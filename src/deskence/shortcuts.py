# SPDX-License-Identifier: GPL-3.0-or-later
"""Rows for the keyboard shortcuts of Deskence (keybindings.py) and the
dialog that records a new one.

A recorded shortcut is checked before it is stored: GNOME's rules for what
can be a shortcut, and clashes with other Deskence shortcuts and with
GNOME's own (keybindings.check). A clash is shown and nothing is stored;
the other shortcut is never changed."""

from gettext import gettext as _

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import keybindings, presets
from .features import UUIDS

MODIFIER_KEYS = {Gdk.KEY_Shift_L, Gdk.KEY_Shift_R, Gdk.KEY_Control_L, Gdk.KEY_Control_R,
                 Gdk.KEY_Alt_L, Gdk.KEY_Alt_R, Gdk.KEY_Super_L, Gdk.KEY_Super_R,
                 Gdk.KEY_Meta_L, Gdk.KEY_Meta_R, Gdk.KEY_ISO_Level3_Shift}


def accelerator(keyval, state):
    """The GSettings form of a key press, or None for a modifier alone (the
    combination is not finished yet)."""
    mods = state & Gtk.accelerator_get_default_mod_mask()
    keyval = Gdk.keyval_to_lower(keyval)
    if keyval in MODIFIER_KEYS:
        return None
    return Gtk.accelerator_name(keyval, mods)


def _settings(schema_id):
    source = Gio.SettingsSchemaSource.get_default()
    return Gio.Settings.new(schema_id) if source and source.lookup(schema_id, True) else None


def current_shortcuts():
    def read(schema, key):
        settings = _settings(schema)
        return settings.get_strv(key) if settings else None
    return keybindings.current_shortcuts(read)


class ShortcutRow(Adw.ActionRow):
    """A shortcut of one action: shows it, and changes, disables or restores
    it. A fixed shortcut is only shown."""

    def __init__(self, action_id, title=None, subtitle=None):
        self.action = keybindings.action(action_id)
        super().__init__(title=title or self.action.title(), use_underline=True,
                         subtitle=subtitle if subtitle is not None else
                         self.action.description())
        # Found by the settings search although it is made here, not in a page template.
        self.searchable = True
        self.label = Gtk.ShortcutLabel(disabled_text=_("Disabled"), valign=Gtk.Align.CENTER)
        self.add_suffix(self.label)
        self.settings = None if self.action.fixed else _settings(self.action.schema)
        self.key = self.action.key
        if self.settings is None:
            self.label.set_accelerator(self.action.fixed or "")
            self.set_activatable(False)
            return
        self.set_activatable(True)
        self.reset_button = Gtk.Button(icon_name="edit-undo-symbolic", valign=Gtk.Align.CENTER,
                                       tooltip_text=_("Restore Default Shortcut"))
        self.reset_button.add_css_class("flat")
        self.reset_button.connect("clicked", lambda b: self.settings.reset(self.key))
        self.add_suffix(self.reset_button)
        self.connect("activated", lambda r: self._ask())
        self.settings.connect(f"changed::{self.key}", lambda *a: self._sync())
        self._sync()

    def _sync(self):
        values = self.settings.get_strv(self.key)
        self.label.set_accelerator(values[0] if values else "")
        self.reset_button.set_visible(self.settings.get_user_value(self.key) is not None and
                                      self.settings.get_value(self.key) !=
                                      self.settings.get_default_value(self.key))

    def _ask(self):
        status = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        status.add_css_class("error")
        status.set_visible(False)
        dialog = Adw.AlertDialog(
            heading=_("Set Shortcut"),
            body=_("Press the new shortcut for “{}”. Escape cancels.").format(
                self.action.title()),
            extra_child=status)
        dialog.add_response("cancel", _("_Cancel"))
        dialog.add_response("disable", _("_Disable"))
        dialog.add_response("default", _("Restore _Default"))
        dialog.set_close_response("cancel")
        gnome = keybindings.gnome_bindings()
        default = self.settings.get_default_value(self.key).unpack()

        def store(values):
            self.settings.set_strv(self.key, values)
            Gio.Settings.sync()

        def response(_d, result):
            if result == "disable":
                store([])
            elif result == "default":
                reason = keybindings.check(self.action.id, default[0], current_shortcuts(),
                                           gnome) if default else None
                if reason:
                    self._error(_("The default shortcut is taken: {}").format(reason))
                else:
                    self.settings.reset(self.key)
        dialog.connect("response", response)

        controller = Gtk.EventControllerKey()

        def pressed(_c, keyval, _keycode, state):
            mods = state & Gtk.accelerator_get_default_mod_mask()
            if keyval == Gdk.KEY_Escape and not mods:
                return False            # the dialog closes: cancelled
            name = accelerator(keyval, state)
            if name is None:
                return True
            reason = keybindings.check(self.action.id, name, current_shortcuts(), gnome)
            if reason:
                status.set_label(f"{Gtk.accelerator_get_label(Gdk.keyval_to_lower(keyval), mods)}"
                                 f": {reason}")
                status.set_visible(True)
                if hasattr(status, "announce"):  # GTK 4.14+
                    status.announce(status.get_label(),
                                    Gtk.AccessibleAnnouncementPriority.MEDIUM)
                return True
            store([name])
            dialog.force_close()
            return True
        controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        controller.connect("key-pressed", pressed)
        dialog.add_controller(controller)
        dialog.present(self)
        # Like GNOME Settings: while recording, the keys of GNOME's own
        # shortcuts reach the dialog instead of starting their action (the
        # compositor may ask the user to allow it).
        surface = self.get_root().get_surface() if self.get_root() else None
        if surface is not None and hasattr(surface, "inhibit_system_shortcuts"):
            surface.inhibit_system_shortcuts(None)
            dialog.connect("closed", lambda d: surface.restore_system_shortcuts())

    def _error(self, message):
        dialog = Adw.AlertDialog(heading=_("Cannot Use This Shortcut"), body=message)
        dialog.add_response("close", _("_Close"))

        def show():
            dialog.present(self)
            return GLib.SOURCE_REMOVE
        # After the shortcut dialog has gone.
        GLib.idle_add(show)


class ShortcutsDialog(Adw.PreferencesDialog):
    """All shortcuts of Deskence in one place."""

    def __init__(self, shell):
        super().__init__(title=_("Keyboard Shortcuts"))
        page = Adw.PreferencesPage()
        globals_group = Adw.PreferencesGroup(
            title=_("Everywhere"),
            description=_("Clashes with other Deskence shortcuts and with GNOME's own are "
                          "refused. Shortcuts of other applications and extensions cannot be "
                          "checked."))
        local_group = Adw.PreferencesGroup(title=_("In the Settings Window"))
        for a in keybindings.actions():
            row = ShortcutRow(a.id)
            if a.feature and not shell.is_enabled(UUIDS[a.feature]):
                row.set_subtitle(_("Works while “{}” is turned on").format(
                    presets.module_title(a.feature)))
            (globals_group if a.scope == keybindings.GLOBAL else local_group).add(row)
        page.add(globals_group)
        page.add(local_group)
        self.add(page)

