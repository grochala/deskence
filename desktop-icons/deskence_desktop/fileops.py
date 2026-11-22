# SPDX-License-Identifier: GPL-3.0-or-later
"""File operations for the desktop.

Copying, moving, trashing, renaming and creating folders are delegated to
Files (org.gnome.Nautilus.FileOperations2). Files shows progress, asks what to
do about name conflicts, reports errors and supports undo, exactly as for
operations started in Files itself.

When Files is not installed, asynchronous Gio fallbacks are used. They never
overwrite: a conflicting name gets a free variant such as "name (2).txt".
Nothing is ever deleted permanently; if the trash is unavailable the
operation fails with an error.
"""

import os
from gettext import gettext as _

from gi.repository import Gio, GLib

NAUTILUS_NAME = "org.gnome.Nautilus"
NAUTILUS_PATH = "/org/gnome/Nautilus/FileOperations2"
NAUTILUS_IFACE = "org.gnome.Nautilus.FileOperations2"

FILE_MANAGER_NAME = "org.freedesktop.FileManager1"
FILE_MANAGER_PATH = "/org/freedesktop/FileManager1"

_MISSING_SERVICE_ERRORS = (
    "org.freedesktop.DBus.Error.ServiceUnknown",
    "org.freedesktop.DBus.Error.NameHasNoOwner",
    "org.freedesktop.DBus.Error.UnknownMethod",
    "org.freedesktop.DBus.Error.Spawn.ServiceNotFound",
)


def free_name(directory, name):
    """A name not used in directory, keeping the extension: "a (2).txt"."""
    if not directory.get_child(name).query_exists(None):
        return name
    base, ext = os.path.splitext(name)
    if base == "" or name.startswith(".") and base == name:
        base, ext = name, ""
    for n in range(2, 10000):
        candidate = f"{base} ({n}){ext}"
        if not directory.get_child(candidate).query_exists(None):
            return candidate
    raise GLib.Error("No free file name")


def _is_missing_service(error):
    if Gio.DBusError.is_remote_error(error):
        return Gio.DBusError.get_remote_error(error) in _MISSING_SERVICE_ERRORS
    return error.domain == GLib.quark_to_string(Gio.DBusError.quark()) and error.code in (
        Gio.DBusError.SERVICE_UNKNOWN, Gio.DBusError.NAME_HAS_NO_OWNER,
        Gio.DBusError.UNKNOWN_METHOD, Gio.DBusError.SPAWN_SERVICE_NOT_FOUND)


class FileOperations:
    """on_error(title, message) is called for errors not shown by Files."""

    def __init__(self, on_error):
        self._on_error = on_error
        self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    # -- Files (Nautilus) -------------------------------------------------

    def _call_nautilus(self, method, params, fallback):
        def done(bus, result):
            try:
                bus.call_finish(result)
            except GLib.Error as e:
                if _is_missing_service(e):
                    fallback()
                else:
                    self._on_error(_("The operation failed"), e.message)

        self._bus.call(NAUTILUS_NAME, NAUTILUS_PATH, NAUTILUS_IFACE, method,
                       params, None, Gio.DBusCallFlags.NONE, -1, None, done)

    @staticmethod
    def _platform_data():
        return {"window-position": GLib.Variant("s", "center")}

    def copy(self, uris, destination_uri):
        self._call_nautilus(
            "CopyURIs",
            GLib.Variant("(assa{sv})", (uris, destination_uri, self._platform_data())),
            lambda: self._fallback_transfer(uris, destination_uri, move=False))

    def move(self, uris, destination_uri):
        self._call_nautilus(
            "MoveURIs",
            GLib.Variant("(assa{sv})", (uris, destination_uri, self._platform_data())),
            lambda: self._fallback_transfer(uris, destination_uri, move=True))

    def trash(self, uris):
        self._call_nautilus(
            "TrashURIs",
            GLib.Variant("(asa{sv})", (uris, self._platform_data())),
            lambda: self._fallback_trash(uris))

    def rename(self, uri, new_name):
        self._call_nautilus(
            "RenameURI",
            GLib.Variant("(ssa{sv})", (uri, new_name, self._platform_data())),
            lambda: self._fallback_rename(uri, new_name))

    def create_folder(self, parent_uri, name):
        self._call_nautilus(
            "CreateFolder",
            GLib.Variant("(ssa{sv})", (parent_uri, name, self._platform_data())),
            lambda: self._fallback_create_folder(parent_uri, name))

    def empty_trash(self):
        self._call_nautilus(
            "EmptyTrash",
            GLib.Variant("(ba{sv})", (True, self._platform_data())),
            lambda: self._on_error(_("Cannot empty the trash"),
                                   _("Emptying the trash needs the Files application.")))

    def undo(self):
        self._call_nautilus("Undo", GLib.Variant("(a{sv})", (self._platform_data(),)),
                            lambda: None)

    def show_properties(self, uris):
        def done(bus, result):
            try:
                bus.call_finish(result)
            except GLib.Error as e:
                self._on_error(_("Cannot show properties"), e.message)

        self._bus.call(FILE_MANAGER_NAME, FILE_MANAGER_PATH, FILE_MANAGER_NAME,
                       "ShowItemProperties", GLib.Variant("(ass)", (uris, "")),
                       None, Gio.DBusCallFlags.NONE, -1, None, done)

    # -- Gio fallbacks ----------------------------------------------------

    def _report(self, title):
        def handler(error):
            if not error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                self._on_error(title, error.message)
        return handler

    def _fallback_trash(self, uris):
        report = self._report(_("Cannot move to the trash"))
        for uri in uris:
            file = Gio.File.new_for_uri(uri)

            def done(f, result):
                try:
                    f.trash_finish(result)
                except GLib.Error as e:
                    report(e)
            file.trash_async(GLib.PRIORITY_DEFAULT, None, done)

    def _fallback_rename(self, uri, new_name):
        report = self._report(_("Cannot rename"))

        def done(f, result):
            try:
                f.set_display_name_finish(result)
            except GLib.Error as e:
                report(e)
        Gio.File.new_for_uri(uri).set_display_name_async(
            new_name, GLib.PRIORITY_DEFAULT, None, done)

    def _fallback_create_folder(self, parent_uri, name):
        report = self._report(_("Cannot create the folder"))
        parent = Gio.File.new_for_uri(parent_uri)
        try:
            folder = parent.get_child(free_name(parent, name))
        except GLib.Error as e:
            report(e)
            return

        def done(f, result):
            try:
                f.make_directory_finish(result)
            except GLib.Error as e:
                report(e)
        folder.make_directory_async(GLib.PRIORITY_DEFAULT, None, done)

    def _fallback_transfer(self, uris, destination_uri, move):
        report = self._report(_("Cannot move the files") if move else _("Cannot copy the files"))
        destination = Gio.File.new_for_uri(destination_uri)
        for uri in uris:
            source = Gio.File.new_for_uri(uri)
            if move and source.get_parent() and source.get_parent().equal(destination):
                continue
            try:
                target = destination.get_child(free_name(destination, source.get_basename()))
            except GLib.Error as e:
                report(e)
                continue
            if move:
                self._move(source, target, report)
            else:
                self._copy(source, target, report)

    def _move(self, source, target, report):
        def done(f, result):
            try:
                f.move_finish(result)
            except GLib.Error as e:
                if e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.WOULD_RECURSE) or \
                        e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.NOT_SUPPORTED):
                    # Directory across file systems: copy, then trash the
                    # original only when the copy succeeded.
                    self._copy(source, target, report,
                               on_done=lambda: self._fallback_trash([source.get_uri()]))
                else:
                    report(e)
        source.move_async(target, Gio.FileCopyFlags.NOFOLLOW_SYMLINKS,
                          GLib.PRIORITY_DEFAULT, None, None, None, done)

    def _copy(self, source, target, report, on_done=None):
        def queried(f, result):
            try:
                info = f.query_info_finish(result)
            except GLib.Error as e:
                report(e)
                return
            if info.get_file_type() == Gio.FileType.DIRECTORY:
                self._copy_directory(source, target, report, on_done)
            else:
                source.copy_async(target, Gio.FileCopyFlags.NOFOLLOW_SYMLINKS,
                                  GLib.PRIORITY_DEFAULT, None, None, None, copied)

        def copied(f, result):
            try:
                f.copy_finish(result)
            except GLib.Error as e:
                report(e)
                return
            if on_done:
                on_done()

        source.query_info_async("standard::type", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
                                GLib.PRIORITY_DEFAULT, None, queried)

    def _copy_directory(self, source, target, report, on_done):
        def made(f, result):
            try:
                f.make_directory_finish(result)
            except GLib.Error as e:
                report(e)
                return
            source.enumerate_children_async("standard::name",
                                            Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
                                            GLib.PRIORITY_DEFAULT, None, enumerated)

        def enumerated(f, result):
            try:
                enumerator = f.enumerate_children_finish(result)
            except GLib.Error as e:
                report(e)
                return
            names = [info.get_name() for info in enumerator]
            enumerator.close(None)
            remaining = [len(names)]
            if not names and on_done:
                on_done()

            def child_done():
                remaining[0] -= 1
                if remaining[0] == 0 and on_done:
                    on_done()
            for name in names:
                self._copy(source.get_child(name), target.get_child(name), report, child_done)

        target.make_directory_async(GLib.PRIORITY_DEFAULT, None, made)
