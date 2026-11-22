# SPDX-License-Identifier: GPL-3.0-or-later
"""The desktop icons application: windows, layout, selection and actions."""

import os
from gettext import gettext as _

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from . import clipboard, model
from .fileops import FileOperations
from .items import DesktopSource
from .positions import PositionStore
from .shellareas import ShellAreas
from .window import INTERNAL_MIME, DesktopWindow

SCHEMA_ID = "io.github.deskence.Deskence.DesktopIcons"
SETTINGS_APP_ID = "io.github.deskence.Deskence"
SETTINGS_APP_PATH = "/io/github/deskence/Deskence"

CSS = """
window.deskence-desktop {
  background: none;
  box-shadow: none;
  border-radius: 0;
}
.desktop-icon {
  padding: 4px;
  border-radius: 9px;
}
.desktop-icon > label {
  color: white;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.9), 0 0 4px rgba(0, 0, 0, 0.6);
}
.desktop-icon:hover {
  background-color: alpha(white, 0.12);
}
.desktop-icon.selected {
  background-color: alpha(@accent_bg_color, 0.6);
}
.desktop-icon.selected > label {
  color: @accent_fg_color;
}
.desktop-icon.cut {
  opacity: 0.55;
}
.desktop-icon.drop-target {
  background-color: alpha(@accent_bg_color, 0.4);
}
/* The desktop itself is a drop target covering the monitor; GTK would draw
   its drop highlight as a rectangle around the whole monitor. Only folders,
   the trash and drives under the pointer are highlighted (above). */
.desktop-canvas:drop(active) {
  box-shadow: none;
  outline: none;
}
"""

ACCELS = {
    "win.select-all": ["<Control>a"],
    "win.copy": ["<Control>c"],
    "win.cut": ["<Control>x"],
    "win.paste": ["<Control>v"],
    "win.trash": ["Delete", "KP_Delete"],
    "win.rename": ["F2"],
    "win.open": ["Return", "KP_Enter"],
    "win.properties": ["<Control>i", "<Alt>Return"],
    "win.new-folder": ["<Shift><Control>n"],
    "win.undo": ["<Control>z"],
}

NAME_ERRORS = {
    "empty": lambda: _("The name cannot be empty."),
    "slash": lambda: _("The name cannot contain “/”."),
    "dot": lambda: _("“.” and “..” are not valid names."),
    "exists": lambda: _("An item with this name already exists."),
    "too-long": lambda: _("The name is too long."),
}


class DesktopApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.deskence.Deskence.DesktopIcons",
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.windows = {}
        self.selection = set()
        self.cut_ids = set()
        self.placements = {}
        self.items_by_id = {}
        self.drag_in_progress = False
        self.drag_ids = []
        self._drag_offsets = {}
        self._drag_grab = (0, 0)
        self._pending_positions = {}
        self._layout_id = 0
        self._primary = None

    # -- Startup ---------------------------------------------------------

    def do_startup(self):
        Adw.Application.do_startup(self)
        if Gio.SettingsSchemaSource.get_default().lookup(SCHEMA_ID, True) is None:
            print(f"deskence-desktop-icons: settings schema {SCHEMA_ID} is not installed")
            self.quit()
            return
        self.settings = Gio.Settings.new(SCHEMA_ID)
        self.settings.connect("changed", self._on_settings_changed)
        self.single_click = self.settings.get_string("click-mode") == "single"
        self.shell_areas = ShellAreas()
        self.shell_areas.connect("changed", lambda a: self.queue_layout())
        self.shell_areas.connect("activate", self._on_shell_menu_activate)

        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        for action, accels in ACCELS.items():
            self.set_accels_for_action(action, accels)

        self.positions = PositionStore()
        self.fileops = FileOperations(self.show_error)
        self.source = DesktopSource(self.settings)
        self.source.connect("changed", lambda s: self.queue_layout())
        self.source.connect("renamed", self._on_renamed)

        self.clipboard = Gdk.Display.get_default().get_clipboard()
        self.clipboard.connect("changed", self._on_clipboard_changed)

        self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._bus.signal_subscribe("org.gnome.Mutter.DisplayConfig",
                                   "org.gnome.Mutter.DisplayConfig", "MonitorsChanged",
                                   "/org/gnome/Mutter/DisplayConfig", None,
                                   Gio.DBusSignalFlags.NONE,
                                   lambda *a: self._query_primary_monitor())
        self._query_primary_monitor()

        # Stay alive while no monitor is connected.
        self.hold()

    def do_activate(self):
        if not hasattr(self, "settings"):
            return
        monitors = Gdk.Display.get_default().get_monitors()
        monitors.connect("items-changed", lambda *a: self._sync_windows())
        self._sync_windows()

    def _sync_windows(self):
        monitors = Gdk.Display.get_default().get_monitors()
        wanted = {}
        for i in range(monitors.get_n_items()):
            monitor = monitors.get_item(i)
            wanted[monitor.get_connector() or str(i)] = monitor
        for connector in list(self.windows):
            if connector not in wanted:
                self.windows.pop(connector).destroy()
        for connector, monitor in wanted.items():
            if connector not in self.windows:
                window = DesktopWindow(self, monitor)
                self.windows[connector] = window
                window.present()
        self.queue_layout()

    def _query_primary_monitor(self):
        def done(bus, result):
            try:
                state = bus.call_finish(result).unpack()
            except GLib.Error:
                return
            for logical in state[2]:
                if logical[4] and logical[5]:
                    self._primary = logical[5][0][0]
                    self.queue_layout()
                    return
        self._bus.call("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
                       "org.gnome.Mutter.DisplayConfig", "GetCurrentState", None, None,
                       Gio.DBusCallFlags.NONE, -1, None, done)

    def _on_settings_changed(self, settings, key):
        if key == "click-mode":
            self.single_click = settings.get_string("click-mode") == "single"
        elif key in ("icon-size", "start-corner"):
            self.queue_layout()
        # "icon-placement" only changes how icons are dropped from now on;
        # existing positions stay until "Align to Grid".

    def _on_shell_menu_activate(self, areas, connector, action, target):
        window = self.windows.get(connector)
        if window is not None:
            window.activate_menu_action(action, target)

    @property
    def snap_to_grid(self):
        return self.settings.get_string("icon-placement") == "grid"

    # -- Layout ----------------------------------------------------------

    def queue_layout(self):
        if not self._layout_id:
            self._layout_id = GLib.idle_add(self._do_layout)

    def _do_layout(self):
        self._layout_id = 0
        if not self.shell_areas.ready:
            return GLib.SOURCE_REMOVE
        items = self.source.items()
        self.items_by_id = {item.id: item for item in items}
        order = [info.id for info in model.sort_items(
            [item.sort_info() for item in items], self.settings.get_string("sort-order"))]

        surfaces = self._surfaces()
        if not surfaces:
            return GLib.SOURCE_REMOVE
        primary = self._primary if self._primary in surfaces else next(iter(surfaces))

        changed = self.positions.upgrade_legacy(surfaces)
        for name, placement in self._pending_positions.items():
            if name in self.items_by_id:
                self.positions.set(name, placement)
                changed = True
        self._pending_positions = {k: v for k, v in self._pending_positions.items()
                                   if k not in self.items_by_id}

        result = model.layout(order, self.positions.for_layout(), surfaces, primary,
                              self.settings.get_string("start-corner"))
        self.placements = result.placements
        changed = changed or bool(result.to_save)
        self.positions.update(result.to_save)
        if self.source.loaded:
            before = len(self.positions)
            self.positions.prune(set(self.items_by_id))
            changed = changed or before != len(self.positions)
        if changed:
            self._save_positions()

        self.selection &= set(self.items_by_id)
        for connector, window in self.windows.items():
            placed = [(self.items_by_id[item_id], p.x, p.y)
                      for item_id, p in result.placements.items() if p.connector == connector]
            window.show_items(placed)
        return GLib.SOURCE_REMOVE

    def _surfaces(self):
        surfaces = {}
        size_nick = self.settings.get_string("icon-size")
        corner = self.settings.get_string("start-corner")
        for connector, window in self.windows.items():
            if not window.layout_ready():
                continue
            window.update_geometry(size_nick, corner)
            surfaces[connector] = window.surface
        return surfaces

    def _slots_on(self, connector, exclude=()):
        """Slot origins of the icons shown on a monitor."""
        return [(p.x, p.y) for item_id, p in self.placements.items()
                if p.connector == connector and item_id not in exclude]

    def _save_positions(self):
        try:
            self.positions.save()
        except OSError as e:
            print(f"deskence-desktop-icons: cannot save icon positions: {e}")

    def _on_renamed(self, source, old_name, new_name):
        self.positions.rename(old_name, new_name)
        if old_name in self.selection:
            self.selection.discard(old_name)
            self.selection.add(new_name)
        self._save_positions()

    # -- Selection -------------------------------------------------------

    def select(self, ids, notify_windows=True):
        self.selection = set(ids)
        if notify_windows:
            self.refresh_selection()

    def toggle_selected(self, item_id):
        self.selection ^= {item_id}
        self.refresh_selection()

    def refresh_selection(self):
        for window in self.windows.values():
            window.refresh_selection()

    def selected_items(self):
        return [self.items_by_id[i] for i in self.selection if i in self.items_by_id]

    def accent_color(self):
        manager = Adw.StyleManager.get_default()
        if hasattr(manager, "get_accent_color_rgba"):
            return manager.get_accent_color_rgba()
        color = Gdk.RGBA()
        color.parse("#3584e4")
        return color

    # -- Drag and drop ---------------------------------------------------

    def begin_drag(self, window, pressed_id, grab):
        """grab: the point held, relative to the slot of the pressed icon."""
        ids = [i for i in self.selection if i in self.items_by_id]
        anchor = self.placements[pressed_id]
        self._drag_grab = grab
        self._drag_offsets = {}
        for item_id in ids:
            p = self.placements.get(item_id)
            if p is not None and p.connector == anchor.connector:
                self._drag_offsets[item_id] = (p.x - anchor.x, p.y - anchor.y)
        # The pressed icon first: it lands under the pointer. Icons from other
        # monitors have no offset and go to free cells next to the group.
        far = (float("inf"), float("inf"))
        ids.sort(key=lambda i: (i != pressed_id, self._drag_offsets.get(i, far)[::-1]))
        self.drag_ids = ids
        self.drag_in_progress = True

        providers = [Gdk.ContentProvider.new_for_bytes(
            INTERNAL_MIME, GLib.Bytes.new("\n".join(ids).encode("utf-8")))]
        files = [self.items_by_id[i].file for i in ids if self.items_by_id[i].kind == "file"]
        if files:
            file_list = Gdk.FileList.new_from_list(files)
            providers.append(Gdk.ContentProvider.new_for_value(
                GObject.Value(Gdk.FileList, file_list)))
        return Gdk.ContentProvider.new_union(providers)

    def end_drag(self):
        self.drag_in_progress = False
        self.drag_ids = []
        self._drag_offsets = {}

    def drop_internal(self, window, x, y):
        """Icons dragged within the desktop: only their position changes.

        The files stay where they are, whatever the drag action was.
        """
        ax, ay = window.to_monitor(x, y)
        anchor = (ax - self._drag_grab[0], ay - self._drag_grab[1])
        others = self._slots_on(window.connector, exclude=self.drag_ids)
        slots = model.place_dropped(self.drag_ids, anchor, self._drag_offsets,
                                    window.surface, others, self.snap_to_grid)
        for item_id, slot in slots.items():
            self.positions.set(item_id, model.Placement(window.connector, *slot))
        self._save_positions()
        self.queue_layout()

    def align_to_grid(self, window):
        """Put the icons of every monitor into the nearest free grid cells.

        A one-off action: the placement mode does not change.
        """
        for connector, w in self.windows.items():
            slots = {item_id: (p.x, p.y) for item_id, p in self.placements.items()
                     if p.connector == connector}
            if not slots:
                continue
            for item_id, slot in model.align_to_grid(slots, w.surface).items():
                self.positions.set(item_id, model.Placement(connector, *slot))
        self._save_positions()
        self.queue_layout()

    def _slots_for_new(self, window, x, y, names):
        """Remember where new files created or dropped at a point go."""
        ax, ay = window.to_monitor(x, y)
        anchor = model.slot_for_point(ax, ay, window.surface, window.icon_size,
                                      self.snap_to_grid)
        slots = model.place_dropped(names, anchor, {}, window.surface,
                                    self._slots_on(window.connector), self.snap_to_grid)
        for name, slot in slots.items():
            self._pending_positions[name] = model.Placement(window.connector, *slot)

    def drop_files(self, window, x, y, files, target_item, copy):
        uris = [f.get_uri() for f in files]
        if target_item is not None and target_item.kind == "trash":
            self.fileops.trash(uris)
            return
        if target_item is not None:
            destination = target_item.file
        elif self.source.directory is not None:
            destination = self.source.directory
            self._slots_for_new(window, x, y, [f.get_basename() for f in files])
            already_here = [f for f in files if f.get_parent() and
                            f.get_parent().equal(destination)]
            if already_here:
                self.queue_layout()
            files = [f for f in files if f not in already_here]
            uris = [f.get_uri() for f in files]
        else:
            return
        if not uris:
            return
        if copy:
            self.fileops.copy(uris, destination.get_uri())
            return
        # Like Files: moving within a file system, copying across them.
        same, other = [], []
        dest_fs = self._filesystem_id(destination)
        for f in files:
            if f.is_native() and dest_fs and self._filesystem_id(f) == dest_fs:
                same.append(f.get_uri())
            else:
                other.append(f.get_uri())
        if same:
            self.fileops.move(same, destination.get_uri())
        if other:
            self.fileops.copy(other, destination.get_uri())

    @staticmethod
    def _filesystem_id(file):
        try:
            info = file.query_info("id::filesystem", Gio.FileQueryInfoFlags.NONE, None)
            return info.get_attribute_string("id::filesystem")
        except GLib.Error:
            return None

    # -- Clipboard -------------------------------------------------------

    def _set_clipboard(self, items, cut):
        uris = [item.uri for item in items]
        paths = [item.file.get_path() or item.uri for item in items]
        provider = Gdk.ContentProvider.new_union([
            Gdk.ContentProvider.new_for_bytes(
                clipboard.GNOME_COPIED_FILES,
                GLib.Bytes.new(clipboard.encode_gnome_copied_files(uris, cut))),
            Gdk.ContentProvider.new_for_bytes(
                clipboard.URI_LIST, GLib.Bytes.new(clipboard.encode_uri_list(uris))),
            Gdk.ContentProvider.new_for_bytes(
                clipboard.TEXT_PLAIN, GLib.Bytes.new("\n".join(paths).encode("utf-8"))),
        ])
        self.clipboard.set_content(provider)
        self.cut_ids = {item.id for item in items} if cut else set()
        self.refresh_selection()

    def _on_clipboard_changed(self, cb):
        if not cb.is_local() and self.cut_ids:
            self.cut_ids = set()
            self.refresh_selection()

    def clipboard_has_files(self):
        formats = self.clipboard.get_formats()
        return formats.contain_mime_type(clipboard.GNOME_COPIED_FILES) or \
            formats.contain_mime_type(clipboard.URI_LIST)

    def paste(self):
        if self.source.directory is None:
            return
        destination = self.source.directory.get_uri()

        def read_done(cb, result):
            try:
                stream, mime = cb.read_finish(result)
            except GLib.Error:
                return
            output = Gio.MemoryOutputStream.new_resizable()

            def spliced(out, res):
                try:
                    out.splice_finish(res)
                except GLib.Error:
                    return
                data = out.steal_as_bytes().get_data()
                if mime == clipboard.GNOME_COPIED_FILES:
                    decoded = clipboard.decode_gnome_copied_files(data)
                    if decoded is None:
                        return
                    cut, uris = decoded
                else:
                    cut, uris = False, clipboard.decode_uri_list(data)
                if not uris:
                    return
                if cut:
                    self.fileops.move(uris, destination)
                    self.clipboard.set_content(None)
                    self.cut_ids = set()
                else:
                    self.fileops.copy(uris, destination)

            output.splice_async(stream, Gio.OutputStreamSpliceFlags.CLOSE_SOURCE |
                                Gio.OutputStreamSpliceFlags.CLOSE_TARGET,
                                GLib.PRIORITY_DEFAULT, None, spliced)

        self.clipboard.read_async([clipboard.GNOME_COPIED_FILES, clipboard.URI_LIST],
                                  GLib.PRIORITY_DEFAULT, None, read_done)

    # -- Opening ---------------------------------------------------------

    def open_items(self, items, window):
        for item in items:
            self._open(item, window)

    def _launch_context(self):
        return Gdk.Display.get_default().get_app_launch_context()

    def _open_uri(self, uri):
        def done(_o, result):
            try:
                Gio.AppInfo.launch_default_for_uri_finish(result)
            except GLib.Error as e:
                self.show_error(_("Cannot open the location"), e.message)
        Gio.AppInfo.launch_default_for_uri_async(uri, self._launch_context(), None, done)

    def _open(self, item, window):
        if item.kind != "file" or item.is_dir:
            self._open_uri(item.uri)
            return
        if item.is_broken_link:
            self.show_error(_("Cannot open “{}”").format(item.name),
                            _("The link is broken: the item it points to does not exist."))
            return
        if item.content_type == "application/x-desktop":
            if item.is_untrusted_launcher:
                self._ask_allow_launch(item)
            else:
                self._launch_desktop_file(item)
            return
        launcher = Gtk.FileLauncher.new(item.file)

        def done(l, result):
            try:
                l.launch_finish(result)
            except GLib.Error as e:
                if not e.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                    self.show_error(_("Cannot open “{}”").format(item.name), e.message)
        launcher.launch(None, None, done)

    def _launch_desktop_file(self, item):
        info = Gio.DesktopAppInfo.new_from_filename(item.file.get_path())
        if info is None:
            self.show_error(_("Cannot open “{}”").format(item.name),
                            _("The launcher is not valid."))
            return
        try:
            info.launch([], self._launch_context())
        except GLib.Error as e:
            self.show_error(_("Cannot start “{}”").format(item.name), e.message)

    def _ask_allow_launch(self, item):
        dialog = Adw.AlertDialog(
            heading=_("Untrusted Launcher"),
            body=_("“{}” has not been marked as trusted. Only allow launching "
                   "if you know where this file comes from.").format(item.name))
        dialog.add_response("cancel", _("_Cancel"))
        dialog.add_response("allow", _("_Allow and Launch"))
        dialog.set_close_response("cancel")
        dialog.set_default_response("cancel")

        def response(d, answer):
            if answer == "allow" and self._allow_launch(item):
                self._launch_desktop_file(item)
        dialog.connect("response", response)
        dialog.present(None)

    def _allow_launch(self, item):
        try:
            info = item.file.query_info("unix::mode", Gio.FileQueryInfoFlags.NONE, None)
            mode = info.get_attribute_uint32("unix::mode")
            item.file.set_attribute_uint32("unix::mode", mode | 0o111,
                                           Gio.FileQueryInfoFlags.NONE, None)
            item.file.set_attribute_string("metadata::trusted", "true",
                                           Gio.FileQueryInfoFlags.NONE, None)
        except GLib.Error as e:
            self.show_error(_("Cannot allow launching “{}”").format(item.name), e.message)
            return False
        self.source.refresh()
        return True

    # -- Errors ----------------------------------------------------------

    def show_error(self, title, message):
        dialog = Adw.AlertDialog(heading=title, body=message)
        dialog.add_response("close", _("_Close"))
        dialog.present(None)

    # -- Actions and menus -----------------------------------------------

    def install_window_actions(self, window):
        def add(name, callback, parameter_type=None):
            action = Gio.SimpleAction.new(name, parameter_type)
            action.connect("activate", lambda a, p: callback(window, p))
            window.add_action(action)

        add("new-folder", self._action_new_folder)
        add("paste", lambda w, p: self.paste())
        add("select-all", lambda w, p: self.select(list(self.items_by_id)))
        add("arrange", lambda w, p: self.arrange())
        add("align-to-grid", lambda w, p: self.align_to_grid(w))
        add("change-background", lambda w, p: self._spawn(["gnome-control-center", "background"]))
        add("desktop-settings", lambda w, p: self.open_settings())
        add("open", lambda w, p: self.open_items(self.selected_items(), w))
        add("open-with", self._action_open_with)
        add("cut", lambda w, p: self._copy_or_cut(True))
        add("copy", lambda w, p: self._copy_or_cut(False))
        add("rename", self._action_rename)
        add("trash", lambda w, p: self._action_trash())
        add("properties", lambda w, p: self._action_properties())
        add("empty-trash", lambda w, p: self.fileops.empty_trash())
        add("unmount", lambda w, p: self._action_unmount(False))
        add("eject", lambda w, p: self._action_unmount(True))
        add("allow-launch", lambda w, p: [self._allow_launch(i) for i in self.selected_items()])
        add("undo", lambda w, p: self.fileops.undo())

        sort = Gio.SimpleAction.new_stateful(
            "sort-order", GLib.VariantType.new("s"),
            GLib.Variant("s", self.settings.get_string("sort-order")))
        sort.connect("change-state", self._on_sort_order)
        self.settings.connect("changed::sort-order", lambda s, k: sort.set_state(
            GLib.Variant("s", s.get_string(k))))
        window.add_action(sort)

    def _on_sort_order(self, action, value):
        action.set_state(value)
        self.settings.set_string("sort-order", value.get_string())
        self.arrange()

    def arrange(self):
        """Forget remembered positions and lay icons out in sort order."""
        self.positions.clear()
        self._save_positions()
        self.queue_layout()

    def _spawn(self, argv):
        try:
            info = Gio.AppInfo.create_from_commandline(
                " ".join(GLib.shell_quote(a) for a in argv), None, Gio.AppInfoCreateFlags.NONE)
            info.launch([], self._launch_context())
        except GLib.Error as e:
            self.show_error(_("Cannot open Settings"), e.message)

    def open_settings(self):
        """Open the "Desktop Icons" page of Deskence."""
        def done(bus, result):
            try:
                bus.call_finish(result)
            except GLib.Error as e:
                self.show_error(_("Cannot open Deskence"), e.message)
        self._bus.call(SETTINGS_APP_ID, SETTINGS_APP_PATH, "org.freedesktop.Application",
                       "ActivateAction",
                       GLib.Variant("(sava{sv})", ("show-page", [GLib.Variant("s", "desktop-icons")], {})),
                       None, Gio.DBusCallFlags.NONE, -1, None, done)

    def _file_selection(self):
        items = self.selected_items()
        if items and all(item.kind == "file" for item in items):
            return items
        return []

    def _copy_or_cut(self, cut):
        items = [i for i in self._file_selection() if i.can_cut_copy]
        if items:
            self._set_clipboard(items, cut)

    def _action_trash(self):
        items = [i for i in self._file_selection() if i.can_trash]
        if items:
            self.fileops.trash([i.uri for i in items])

    def _action_properties(self):
        items = [i for i in self.selected_items() if i.can_properties]
        if items:
            self.fileops.show_properties([i.uri for i in items])

    def _action_open_with(self, window, _param):
        items = self._file_selection()
        if len(items) != 1:
            return
        launcher = Gtk.FileLauncher.new(items[0].file)
        launcher.set_always_ask(True)

        def done(l, result):
            try:
                l.launch_finish(result)
            except GLib.Error as e:
                if not e.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                    self.show_error(_("Cannot open “{}”").format(items[0].name), e.message)
        launcher.launch(None, None, done)

    def _action_unmount(self, eject):
        items = [i for i in self.selected_items() if i.kind == "mount"]
        for item in items:
            mount = item.mount
            operation = Gtk.MountOperation.new(None)

            def done(m, result, item=item):
                try:
                    if eject:
                        m.eject_with_operation_finish(result)
                    else:
                        m.unmount_with_operation_finish(result)
                except GLib.Error as e:
                    if not e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.FAILED_HANDLED):
                        self.show_error(_("Cannot unmount “{}”").format(item.name), e.message)
            if eject:
                mount.eject_with_operation(Gio.MountUnmountFlags.NONE, operation, None, done)
            else:
                mount.unmount_with_operation(Gio.MountUnmountFlags.NONE, operation, None, done)

    # Name popovers (rename and new folder), like the ones in Files.

    def _name_popover(self, title, button_label, initial, existing, current, on_accept):
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                      margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        label = Gtk.Label(label=title, xalign=0)
        label.add_css_class("heading")
        entry = Gtk.Entry(text=initial, activates_default=True, width_chars=24)
        entry.update_property([Gtk.AccessibleProperty.LABEL], [title])
        error = Gtk.Label(xalign=0, wrap=True, max_width_chars=30, visible=False)
        error.add_css_class("error")
        error.add_css_class("caption")
        button = Gtk.Button(label=button_label, halign=Gtk.Align.END, use_underline=True)
        button.add_css_class("suggested-action")
        for widget in (label, entry, error, button):
            box.append(widget)
        popover.set_child(box)
        popover.set_default_widget(button)

        def validate(*_a):
            problem = model.validate_file_name(entry.get_text(), existing, current)
            error.set_visible(problem is not None and entry.get_text() != "")
            if problem:
                error.set_label(NAME_ERRORS[problem]())
            elif model.name_is_hidden(entry.get_text()):
                error.set_label(_("Names starting with “.” are hidden."))
                error.set_visible(True)
            button.set_sensitive(problem is None and entry.get_text() != current)
            return problem is None

        def accept(*_a):
            if validate():
                popover.popdown()
                on_accept(entry.get_text())

        entry.connect("changed", validate)
        entry.connect("activate", accept)
        button.connect("clicked", accept)
        validate()

        def select_name(*_a):
            entry.grab_focus()
            base, ext = os.path.splitext(initial)
            entry.select_region(0, len(base) if ext and base else -1)
        popover.connect("show", lambda p: GLib.idle_add(select_name))
        return popover

    def _action_new_folder(self, window, _param):
        if self.source.directory is None:
            return
        point = window.menu_point
        existing = self.source.file_names()
        name = _("New Folder")
        n = 2
        while name in existing:
            name = _("New Folder") + f" ({n})"
            n += 1

        def create(new_name):
            self._slots_for_new(window, *point, [new_name])
            self.fileops.create_folder(self.source.directory.get_uri(), new_name)

        popover = self._name_popover(_("Folder Name"), _("_Create"), name, existing, None, create)
        window.popup_at_point(popover)

    def _action_rename(self, window, _param):
        items = self._file_selection()
        if len(items) != 1 or not items[0].can_rename:
            return
        item = items[0]
        existing = self.source.file_names()
        title = _("Rename Folder") if item.is_dir else _("Rename File")

        def rename(new_name):
            self.positions.rename(item.id, new_name)
            self._save_positions()
            self.fileops.rename(item.uri, new_name)

        popover = self._name_popover(title, _("_Rename"), item.edit_name, existing,
                                     item.edit_name, rename)
        target = window if item.id in window.icons else self._window_of(item.id)
        target.popup_at_icon(popover, item.id)

    def _window_of(self, item_id):
        placement = self.placements.get(item_id)
        if placement and placement.connector in self.windows:
            return self.windows[placement.connector]
        return next(iter(self.windows.values()))

    def build_desktop_menu(self):
        menu = Gio.Menu()
        section = Gio.Menu()
        if self.source.directory is not None:
            section.append(_("New _Folder…"), "win.new-folder")
            section.append(_("_Paste"), "win.paste")
        section.append(_("Select _All"), "win.select-all")
        menu.append_section(None, section)

        section = Gio.Menu()
        section.append(_("A_rrange Icons"), "win.arrange")
        section.append(_("Align to _Grid"), "win.align-to-grid")
        sort = Gio.Menu()
        for value, label in (("name", _("_Name")), ("modified", _("_Modified")),
                             ("size", _("_Size")), ("type", _("_Type"))):
            sort.append(label, f"win.sort-order::{value}")
        section.append_submenu(_("_Sort By"), sort)
        menu.append_section(None, section)

        section = Gio.Menu()
        section.append(_("Change _Background…"), "win.change-background")
        section.append(_("_Desktop Settings"), "win.desktop-settings")
        menu.append_section(None, section)

        for window in self.windows.values():
            window.lookup_action("paste").set_enabled(self.clipboard_has_files())
        return menu

    def build_item_menu(self):
        items = self.selected_items()
        menu = Gio.Menu()
        if not items:
            return menu
        files = [i for i in items if i.kind == "file"]
        single = items[0] if len(items) == 1 else None

        section = Gio.Menu()
        section.append(_("_Open"), "win.open")
        if single and single.kind == "file" and single.can_open_with and not single.is_dir:
            section.append(_("Open _With…"), "win.open-with")
        if single and single.kind == "file" and single.is_untrusted_launcher:
            section.append(_("Allow _Launching"), "win.allow-launch")
        menu.append_section(None, section)

        if len(files) == len(items):
            section = Gio.Menu()
            section.append(_("Cu_t"), "win.cut")
            section.append(_("_Copy"), "win.copy")
            if single and single.can_rename:
                section.append(_("Rena_me…"), "win.rename")
            menu.append_section(None, section)
            if all(i.can_trash for i in files):
                section = Gio.Menu()
                section.append(_("Move to _Trash"), "win.trash")
                menu.append_section(None, section)
        elif single and single.kind == "trash":
            section = Gio.Menu()
            section.append(_("_Empty Trash…"), "win.empty-trash")
            menu.append_section(None, section)
            for window in self.windows.values():
                window.lookup_action("empty-trash").set_enabled(single.full)
        elif single and single.kind == "mount":
            section = Gio.Menu()
            if single.mount.can_eject():
                section.append(_("_Eject"), "win.eject")
            elif single.mount.can_unmount():
                section.append(_("_Unmount"), "win.unmount")
            menu.append_section(None, section)

        if all(i.can_properties for i in items):
            section = Gio.Menu()
            section.append(_("_Properties"), "win.properties")
            menu.append_section(None, section)
        return menu
