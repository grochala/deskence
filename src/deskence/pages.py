# SPDX-License-Identifier: GPL-3.0-or-later
"""The settings pages of the features."""

import os
import sys
from gettext import gettext as _

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import appsicon, button_layout, control, features, languages, presets
from .appgrid import AppGrid
from .previews import DockPreview, IconsPreview  # noqa: F401 (registers types)
from .shell import FeatureStatus
from .shortcuts import ShortcutRow

SCHEMA = "io.github.deskence.Deskence"
UI = "/io/github/deskence/Deskence/ui/"

FEATURE_UUIDS = features.UUIDS


# Dock settings shown in the screen previews.
DOCK_PREVIEW_KEYS = ("position", "length", "icon-size", "show-apps-button",
                     "apps-button-position", "background-custom-color", "background-color",
                     "background-custom-transparency", "background-transparency")


def dock_preview_settings(settings):
    """Arguments of ScreenPreview.set_dock() from the dock settings."""
    apps_button = settings.get_string("apps-button-position") \
        if settings.get_boolean("show-apps-button") else None
    background = None
    rgba = Gdk.RGBA()
    if settings.get_boolean("background-custom-color") and \
            rgba.parse(settings.get_string("background-color")):
        alpha = 1 - settings.get_int("background-transparency") / 100 \
            if settings.get_boolean("background-custom-transparency") else 1.0
        background = (rgba.red, rgba.green, rgba.blue, alpha)
    return (settings.get_string("position"), settings.get_string("length"),
            settings.get_int("icon-size"), apps_button, background)


def bind_combo(row, settings, key, nicks):
    """Two-way binding of an enum key to a combo row, in nicks order."""
    def from_settings(*_args):
        nick = settings.get_string(key)
        if nick in nicks and row.get_selected() != nicks.index(nick):
            row.set_selected(nicks.index(nick))

    def to_settings(*_args):
        if getattr(row, "deskence_updating", False):
            return
        index = row.get_selected()
        if 0 <= index < len(nicks) and settings.get_string(key) != nicks[index]:
            settings.set_string(key, nicks[index])

    settings.connect(f"changed::{key}", from_settings)
    from_settings()
    row.connect("notify::selected", to_settings)


def color_string(rgba):
    """"#rrggbb" of a Gdk.RGBA; its alpha is ignored (transparency is a
    separate setting)."""
    return "#{:02x}{:02x}{:02x}".format(*(round(c * 255) for c in
                                          (rgba.red, rgba.green, rgba.blue)))


def bind_color(button, settings, key):
    """Keep a color button (no alpha) and a "#rrggbb" key in sync."""
    syncing = False

    def to_button(*args):
        nonlocal syncing
        rgba = Gdk.RGBA()
        if not rgba.parse(settings.get_string(key)):
            return
        current = button.get_rgba()
        if current is None or not current.equal(rgba):
            syncing = True
            button.set_rgba(rgba)
            syncing = False

    def to_settings(*args):
        if syncing:
            return
        value = color_string(button.get_rgba())
        if settings.get_string(key) != value:
            settings.set_string(key, value)

    button.connect("notify::rgba", to_settings)
    settings.connect(f"changed::{key}", to_button)
    to_button()


def bind_scale_marks(scale, label):
    scale.set_format_value_func(lambda s, v: f"{v:.0f} %")
    for value, text in ((0, _("Opaque")), (100, _("Transparent"))):
        scale.add_mark(value, Gtk.PositionType.BOTTOM, text)
    scale.update_property([Gtk.AccessibleProperty.LABEL], [label])


def confirm(parent, heading, body, action_label, on_confirm, destructive=True):
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("cancel", _("_Cancel"))
    dialog.add_response("confirm", action_label)
    dialog.set_response_appearance(
        "confirm", Adw.ResponseAppearance.DESTRUCTIVE if destructive
        else Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")
    dialog.connect("response", lambda d, r: on_confirm() if r == "confirm" else None)
    dialog.present(parent)


def restore_defaults(shell, *scopes):
    """"Restore Default Settings" of a page: the same scopes as on the
    command line (control.reset_keys())."""
    store = presets.SettingsStore()
    enabled = control.enabled_features(shell)
    for scope in scopes:
        control.reset(store, control.plan_reset(store, scope, enabled), AppGrid(),
                      lambda module, on: shell.set_enabled(features.UUIDS[module], on))


def open_uri(widget, uri):
    """Opens uri in its application, in the language the application was
    started with, not the one chosen for Deskence (languages.py)."""
    context = widget.get_display().get_app_launch_context()
    for name, value in languages.original_environment().items():
        if value is None:
            context.unsetenv(name)
        else:
            context.setenv(name, value)

    def done(_source, result):
        try:
            Gio.AppInfo.launch_default_for_uri_finish(result)
        except GLib.Error as e:
            print(f"deskence: cannot open {uri}: {e.message}", file=sys.stderr)

    Gio.AppInfo.launch_default_for_uri_async(uri, context, None, done)


class FeatureController:
    """Connects a page's main switch to one of our GNOME Shell extensions.

    The switch shows whether the feature is enabled; rows below it explain
    the actual state (needs a new login, error, conflicts...). Settings of a
    disabled feature are dimmed.
    """

    def __init__(self, page, feature, shell, switch_row, group, dependent):
        self.page = page
        self.feature = feature
        self.uuid = FEATURE_UUIDS[feature]
        self.shell = shell
        self.switch_row = switch_row
        self.group = group
        self.dependent = dependent
        self._rows = []
        self._syncing = False
        if switch_row is not None:
            switch_row.connect("notify::active", self._on_switch)
        shell.connect("changed", lambda *a: self.sync())
        self.sync()

    def _on_switch(self, row, _pspec):
        if not self._syncing:
            self.shell.set_enabled(self.uuid, row.get_active())

    def status(self):
        return self.shell.status(self.uuid)

    def sync(self):
        enabled = self.shell.is_enabled(self.uuid)
        status = self.status()
        for row in self._rows:
            self.group.remove(row)
        self._rows = []
        if self.switch_row is not None:
            self._syncing = True
            self.switch_row.set_active(enabled)
            self._syncing = False
            self.switch_row.set_sensitive(status.state != FeatureStatus.NOT_INSTALLED)
            self.switch_row.set_subtitle(self._subtitle(enabled, status))
        elif enabled or status.state == FeatureStatus.NOT_INSTALLED:
            # A feature turned on by another control: its state as a row.
            subtitle = self._subtitle(enabled, status)
            if subtitle:
                self._row(subtitle, "", icon="dialog-information-symbolic")
        for widget in self.dependent:
            widget.set_sensitive(enabled)
        self._add_status_rows(enabled, status)
        for conflict in self.shell.conflicts(self.feature):
            self._add_conflict_row(conflict)

    def _subtitle(self, enabled, status):
        if status.state == FeatureStatus.NOT_INSTALLED:
            return _("Not installed. Reinstall the deskence package.")
        if not enabled:
            return ""
        return {
            FeatureStatus.NEEDS_LOGIN: _("Starts after you log out and log in again"),
            FeatureStatus.UPDATE_PENDING: _("Updated; the new version starts after you log in again"),
            FeatureStatus.NO_SHELL: _("GNOME Shell is not running; applies in the next GNOME session"),
            FeatureStatus.INACTIVE: _("Not running"),
        }.get(status.state, "")

    def _row(self, title, subtitle, icon="dialog-warning-symbolic"):
        row = Adw.ActionRow(title=title, subtitle=subtitle, subtitle_selectable=True)
        image = Gtk.Image.new_from_icon_name(icon)
        image.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        if icon == "dialog-warning-symbolic":
            image.add_css_class("warning")
        row.add_prefix(image)
        self.group.add(row)
        self._rows.append(row)
        return row

    @staticmethod
    def _button(row, label, callback):
        button = Gtk.Button(label=label, valign=Gtk.Align.CENTER, use_underline=True)
        button.connect("clicked", lambda b: callback())
        row.add_suffix(button)
        return button

    def _add_status_rows(self, enabled, status):
        if status.state == FeatureStatus.ERROR:
            self._row(_("The feature stopped because of an error"), status.error)
        elif status.state == FeatureStatus.OUT_OF_DATE:
            self._row(_("This GNOME version is not supported"),
                      _("The installed version does not support GNOME {}.").format(
                          self.shell.shell_version or "?"))
        elif status.state == FeatureStatus.EXTENSIONS_DISABLED:
            row = self._row(_("GNOME extensions are turned off"),
                            _("Deskence needs them to show its features."))
            self._button(row, _("_Turn On…"), self._turn_on_extensions)
        if status.user_copy:
            row = self._row(_("Another copy is used instead"),
                            _("A copy in your home folder replaces the installed one: {}").format(
                                status.user_copy))
            self._button(row, _("_Show"), lambda: open_uri(
                self.page, Gio.File.new_for_path(status.user_copy).get_uri()))

    def _turn_on_extensions(self):
        confirm(self.page, _("Turn On GNOME Extensions?"),
                _("This also turns on other extensions you enabled in the Extensions application."),
                _("_Turn On"), self.shell.enable_extensions_globally, destructive=False)

    def _add_conflict_row(self, conflict):
        what = {
            "dock": _("a dock"),
            "desktop-icons": _("desktop icons"),
            "tray": _("application icons in the top bar"),
            "app-grid": _("sorting of the applications view"),
            "clipboard": _("a clipboard history"),
            "keep-awake": _("keeping the computer awake"),
        }[self.feature]
        if conflict.certain:
            subtitle = _("Also provides {}. Using both at once causes problems.").format(what)
        else:
            subtitle = _("May also provide {}.").format(what)
        row = self._row(conflict.name, subtitle)

        def disable():
            confirm(self.page, _("Disable “{}”?").format(conflict.name),
                    _("The extension stays installed and its settings are kept. "
                      "You can turn it on again in the Extensions application."),
                    _("_Disable"), lambda: self.shell.disable_other(conflict.uuid))
        self._button(row, _("_Disable…"), disable)


@Gtk.Template(resource_path=UI + "dock-page.ui")
class DockPage(Adw.PreferencesPage):
    __gtype_name__ = "DeskenceDockPage"

    feature_group = Gtk.Template.Child()
    enable_row = Gtk.Template.Child()
    preview_group = Gtk.Template.Child()
    appearance_group = Gtk.Template.Child()
    behavior_group = Gtk.Template.Child()
    app_info_group = Gtk.Template.Child()
    counts_row = Gtk.Template.Child()
    progress_row = Gtk.Template.Child()
    items_group = Gtk.Template.Child()
    preview = Gtk.Template.Child()
    position_row = Gtk.Template.Child()
    length_row = Gtk.Template.Child()
    icon_size_scale = Gtk.Template.Child()
    icon_size_adjustment = Gtk.Template.Child()
    hide_row = Gtk.Template.Child()
    monitor_mode_row = Gtk.Template.Child()
    monitor_row = Gtk.Template.Child()
    click_row = Gtk.Template.Child()
    isolate_row = Gtk.Template.Child()
    previews_row = Gtk.Template.Child()
    peek_row = Gtk.Template.Child()
    trash_row = Gtk.Template.Child()
    mounts_row = Gtk.Template.Child()
    network_row = Gtk.Template.Child()
    apps_button_row = Gtk.Template.Child()
    apps_position_row = Gtk.Template.Child()
    apps_position_model = Gtk.Template.Child()
    background_color_switch = Gtk.Template.Child()
    background_color_row = Gtk.Template.Child()
    background_color_button = Gtk.Template.Child()
    background_transparency_switch = Gtk.Template.Child()
    background_transparency_row = Gtk.Template.Child()
    background_transparency_scale = Gtk.Template.Child()
    background_transparency_adjustment = Gtk.Template.Child()
    apps_icon_row = Gtk.Template.Child()
    custom_icon_row = Gtk.Template.Child()
    custom_icon_image = Gtk.Template.Child()
    custom_icon_button = Gtk.Template.Child()
    magnify_row = Gtk.Template.Child()
    magnify_strength_row = Gtk.Template.Child()
    magnify_strength_scale = Gtk.Template.Child()
    magnify_strength_adjustment = Gtk.Template.Child()
    stacks_group = Gtk.Template.Child()
    show_stacks_row = Gtk.Template.Child()
    add_stack_button = Gtk.Template.Child()
    reset_row = Gtk.Template.Child()

    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.settings = Gio.Settings.new(SCHEMA + ".Dock")
        self.interface = Gio.Settings.new("org.gnome.desktop.interface")
        s = self.settings
        self.controller = FeatureController(
            self, "dock", shell, self.enable_row, self.feature_group,
            [self.preview_group, self.appearance_group, self.behavior_group,
             self.app_info_group, self.items_group,
             self.stacks_group])

        bind_combo(self.position_row, s, "position", ["left", "bottom", "right"])
        bind_combo(self.length_row, s, "length", ["fit", "full"])
        bind_combo(self.hide_row, s, "hide-mode", ["never", "intellihide", "autohide"])
        bind_combo(self.monitor_mode_row, s, "monitor-mode", ["primary", "selected", "all"])
        bind_combo(self.click_row, s, "click-action", ["focus-or-cycle", "minimize-or-cycle"])
        bind_combo(self.apps_position_row, s, "apps-button-position", ["start", "end"])
        bind_combo(self.apps_icon_row, s, "apps-button-icon", ["default", "distribution", "custom"])
        s.bind("icon-size", self.icon_size_adjustment, "value", Gio.SettingsBindFlags.DEFAULT)
        s.bind("magnify", self.magnify_row, "active", Gio.SettingsBindFlags.DEFAULT)
        s.bind("show-app-counts", self.counts_row, "active", Gio.SettingsBindFlags.DEFAULT)
        s.bind("show-app-progress", self.progress_row, "active", Gio.SettingsBindFlags.DEFAULT)
        s.bind("magnify-strength", self.magnify_strength_adjustment, "value",
               Gio.SettingsBindFlags.DEFAULT)
        s.bind("magnify", self.magnify_strength_row, "sensitive", Gio.SettingsBindFlags.GET)
        self.magnify_strength_scale.add_mark(1.1, Gtk.PositionType.BOTTOM, _("Subtle"))
        self.magnify_strength_scale.add_mark(2.0, Gtk.PositionType.BOTTOM, _("Strong"))
        self.magnify_strength_scale.update_property([Gtk.AccessibleProperty.LABEL],
                                                    [_("Magnification Strength")])
        self.interface.connect("changed::enable-animations", lambda *a: self._sync())
        # Background: the switches and the slider are the only sources of
        # truth; the color dialog has no alpha channel.
        s.bind("background-custom-color", self.background_color_switch, "active",
               Gio.SettingsBindFlags.DEFAULT)
        s.bind("background-custom-color", self.background_color_row, "sensitive",
               Gio.SettingsBindFlags.GET)
        s.bind("background-custom-transparency", self.background_transparency_switch, "active",
               Gio.SettingsBindFlags.DEFAULT)
        s.bind("background-custom-transparency", self.background_transparency_row, "sensitive",
               Gio.SettingsBindFlags.GET)
        s.bind("background-transparency", self.background_transparency_adjustment, "value",
               Gio.SettingsBindFlags.DEFAULT)
        bind_scale_marks(self.background_transparency_scale, _("Background Transparency"))
        bind_color(self.background_color_button, s, "background-color")
        for row in (self.apps_position_row, self.apps_icon_row, self.custom_icon_row):
            s.bind("show-apps-button", row, "sensitive", Gio.SettingsBindFlags.GET)
        s.bind("window-previews", self.peek_row, "sensitive", Gio.SettingsBindFlags.GET)
        s.bind("show-folder-stacks", self.show_stacks_row, "active", Gio.SettingsBindFlags.DEFAULT)
        self._stack_rows = []
        self._setup_stacks_menu()
        s.connect("changed::folder-stacks", lambda *a: self._fill_stacks())
        s.connect("changed::show-folder-stacks", lambda *a: self._fill_stacks())
        self._fill_stacks()
        self.custom_icon_button.connect("clicked", lambda b: self._choose_custom_icon())
        for mark in (32, 48, 64):
            self.icon_size_scale.add_mark(mark, Gtk.PositionType.BOTTOM, None)
        self.icon_size_scale.update_property([Gtk.AccessibleProperty.LABEL], [_("Icon Size")])
        for row, key in ((self.isolate_row, "isolate-workspaces"),
                         (self.previews_row, "window-previews"), (self.peek_row, "window-peek"),
                         (self.trash_row, "show-trash"),
                         (self.mounts_row, "show-mounts"),
                         (self.network_row, "show-network-mounts"),
                         (self.apps_button_row, "show-apps-button")):
            s.bind(key, row, "active", Gio.SettingsBindFlags.DEFAULT)

        self._hide_subtitles = [
            _("The dock is always visible and windows do not cover it"),
            _("Hides while a window overlaps it"),
            _("Appears when you move the pointer to the screen edge"),
        ]
        self._click_subtitles = [
            _("A second click switches to the next window of the application"),
            _("Clicking an application with one focused window minimizes it"),
        ]
        for key in ("hide-mode", "monitor-mode", "click-action", "apps-button-icon",
                    "apps-button-custom-icon") + DOCK_PREVIEW_KEYS:
            s.connect(f"changed::{key}", lambda *a: self._sync())

        monitors = Gdk.Display.get_default().get_monitors()
        monitors.connect("items-changed", lambda *a: self._fill_monitors())
        s.connect("changed::selected-monitor", lambda *a: self._fill_monitors())
        self.monitor_row.connect("notify::selected", self._on_monitor_selected)
        self._fill_monitors()

        self.reset_row.connect("activated", lambda r: confirm(
            self, _("Restore Default Dock Settings?"),
            _("Position, size, colors, hiding, monitor, click behavior and shown items return "
              "to their defaults. Pinned applications, folders in the dock, the applications view "
              "and whether the dock is shown do not change."),
            _("_Restore"), self._reset))
        self._sync()

    def _sync(self):
        s = self.settings
        self.preview.update(*dock_preview_settings(s))
        self.hide_row.set_subtitle(self._hide_subtitles[self.hide_row.get_selected()])
        self.click_row.set_subtitle(self._click_subtitles[self.click_row.get_selected()])
        self.monitor_row.set_visible(s.get_string("monitor-mode") == "selected")
        self.magnify_row.set_subtitle(
            "" if self.interface.get_boolean("enable-animations")
            else _("Not shown while animations are turned off in Accessibility settings"))
        self._sync_apps_button()

    # --- Folders in the dock --------------------------------------------

    STANDARD_FOLDERS = (("DOWNLOAD", "folder-download-symbolic"),
                        ("DOCUMENTS", "folder-documents-symbolic"),
                        ("PICTURES", "folder-pictures-symbolic"),
                        ("MUSIC", "folder-music-symbolic"),
                        ("VIDEOS", "folder-videos-symbolic"))

    def _setup_stacks_menu(self):
        group = Gio.SimpleActionGroup()
        add = Gio.SimpleAction.new("add-standard", GLib.VariantType.new("s"))
        add.connect("activate", lambda a, p: self._add_stack(f"xdg:{p.get_string()}"))
        group.add_action(add)
        choose = Gio.SimpleAction.new("choose", None)
        choose.connect("activate", lambda *a: self._choose_stack())
        group.add_action(choose)
        self.insert_action_group("stacks", group)
        self.add_stack_button.update_property([Gtk.AccessibleProperty.LABEL], [_("Add Folder")])

    def _sync_stacks_menu(self):
        menu = Gio.Menu()
        standard = Gio.Menu()
        dirs = presets.user_dirs()
        current = self.settings.get_strv("folder-stacks")
        for name, _icon in self.STANDARD_FOLDERS:
            if name in dirs and f"xdg:{name}" not in current:
                item = Gio.MenuItem.new(GLib.filename_display_basename(dirs[name]), None)
                item.set_action_and_target_value("stacks.add-standard", GLib.Variant("s", name))
                standard.append_item(item)
        menu.append_section(None, standard)
        other = Gio.Menu()
        other.append(_("Other Folder…"), "stacks.choose")
        menu.append_section(None, other)
        self.add_stack_button.set_menu_model(menu)

    def _stack_info(self, entry):
        """(title, subtitle, icon name, exists) of an entry."""
        home = GLib.get_home_dir()
        dirs = presets.user_dirs()
        path = presets.stack_path(entry, home, dirs)
        icon = dict(self.STANDARD_FOLDERS).get(entry[4:], "folder-symbolic") \
            if entry.startswith("xdg:") else "folder-symbolic"
        if path is None:
            return entry, _("Not set up on this computer"), icon, False
        exists = GLib.file_test(path, GLib.FileTest.IS_DIR)
        subtitle = path.replace(home, "~", 1) if path.startswith(home) else path
        if not exists:
            subtitle = _("{} (missing)").format(subtitle)
        return GLib.filename_display_basename(path), subtitle, icon, exists

    def _fill_stacks(self):
        for row in self._stack_rows:
            self.stacks_group.remove(row)
        self._stack_rows = []
        entries = self.settings.get_strv("folder-stacks")
        for index, entry in enumerate(entries):
            title, subtitle, icon, exists = self._stack_info(entry)
            row = Adw.ActionRow(title=GLib.markup_escape_text(title),
                                subtitle=GLib.markup_escape_text(subtitle))
            image = Gtk.Image.new_from_icon_name(icon)
            image.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
            if not exists:
                image.add_css_class("dim-label")
            row.add_prefix(image)
            for icon_name, tooltip, delta, sensitive in (
                    ("go-up-symbolic", _("Move Up"), -1, index > 0),
                    ("go-down-symbolic", _("Move Down"), 1, index < len(entries) - 1)):
                button = Gtk.Button(icon_name=icon_name, valign=Gtk.Align.CENTER,
                                    tooltip_text=tooltip, sensitive=sensitive)
                button.add_css_class("flat")
                button.connect("clicked", lambda b, e=entry, d=delta: self._move_stack(e, d))
                row.add_suffix(button)
            remove = Gtk.Button(icon_name="list-remove-symbolic", valign=Gtk.Align.CENTER,
                                tooltip_text=_("Remove From Dock"))
            remove.add_css_class("flat")
            remove.connect("clicked", lambda b, e=entry: self._remove_stack(e))
            row.add_suffix(remove)
            row.set_sensitive(self.settings.get_boolean("show-folder-stacks"))
            self.stacks_group.add(row)
            self._stack_rows.append(row)
        self._sync_stacks_menu()

    def _add_stack(self, entry):
        entries = self.settings.get_strv("folder-stacks")
        if entry not in entries:
            self.settings.set_strv("folder-stacks", entries + [entry])
        self.settings.set_boolean("show-folder-stacks", True)

    def _move_stack(self, entry, delta):
        entries = self.settings.get_strv("folder-stacks")
        index = entries.index(entry) if entry in entries else -1
        target = index + delta
        if index < 0 or not 0 <= target < len(entries):
            return
        entries.insert(target, entries.pop(index))
        self.settings.set_strv("folder-stacks", entries)

    def _remove_stack(self, entry):
        # Only the dock entry; the folder itself is not touched.
        entries = [e for e in self.settings.get_strv("folder-stacks") if e != entry]
        self.settings.set_strv("folder-stacks", entries)
        sorting = self.settings.get_value("folder-stack-sorting").unpack()
        if entry in sorting:
            del sorting[entry]
            self.settings.set_value("folder-stack-sorting", GLib.Variant("a{ss}", sorting))

    def _choose_stack(self):
        dialog = Gtk.FileDialog(title=_("Add Folder to the Dock"), modal=True)

        def done(d, result):
            try:
                folder = d.select_folder_finish(result)
            except GLib.Error:
                return
            path = folder.get_path() if folder else None
            if not path:
                dialog = Adw.AlertDialog(heading=_("Cannot Add This Folder"),
                                         body=_("Only local folders can be added."))
                dialog.add_response("close", _("_Close"))
                dialog.present(self)
                return
            self._add_stack(presets.stack_entry(path, GLib.get_home_dir(), presets.user_dirs()))
        dialog.select_folder(self.get_root(), None, done)

    def _sync_apps_button(self):
        s = self.settings
        vertical = s.get_string("position") != "bottom"
        # A short dock has a start and an end; a whole-edge dock has the
        # button at one of the screen sides.
        if s.get_string("length") != "full":
            labels = [_("Start of the Dock"), _("End of the Dock")]
        elif vertical:
            labels = [_("At the Top"), _("At the Bottom")]
        else:
            labels = [_("On the Left"), _("On the Right")]
        model = self.apps_position_model
        if [model.get_string(i) for i in range(model.get_n_items())] != labels:
            self.apps_position_row.deskence_updating = True
            model.splice(0, model.get_n_items(), labels)
            self.apps_position_row.set_selected(
                0 if s.get_string("apps-button-position") == "start" else 1)
            self.apps_position_row.deskence_updating = False

        mode = s.get_string("apps-button-icon")
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        if mode == "distribution":
            logo = appsicon.distribution_logo(theme)
            self.apps_icon_row.set_subtitle(
                "" if logo else _("No logo is installed; the default icon is used"))
        else:
            self.apps_icon_row.set_subtitle("")

        path = s.get_string("apps-button-custom-icon")
        self.custom_icon_row.set_visible(mode == "custom")
        if path and GLib.file_test(path, GLib.FileTest.IS_REGULAR):
            self.custom_icon_image.set_from_file(path)
            self.custom_icon_row.set_subtitle("")
        else:
            self.custom_icon_image.set_from_icon_name("view-app-grid-symbolic")
            self.custom_icon_row.set_subtitle(
                _("No image chosen; the default icon is used") if not path
                else _("The image is missing; the default icon is used"))

    def _choose_custom_icon(self):
        images = Gtk.FileFilter(name=_("Images"))
        for mime in ("image/png", "image/svg+xml", "image/jpeg", "image/webp"):
            images.add_mime_type(mime)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(images)
        dialog = Gtk.FileDialog(title=_("Choose an Icon"), modal=True, filters=filters,
                                default_filter=images)

        def done(d, result):
            try:
                file = d.open_finish(result)
            except GLib.Error:
                return  # cancelled
            path = file.get_path() if file else None
            if not path:
                self._icon_error(_("Only local files can be used."))
                return
            try:
                copy = appsicon.import_icon(path)
            except appsicon.InvalidIcon as e:
                self._icon_error(_("The file is not an image in a supported format "
                                   "(PNG, SVG, JPEG or WebP) of at most 4 MB.") +
                                 ("" if str(e) in ("format", "too-large") else f"\n\n{e}"))
                return
            except OSError as e:
                self._icon_error(e.strerror or str(e))
                return
            self.settings.set_string("apps-button-custom-icon", copy)
            self.settings.set_string("apps-button-icon", "custom")
        dialog.open(self.get_root(), None, done)

    def _icon_error(self, message):
        dialog = Adw.AlertDialog(heading=_("Cannot Use This Image"), body=message)
        dialog.add_response("close", _("_Close"))
        dialog.present(self)

    def _reset(self):
        restore_defaults(self.shell, "dock")
        appsicon.remove_icons()

    def _fill_monitors(self):
        self._filling = True
        monitors = Gdk.Display.get_default().get_monitors()
        self._connectors = []
        labels = []
        for i in range(monitors.get_n_items()):
            monitor = monitors.get_item(i)
            connector = monitor.get_connector() or ""
            description = monitor.get_description() or monitor.get_model() or connector
            self._connectors.append(connector)
            labels.append(f"{description} ({connector})" if connector else description)
        selected = self.settings.get_string("selected-monitor")
        if selected and selected not in self._connectors:
            self._connectors.append(selected)
            labels.append(_("{} (disconnected)").format(selected))
        self.monitor_row.set_model(Gtk.StringList.new(labels))
        if selected in self._connectors:
            self.monitor_row.set_selected(self._connectors.index(selected))
        self._filling = False

    def _on_monitor_selected(self, row, _pspec):
        if getattr(self, "_filling", False):
            return
        index = row.get_selected()
        if 0 <= index < len(self._connectors):
            connector = self._connectors[index]
            if self.settings.get_string("selected-monitor") != connector:
                self.settings.set_string("selected-monitor", connector)


@Gtk.Template(resource_path=UI + "desktop-icons-page.ui")
class DesktopIconsPage(Adw.PreferencesPage):
    __gtype_name__ = "DeskenceDesktopIconsPage"

    feature_group = Gtk.Template.Child()
    enable_row = Gtk.Template.Child()
    folder_row = Gtk.Template.Child()
    open_folder_button = Gtk.Template.Child()
    preview_group = Gtk.Template.Child()
    layout_group = Gtk.Template.Child()
    items_group = Gtk.Template.Child()
    preview = Gtk.Template.Child()
    size_row = Gtk.Template.Child()
    corner_row = Gtk.Template.Child()
    placement_row = Gtk.Template.Child()
    click_row = Gtk.Template.Child()
    home_row = Gtk.Template.Child()
    trash_row = Gtk.Template.Child()
    mounts_row = Gtk.Template.Child()
    reset_row = Gtk.Template.Child()

    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.settings = Gio.Settings.new(SCHEMA + ".DesktopIcons")
        s = self.settings
        self.controller = FeatureController(
            self, "desktop-icons", shell, self.enable_row, self.feature_group,
            [self.preview_group, self.layout_group, self.items_group])
        bind_combo(self.size_row, s, "icon-size", ["small", "medium", "large", "huge"])
        bind_combo(self.corner_row, s, "start-corner",
                   ["top-left", "top-right", "bottom-left", "bottom-right"])
        bind_combo(self.placement_row, s, "icon-placement", ["free", "grid"])
        bind_combo(self.click_row, s, "click-mode", ["double", "single"])
        for row, key in ((self.home_row, "show-home"), (self.trash_row, "show-trash"),
                         (self.mounts_row, "show-mounts")):
            s.bind(key, row, "active", Gio.SettingsBindFlags.DEFAULT)
        for key in ("icon-size", "start-corner", "icon-placement"):
            s.connect(f"changed::{key}", lambda *a: self._sync())
        # The preview shows the dock too: icons are kept out of its way.
        self.dock_settings = Gio.Settings.new(SCHEMA + ".Dock")
        for key in DOCK_PREVIEW_KEYS:
            self.dock_settings.connect(f"changed::{key}", lambda *a: self._sync_dock())
        shell.connect("changed", lambda *a: self._sync_dock())
        self._sync_dock()

        GLib.reload_user_special_dirs_cache()
        path = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP)
        if path and path != GLib.get_home_dir():
            self.folder_row.set_subtitle(path)
            self.open_folder_button.connect(
                "clicked", lambda b: open_uri(self, Gio.File.new_for_path(path).get_uri()))
        else:
            self.folder_row.set_subtitle(_("No desktop folder is set up"))
            self.open_folder_button.set_visible(False)

        self.reset_row.connect("activated", lambda r: confirm(
            self, _("Restore Default Desktop Icon Settings?"),
            _("Size, placement, click behavior and shown items return to their defaults. "
              "Your files and the positions of icons do not change."),
            _("_Restore"), lambda: restore_defaults(self.shell, "desktop-icons")))
        self._sync()

    def _sync_dock(self):
        if self.shell.is_enabled(FEATURE_UUIDS["dock"]):
            self.preview.set_dock(*dock_preview_settings(self.dock_settings))
        else:
            self.preview.hide_dock()

    def _sync(self):
        self.preview.update(self.settings.get_string("icon-size"),
                            self.settings.get_string("start-corner"))
        self.placement_row.set_subtitle(
            _("Icons stay exactly where you drop them")
            if self.settings.get_string("icon-placement") == "free"
            else _("Dropped icons snap to the grid"))


@Gtk.Template(resource_path=UI + "app-grid-page.ui")
class AppGridPage(Adw.PreferencesPage):
    """The full-screen applications view: order (app-grid extension),
    background and folder tiles (dock extension, keys in the dock schema
    since 0.3.0)."""

    __gtype_name__ = "DeskenceAppGridPage"

    order_group = Gtk.Template.Child()
    sort_row = Gtk.Template.Child()
    app_grid_group = Gtk.Template.Child()
    app_grid_color_switch = Gtk.Template.Child()
    app_grid_color_row = Gtk.Template.Child()
    app_grid_color_button = Gtk.Template.Child()
    app_grid_custom_row = Gtk.Template.Child()
    app_grid_transparency_row = Gtk.Template.Child()
    app_grid_transparency_scale = Gtk.Template.Child()
    app_grid_transparency_adjustment = Gtk.Template.Child()
    folder_group = Gtk.Template.Child()
    folder_color_switch = Gtk.Template.Child()
    folder_color_row = Gtk.Template.Child()
    folder_color_button = Gtk.Template.Child()
    folder_custom_row = Gtk.Template.Child()
    folder_transparency_row = Gtk.Template.Child()
    folder_transparency_scale = Gtk.Template.Child()
    folder_transparency_adjustment = Gtk.Template.Child()
    hover_group = Gtk.Template.Child()
    hover_color_switch = Gtk.Template.Child()
    hover_color_row = Gtk.Template.Child()
    hover_color_button = Gtk.Template.Child()
    hover_custom_row = Gtk.Template.Child()
    hover_transparency_row = Gtk.Template.Child()
    hover_transparency_scale = Gtk.Template.Child()
    hover_transparency_adjustment = Gtk.Template.Child()
    reset_row = Gtk.Template.Child()

    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.grid = AppGrid()
        self.order = Gio.Settings.new(SCHEMA + ".AppGrid")
        self.settings = Gio.Settings.new(SCHEMA + ".Dock")
        s = self.settings
        # Status of the sorting extension (needs a login, error...) under
        # the order; it is turned on and off with the order itself.
        self.controller = FeatureController(self, "app-grid", shell, None, self.order_group, [])
        self._syncing = False
        self.order.connect("changed::sort-mode", lambda *a: self._sync())
        self.sort_row.connect("notify::selected", self._on_sort)

        s.bind("app-grid-custom-color", self.app_grid_color_switch, "active",
               Gio.SettingsBindFlags.DEFAULT)
        s.bind("app-grid-custom-color", self.app_grid_color_row, "sensitive",
               Gio.SettingsBindFlags.GET)
        bind_color(self.app_grid_color_button, s, "app-grid-color")
        s.bind("app-grid-custom-transparency", self.app_grid_custom_row, "active",
               Gio.SettingsBindFlags.DEFAULT)
        s.bind("app-grid-custom-transparency", self.app_grid_transparency_row, "sensitive",
               Gio.SettingsBindFlags.GET)
        s.bind("app-grid-transparency", self.app_grid_transparency_adjustment, "value",
               Gio.SettingsBindFlags.DEFAULT)
        bind_scale_marks(self.app_grid_transparency_scale, _("Background Transparency"))

        s.bind("app-grid-folder-custom-color", self.folder_color_switch, "active",
               Gio.SettingsBindFlags.DEFAULT)
        s.bind("app-grid-folder-custom-color", self.folder_color_row, "visible",
               Gio.SettingsBindFlags.GET)
        bind_color(self.folder_color_button, s, "app-grid-folder-color")
        s.bind("app-grid-folder-custom-transparency", self.folder_custom_row, "active",
               Gio.SettingsBindFlags.DEFAULT)
        s.bind("app-grid-folder-custom-transparency", self.folder_transparency_row, "visible",
               Gio.SettingsBindFlags.GET)
        s.bind("app-grid-folder-transparency", self.folder_transparency_adjustment, "value",
               Gio.SettingsBindFlags.DEFAULT)
        bind_scale_marks(self.folder_transparency_scale, _("Folder Transparency"))

        s.bind("app-grid-hover-custom-color", self.hover_color_switch, "active",
               Gio.SettingsBindFlags.DEFAULT)
        s.bind("app-grid-hover-custom-color", self.hover_color_row, "visible",
               Gio.SettingsBindFlags.GET)
        bind_color(self.hover_color_button, s, "app-grid-hover-color")
        s.bind("app-grid-hover-custom-transparency", self.hover_custom_row, "active",
               Gio.SettingsBindFlags.DEFAULT)
        s.bind("app-grid-hover-custom-transparency", self.hover_transparency_row, "visible",
               Gio.SettingsBindFlags.GET)
        s.bind("app-grid-hover-transparency", self.hover_transparency_adjustment, "value",
               Gio.SettingsBindFlags.DEFAULT)
        bind_scale_marks(self.hover_transparency_scale, _("Highlight Transparency"))
        shell.connect("changed", lambda *a: self._sync_background())
        self.reset_row.connect("activated", lambda r: confirm(
            self, _("Restore Default Applications View Settings?"),
            _("The background, application folders and the hover highlight return to the GNOME "
              "look, and the applications return to your own order."),
            _("_Restore"), self._reset))
        self._sync()
        self._sync_background()

    def _sync(self):
        alphabetical = self.order.get_string("sort-mode") == "alphabetical"
        self._syncing = True
        self.sort_row.set_selected(1 if alphabetical else 0)
        self._syncing = False
        self.sort_row.set_subtitle(
            _("By name, also inside folders. Dragging does not change the order.")
            if alphabetical else
            _("Arrange applications by dragging them. This arrangement returns when "
              "alphabetical order is turned off."))

    def _on_sort(self, row, _pspec):
        if self._syncing:
            return
        mode = "alphabetical" if row.get_selected() == 1 else "custom"
        if mode == self.order.get_string("sort-mode"):
            return
        control.set_sort_mode(self.grid, lambda module, on: self.shell.set_enabled(
            FEATURE_UUIDS[module], on), mode)

    def _sync_background(self):
        dock = self.shell.is_enabled(FEATURE_UUIDS["dock"])
        self.app_grid_group.set_sensitive(dock)
        self.app_grid_group.set_description(
            _("The background behind the applications. Icons, names and the search field do "
              "not change.")
            if dock else
            _("Available while the Deskence dock is turned on."))
        # Drawn by the dock extension, like the background.
        self.folder_group.set_sensitive(dock)
        self.folder_group.set_description(
            _("Change the look of application groups, such as “Utilities”, in the applications "
              "view. Only the tile background changes.")
            if dock else
            _("Available while the Deskence dock is turned on."))
        self.hover_group.set_sensitive(dock)
        self.hover_group.set_description(
            _("Choose the background that appears under the pointer on an application or an "
              "application folder, also inside an open folder.")
            if dock else
            _("Available while the Deskence dock is turned on."))

    def _reset(self):
        restore_defaults(self.shell, "app-grid")


@Gtk.Template(resource_path=UI + "clipboard-page.ui")
class ClipboardPage(Adw.PreferencesPage):
    __gtype_name__ = "DeskenceClipboardPage"

    feature_group = Gtk.Template.Child()
    enable_row = Gtk.Template.Child()
    behavior_group = Gtk.Template.Child()
    storage_group = Gtk.Template.Child()
    paste_row = Gtk.Template.Child()
    plain_row = Gtk.Template.Child()
    primary_row = Gtk.Template.Child()
    max_entries_adjustment = Gtk.Template.Child()
    remember_row = Gtk.Template.Child()
    paused_row = Gtk.Template.Child()
    reset_row = Gtk.Template.Child()

    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.settings = Gio.Settings.new(SCHEMA + ".Clipboard")
        s = self.settings
        self.shortcut_row = ShortcutRow("clipboard-history", _("_Shortcut"),
                                        _("Opens the history"))
        self.feature_group.add(self.shortcut_row)
        self.controller = FeatureController(
            self, "clipboard", shell, self.enable_row, self.feature_group,
            [self.shortcut_row, self.behavior_group, self.storage_group])
        for row, key in ((self.paste_row, "paste-on-select"), (self.plain_row, "paste-plain-text"),
                         (self.primary_row, "include-primary"), (self.paused_row, "paused")):
            s.bind(key, row, "active", Gio.SettingsBindFlags.DEFAULT)
        s.bind("max-entries", self.max_entries_adjustment, "value", Gio.SettingsBindFlags.DEFAULT)
        bind_combo(self.remember_row, s, "remember", ["nothing", "pinned", "all"])
        s.connect("changed::remember", lambda *a: self._sync())
        self.reset_row.connect("activated", lambda r: confirm(
            self, _("Restore Default Clipboard Settings?"),
            _("The shortcut and pasting return to their defaults. The history, how many "
              "items it keeps and whether it is kept after logging out do not change."),
            _("_Restore"), lambda: restore_defaults(self.shell, "clipboard")))
        self._sync()

    def _sync(self):
        folder = os.path.join(GLib.get_user_data_dir(), "deskence", "clipboard")
        self.remember_row.set_subtitle({
            "nothing": _("Only in memory"),
            "pinned": _("Pinned items are saved in {}").format(folder),
            "all": _("The history is saved in {}").format(folder),
        }[self.settings.get_string("remember")])


@Gtk.Template(resource_path=UI + "top-bar-page.ui")
class TopBarPage(Adw.PreferencesPage):
    __gtype_name__ = "DeskenceTopBarPage"

    feature_group = Gtk.Template.Child()
    enable_row = Gtk.Template.Child()
    passive_row = Gtk.Template.Child()
    awake_group = Gtk.Template.Child()
    awake_row = Gtk.Template.Child()
    screen_row = Gtk.Template.Child()
    duration_adjustment = Gtk.Template.Child()
    duration_row = Gtk.Template.Child()
    reset_row = Gtk.Template.Child()

    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.settings = Gio.Settings.new(SCHEMA + ".Tray")
        self.controller = FeatureController(self, "tray", shell, self.enable_row,
                                            self.feature_group, [self.passive_row])
        self.awake = Gio.Settings.new(SCHEMA + ".KeepAwake")
        self.awake_controller = FeatureController(self, "keep-awake", shell, self.awake_row,
                                                  self.awake_group,
                                                  [self.screen_row, self.duration_row])
        self.awake.bind("keep-screen-on", self.screen_row, "active", Gio.SettingsBindFlags.DEFAULT)
        self.awake.bind("custom-duration", self.duration_adjustment, "value",
                        Gio.SettingsBindFlags.DEFAULT)
        self.settings.bind("show-passive", self.passive_row, "active",
                           Gio.SettingsBindFlags.DEFAULT)
        self.reset_row.connect("activated", lambda r: confirm(
            self, _("Restore Default Top Bar Settings?"),
            _("Showing inactive icons and the Keep Awake options return to their defaults. "
              "Which features are shown does not change."),
            _("_Restore"), self._reset))

    def _reset(self):
        restore_defaults(self.shell, "tray", "keep-awake")


@Gtk.Template(resource_path=UI + "windows-page.ui")
class WindowsPage(Adw.PreferencesPage):
    """Title bar buttons, stored in GNOME's own setting."""

    __gtype_name__ = "DeskenceWindowsPage"

    minimize_row = Gtk.Template.Child()
    maximize_row = Gtk.Template.Child()
    side_row = Gtk.Template.Child()
    above_group = Gtk.Template.Child()
    restore_previous_row = Gtk.Template.Child()
    reset_row = Gtk.Template.Child()

    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.wm = Gio.Settings.new("org.gnome.desktop.wm.preferences")
        # GNOME's own keybinding; Deskence only offers to set it.
        self.above_group.add(ShortcutRow("always-on-top", _("_Shortcut"),
                                         _("Switches Always on Top for the focused window")))
        self.state = Gio.Settings.new(SCHEMA + ".Windows")
        self._syncing = False
        self.wm.connect("changed::button-layout", lambda *a: self._sync())
        self.state.connect("changed", lambda *a: self._sync())
        self.minimize_row.connect("notify::active", self._on_button, "minimize")
        self.maximize_row.connect("notify::active", self._on_button, "maximize")
        self.side_row.connect("notify::selected", self._on_side)
        self.restore_previous_row.connect("activated", lambda r: self._restore_previous())
        self.reset_row.connect("activated", lambda r: confirm(
            self, _("Restore Default Title Bar Buttons?"),
            _("The title bar buttons return to the GNOME default of this system."),
            _("_Restore"), self._reset))
        self._sync()

    def _layout(self):
        return self.wm.get_string("button-layout")

    def _write(self, layout):
        if layout == self._layout():
            return
        # Remember the user's own layout once, before our first change.
        if not self.state.get_string("original-button-layout"):
            self.state.set_string("original-button-layout", self._layout())
        self.state.set_string("last-written-button-layout", layout)
        self.wm.set_string("button-layout", layout)

    def _on_button(self, row, _pspec, button):
        if not self._syncing:
            self._write(button_layout.set_button(self._layout(), button, row.get_active()))

    def _on_side(self, row, _pspec):
        if not self._syncing:
            side = ["right", "left"][row.get_selected()]
            self._write(button_layout.set_side(self._layout(), side))

    def _can_restore_previous(self):
        original = self.state.get_string("original-button-layout")
        last = self.state.get_string("last-written-button-layout")
        # Only while the layout is still the one we wrote: later changes made
        # elsewhere are the user's newer choice and are not overwritten.
        return bool(original) and self._layout() == last and original != last

    def _restore_previous(self):
        original = self.state.get_string("original-button-layout")

        def restore():
            self.wm.set_string("button-layout", original)
            self.state.reset("original-button-layout")
            self.state.reset("last-written-button-layout")
        confirm(self, _("Restore Previous Title Bar Buttons?"),
                _("The title bar buttons return to how they were before Deskence "
                  "changed them."),
                _("_Restore"), restore)

    def _reset(self):
        restore_defaults(self.shell, "windows")

    def _sync(self):
        layout = self._layout()
        self._syncing = True
        self.minimize_row.set_active(button_layout.has_button(layout, "minimize"))
        self.maximize_row.set_active(button_layout.has_button(layout, "maximize"))
        self.side_row.set_selected(0 if button_layout.side(layout) == "right" else 1)
        self._syncing = False
        can_restore = self._can_restore_previous()
        self.restore_previous_row.set_visible(bool(self.state.get_string("original-button-layout")))
        self.restore_previous_row.set_sensitive(can_restore)
        self.restore_previous_row.set_tooltip_text(
            None if can_restore else
            _("The buttons were changed elsewhere after Deskence changed them"))
