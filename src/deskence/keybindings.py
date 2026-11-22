# SPDX-License-Identifier: GPL-3.0-or-later
"""Keyboard shortcuts of Deskence: the actions that have one, where each is
stored, how a shortcut is written, and what it would clash with.

Shortcuts are stored the way GNOME stores keybindings: GSettings keys of
type "as" with accelerators such as "<Shift><Super>v". Global shortcuts are
grabbed by GNOME Shell (mutter): the clipboard history by our clipboard
extension (Main.wm.addKeybinding, which follows changes of the key and is
removed when the extension is disabled), Always on Top by mutter itself
from GNOME's own key. Local shortcuts only work in the settings window and
cannot clash with global ones in a way that matters, so they are only
compared with each other.

Clashes are found among the actions of Deskence and in GNOME's keybinding
settings that can be read reliably (window manager, GNOME Shell, mutter,
settings daemon media keys and custom shortcuts). Shortcuts of other
applications, of other desktop extensions and of the keyboard layout are
not stored anywhere readable and are not detected. Nothing here ever
changes a shortcut that belongs to GNOME or another program.

Without GTK, so presets and the command line can check shortcuts too.
"""

import re
from dataclasses import dataclass
from gettext import gettext as _

from gi.repository import Gio

GLOBAL = "global"
WINDOW = "window"        # only in the Deskence settings window

CLIPBOARD = "io.github.deskence.Deskence.Clipboard"
WM_KEYBINDINGS = "org.gnome.desktop.wm.keybindings"


@dataclass(frozen=True)
class Action:
    id: str
    title: object            # callable returning the translated title
    description: object     # callable returning the translated description
    scope: str
    schema: str = None       # where a changeable shortcut is stored
    key: str = None
    feature: str = None     # the Deskence feature that registers it, if any
    fixed: str = None       # a shortcut that cannot be changed


def actions():
    """Every action of Deskence with a keyboard shortcut."""
    return [
        Action("clipboard-history", lambda: _("Show Clipboard History"),
               lambda: _("Opens the history of copied texts and images"),
               GLOBAL, CLIPBOARD, "shortcut", feature="clipboard"),
        Action("always-on-top", lambda: _("Always on Top"),
               lambda: _("Switches Always on Top for the focused window (a GNOME shortcut)"),
               GLOBAL, WM_KEYBINDINGS, "toggle-above"),
        Action("search-settings", lambda: _("Search Settings"),
               lambda: _("In the Deskence settings window"),
               WINDOW, fixed="<Control>f"),
    ]


def action(action_id):
    return next(a for a in actions() if a.id == action_id)


# --- Writing shortcuts --------------------------------------------------------

MODIFIER_ORDER = ("Shift", "Control", "Alt", "Super", "Hyper", "Meta")
MODIFIER_ALIASES = {
    "shift": "Shift", "control": "Control", "ctrl": "Control", "ctl": "Control",
    "primary": "Control", "alt": "Alt", "mod1": "Alt", "super": "Super", "mod4": "Super",
    "hyper": "Hyper", "meta": "Meta",
}
MODIFIER_KEYS = {"shift_l", "shift_r", "control_l", "control_r", "alt_l", "alt_r", "super_l",
                 "super_r", "meta_l", "meta_r", "hyper_l", "hyper_r", "iso_level3_shift"}
# Keys that make a shortcut on their own.
LONE_KEYS = {f"f{n}" for n in range(1, 25)} | {"print", "pause", "scroll_lock"}
_ACCEL = re.compile(r"((?:<[^<>]+>)*)([^<>]+)$")


def parse(accel):
    """(modifiers, key) of an accelerator, both lower case where it does not
    matter, or None when it is not one."""
    if not isinstance(accel, str):
        return None
    match = _ACCEL.match(accel.strip())
    if not match or not match.group(2).strip():
        return None
    mods = set()
    for name in re.findall(r"<([^<>]+)>", match.group(1)):
        canonical = MODIFIER_ALIASES.get(name.strip().lower())
        if canonical is None:
            return None
        mods.add(canonical)
    return frozenset(mods), match.group(2).strip().lower()


def normalize(accel):
    """One spelling for equal shortcuts ("<Primary><shift>V" and
    "<Shift><Control>v" alike), or None."""
    parsed = parse(accel)
    if parsed is None:
        return None
    mods, key = parsed
    return "".join(f"<{m}>" for m in MODIFIER_ORDER if m in mods) + key


def problem(accel, scope=GLOBAL):
    """Why a shortcut cannot be used, or None. As in GNOME, a key needs
    Ctrl, Alt or Super unless it is a function key; Shift alone only
    types capitals. A global shortcut also must not take Ctrl or Alt with
    a single character, which applications use for their own commands and
    menus."""
    parsed = parse(accel)
    if parsed is None:
        return _("This is not a valid shortcut.")
    mods, key = parsed
    if key in MODIFIER_KEYS:
        return _("A modifier key alone cannot be a shortcut.")
    if key not in LONE_KEYS and not mods - {"Shift"}:
        return _("Use Ctrl, Alt or Super together with the key, or a function key.")
    if scope == GLOBAL and len(key) == 1 and mods in ({"Control"}, {"Alt"},
                                                       {"Control", "Shift"}, {"Alt", "Shift"}):
        return _("Applications use this kind of shortcut themselves. Add Super, or "
                 "combine Ctrl and Alt.")
    return None


# --- Clashes ------------------------------------------------------------------

GNOME_SCHEMAS = (
    "org.gnome.desktop.wm.keybindings",
    "org.gnome.shell.keybindings",
    "org.gnome.mutter.keybindings",
    "org.gnome.mutter.wayland.keybindings",
    "org.gnome.settings-daemon.plugins.media-keys",
)
CUSTOM_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"


@dataclass(frozen=True)
class Binding:
    schema: str
    key: str
    accel: str        # normalized
    label: str        # what the shortcut does, for the user


def gnome_bindings(source=None, backend=None):
    """The shortcuts GNOME has set: those that can be read from its
    keybinding settings. Schemas that are not installed are skipped."""
    source = source or Gio.SettingsSchemaSource.get_default()
    result = []

    def settings(schema, path=None):
        if path:
            return Gio.Settings.new_full(schema, backend, path)
        return Gio.Settings.new_full(schema, backend, None)

    for schema_id in GNOME_SCHEMAS:
        schema = source.lookup(schema_id, True) if source else None
        if schema is None:
            continue
        values = settings(schema)
        for key in schema.list_keys():
            info = schema.get_key(key)
            kind = info.get_value_type().dup_string()
            if kind == "as":
                accels = values.get_strv(key)
            elif kind == "s":
                accels = [values.get_string(key)]
            else:
                continue
            label = info.get_summary() or key
            for accel in accels:
                normal = normalize(accel)
                if normal and accel.strip().lower() != "disabled":
                    result.append(Binding(schema_id, key, normal, label))
        if schema_id == "org.gnome.settings-daemon.plugins.media-keys" and \
                "custom-keybindings" in schema.list_keys():
            custom = source.lookup(CUSTOM_SCHEMA, True)
            if custom is None:
                continue
            for path in values.get_strv("custom-keybindings"):
                item = settings(custom, path)
                normal = normalize(item.get_string("binding"))
                if normal:
                    result.append(Binding(CUSTOM_SCHEMA, path, normal,
                                          item.get_string("name") or _("Custom shortcut")))
    return result


@dataclass(frozen=True)
class Clash:
    kind: str         # "deskence" or "gnome"
    label: str


def clashes(action_id, accel, current, gnome):
    """What accel would clash with when given to action_id. current: the
    shortcuts of the other Deskence actions, {action id: [accel, ...]};
    gnome: gnome_bindings(). The key an action itself is stored in is never
    a clash, and local and global shortcuts never clash with each other."""
    normal = normalize(accel)
    if normal is None:
        return []
    me = action(action_id)
    result = []
    for other in actions():
        if other.id == action_id or other.scope != me.scope:
            continue
        values = [other.fixed] if other.fixed else current.get(other.id, [])
        if any(normalize(v) == normal for v in values):
            result.append(Clash("deskence", other.title()))
    if me.scope == GLOBAL:
        ours = {(a.schema, a.key) for a in actions() if a.schema}
        for binding in gnome:
            if binding.accel == normal and (binding.schema, binding.key) not in ours:
                result.append(Clash("gnome", binding.label))
    return result


def check(action_id, accel, current, gnome):
    """None when accel can be used for action_id, otherwise the reason."""
    reason = problem(accel, action(action_id).scope)
    if reason:
        return reason
    found = clashes(action_id, accel, current, gnome)
    if found:
        return _("Already used for: {}").format(", ".join(c.label for c in found))
    return None


def current_shortcuts(read):
    """{action id: [accel, ...]} of the changeable actions. read(schema,
    key) returns the stored list, or None when the key is not available."""
    result = {}
    for a in actions():
        if a.schema:
            values = read(a.schema, a.key)
            if values is not None:
                result[a.id] = list(values)
    return result
