# SPDX-License-Identifier: GPL-3.0-or-later
"""Items shown on the desktop and where they come from.

Files are the real content of the XDG desktop directory, enumerated
asynchronously and refreshed through a file monitor. Hidden files (".name")
and backup files ("name~") are not shown, as in Files by default. Symbolic
links are shown with an emblem; broken links can be renamed or trashed but
not opened.
"""

import os
from gettext import gettext as _

from gi.repository import Gio, GLib, GObject

from .model import SortInfo

FILE_ATTRIBUTES = ",".join([
    "standard::name", "standard::display-name", "standard::edit-name",
    "standard::icon", "standard::type", "standard::is-hidden",
    "standard::is-backup", "standard::is-symlink", "standard::size",
    "standard::content-type", "standard::target-uri",
    "time::modified", "thumbnail::path", "thumbnail::is-valid",
    "access::can-execute", "access::can-rename", "access::can-trash",
    "metadata::trusted", "id::filesystem",
])

REFRESH_DELAY_MS = 150


def desktop_directory():
    """The XDG desktop directory, or None when it is the home directory.

    When XDG_DESKTOP_DIR points at the home folder, GNOME treats the user as
    having no desktop folder; showing the whole home folder would be wrong.
    """
    GLib.reload_user_special_dirs_cache()
    path = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP)
    home = GLib.get_home_dir()
    if not path or os.path.realpath(path) == os.path.realpath(home):
        return None
    return Gio.File.new_for_path(path)


class DesktopItem:
    """Something shown as a desktop icon."""

    kind = "file"
    special_rank = -1

    def __init__(self, item_id, name, gicon, uri):
        self.id = item_id
        self.name = name
        self.gicon = gicon
        self.uri = uri
        self.file = Gio.File.new_for_uri(uri)
        self.is_dir = False
        self.thumbnail = None
        self.emblem = None
        self.is_broken_link = False
        self.is_untrusted_launcher = False
        self.content_type = ""
        self.modified = 0
        self.size = 0
        self.filesystem = ""

    # Which actions apply. Special icons override these.
    can_cut_copy = False
    can_trash = False
    can_rename = False
    can_open_with = False
    can_properties = False
    is_drop_target = False

    def sort_info(self):
        return SortInfo(self.id, self.name, GLib.utf8_collate_key_for_filename(self.name, -1),
                        self.is_dir, self.modified, self.size, self.content_type,
                        self.special_rank)

    def signature(self):
        """Changes when the icon needs to be redrawn."""
        return (self.name, self.gicon.to_string() if self.gicon else "", self.thumbnail,
                self.emblem, self.is_broken_link, self.is_untrusted_launcher)


class FileItem(DesktopItem):
    def __init__(self, directory, info):
        name = info.get_name()
        super().__init__(name, info.get_display_name(), info.get_icon(),
                         directory.get_child(name).get_uri())
        self.edit_name = info.get_edit_name() or info.get_display_name()
        file_type = info.get_file_type()
        self.is_dir = file_type == Gio.FileType.DIRECTORY
        self.is_symlink = info.get_is_symlink()
        # With symlinks followed, a broken link still reports the link itself.
        self.is_broken_link = file_type == Gio.FileType.SYMBOLIC_LINK
        self.content_type = info.get_content_type() or ""
        self.size = info.get_size()
        modified = info.get_modification_date_time()
        self.modified = modified.to_unix() if modified else 0
        self.filesystem = info.get_attribute_string("id::filesystem") or ""
        self.can_rename = info.get_attribute_boolean("access::can-rename") \
            if info.has_attribute("access::can-rename") else True
        self.can_trash = info.get_attribute_boolean("access::can-trash") \
            if info.has_attribute("access::can-trash") else True
        self.can_execute = info.get_attribute_boolean("access::can-execute")
        self.can_cut_copy = True
        self.can_open_with = not self.is_broken_link
        self.can_properties = True
        self.is_drop_target = self.is_dir

        if info.get_attribute_boolean("thumbnail::is-valid") or \
                not info.has_attribute("thumbnail::is-valid"):
            self.thumbnail = info.get_attribute_byte_string("thumbnail::path")
        if self.is_symlink:
            self.emblem = "emblem-symbolic-link"

        if self.content_type == "application/x-desktop" and not self.is_broken_link:
            self._load_launcher(info)

    def _load_launcher(self, info):
        """Launchers show their own name and icon only once trusted."""
        trusted = info.get_attribute_as_string("metadata::trusted") == "true"
        if not (trusted and self.can_execute):
            self.is_untrusted_launcher = True
            self.emblem = "emblem-important"
            return
        path = self.file.get_path()
        app_info = Gio.DesktopAppInfo.new_from_filename(path) if path else None
        if app_info is None:
            self.is_untrusted_launcher = True
            return
        self.name = app_info.get_display_name() or self.name
        if app_info.get_icon():
            self.gicon = app_info.get_icon()
            self.thumbnail = None


class HomeItem(DesktopItem):
    kind = "home"
    special_rank = 0
    can_properties = True
    is_drop_target = True

    def __init__(self):
        super().__init__("special:home", _("Home"), Gio.ThemedIcon.new("user-home"),
                         Gio.File.new_for_path(GLib.get_home_dir()).get_uri())
        self.is_dir = True


class TrashItem(DesktopItem):
    kind = "trash"
    special_rank = 1
    is_drop_target = True

    def __init__(self, full):
        super().__init__("special:trash", _("Trash"),
                         Gio.ThemedIcon.new("user-trash-full" if full else "user-trash"),
                         "trash:///")
        self.full = full
        self.is_dir = True

    def signature(self):
        return super().signature() + (self.full,)


class MountItem(DesktopItem):
    kind = "mount"
    special_rank = 2
    is_drop_target = True
    can_properties = True

    def __init__(self, mount):
        root = mount.get_root()
        super().__init__(f"mount:{root.get_uri()}", mount.get_name(), mount.get_icon(),
                         mount.get_default_location().get_uri())
        self.mount = mount
        self.is_dir = True


class DesktopSource(GObject.Object):
    """Keeps the list of desktop items up to date.

    Emits "changed" after any change, and "renamed" (old id, new id) when
    a file is renamed so its remembered position can follow it.
    """

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_LAST, None, ()),
        "renamed": (GObject.SignalFlags.RUN_LAST, None, (str, str)),
    }

    def __init__(self, settings):
        super().__init__()
        self._settings = settings
        self._files = {}
        self._loaded = False
        self._trash_full = False
        self._refresh_id = 0
        self._cancellable = None
        self.directory = desktop_directory()
        self._monitor = None

        if self.directory is not None:
            self._ensure_directory()
            try:
                self._monitor = self.directory.monitor_directory(
                    Gio.FileMonitorFlags.WATCH_MOVES, None)
                self._monitor.connect("changed", self._on_directory_changed)
            except GLib.Error as e:
                print(f"deskence-desktop-icons: cannot monitor the desktop: {e.message}")

        self._trash = Gio.File.new_for_uri("trash:///")
        try:
            self._trash_monitor = self._trash.monitor_directory(Gio.FileMonitorFlags.NONE, None)
            self._trash_monitor.connect("changed", lambda *a: self._query_trash())
        except GLib.Error:
            self._trash_monitor = None
        self._query_trash()

        self._volumes = Gio.VolumeMonitor.get()
        for signal in ("mount-added", "mount-removed", "mount-changed"):
            self._volumes.connect(signal, lambda *a: self.emit("changed"))
        for key in ("show-home", "show-trash", "show-mounts"):
            settings.connect(f"changed::{key}", lambda *a: self.emit("changed"))

        self.refresh()

    @property
    def loaded(self):
        return self._loaded

    def _ensure_directory(self):
        # xdg-user-dirs normally creates it; recreate it if it was removed.
        if not self.directory.query_exists(None):
            try:
                self.directory.make_directory_with_parents(None)
            except GLib.Error:
                pass

    def _on_directory_changed(self, monitor, file, other, event):
        if event == Gio.FileMonitorEvent.RENAMED and other is not None:
            self.emit("renamed", file.get_basename(), other.get_basename())
        self._queue_refresh()

    def _queue_refresh(self):
        if self._refresh_id:
            return
        self._refresh_id = GLib.timeout_add(REFRESH_DELAY_MS, self._refresh_timeout)

    def _refresh_timeout(self):
        self._refresh_id = 0
        self.refresh()
        return GLib.SOURCE_REMOVE

    def refresh(self):
        if self.directory is None:
            self._loaded = True
            self.emit("changed")
            return
        if self._cancellable:
            self._cancellable.cancel()
        self._cancellable = cancellable = Gio.Cancellable()
        files = {}

        def enumerated(directory, result):
            try:
                enumerator = directory.enumerate_children_finish(result)
            except GLib.Error as e:
                if not e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                    print(f"deskence-desktop-icons: cannot read the desktop: {e.message}")
                    self._files = {}
                    self._loaded = True
                    self.emit("changed")
                return
            enumerator.next_files_async(100, GLib.PRIORITY_DEFAULT, cancellable,
                                        next_files, enumerator)

        def next_files(enumerator, result, _data):
            try:
                infos = enumerator.next_files_finish(result)
            except GLib.Error as e:
                if not e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                    print(f"deskence-desktop-icons: reading the desktop failed: {e.message}")
                return
            if not infos:
                enumerator.close_async(GLib.PRIORITY_DEFAULT, None, None)
                self._files = files
                self._loaded = True
                self.emit("changed")
                return
            for info in infos:
                if info.get_is_hidden() or info.get_is_backup():
                    continue
                try:
                    item = FileItem(self.directory, info)
                except (GLib.Error, TypeError) as e:
                    print(f"deskence-desktop-icons: skipping {info.get_name()}: {e}")
                    continue
                files[item.id] = item
            enumerator.next_files_async(100, GLib.PRIORITY_DEFAULT, cancellable,
                                        next_files, enumerator)

        self.directory.enumerate_children_async(FILE_ATTRIBUTES, Gio.FileQueryInfoFlags.NONE,
                                                GLib.PRIORITY_DEFAULT, cancellable, enumerated)

    def _query_trash(self):
        def done(file, result):
            try:
                info = file.query_info_finish(result)
            except GLib.Error:
                return
            full = info.get_attribute_uint32("trash::item-count") > 0
            if full != self._trash_full:
                self._trash_full = full
                self.emit("changed")
        self._trash.query_info_async("trash::item-count", Gio.FileQueryInfoFlags.NONE,
                                     GLib.PRIORITY_DEFAULT, None, done)

    def items(self):
        result = []
        if self._settings.get_boolean("show-home"):
            result.append(HomeItem())
        if self._settings.get_boolean("show-trash"):
            result.append(TrashItem(self._trash_full))
        if self._settings.get_boolean("show-mounts"):
            for mount in self._volumes.get_mounts():
                if mount.is_shadowed() or not mount.get_root().is_native():
                    continue
                if mount.can_eject() or mount.can_unmount():
                    result.append(MountItem(mount))
        result.extend(self._files.values())
        return result

    def file_names(self):
        return set(self._files)
