# SPDX-License-Identifier: GPL-3.0-or-later
"""Operations shared by the settings window and the command line.

Nothing here uses GTK, so the command line works without a display: which
settings a reset restores, how a preset is applied (with the settings that
need more than a value), what an import knows about this computer, and
whether written settings really are kept.

Settings are stored through GSettings. Normally that is dconf, which writes
through its service on the session bus: without that bus nothing would be
saved, and an in-memory backend (GSETTINGS_BACKEND=memory) keeps nothing
either. storage() tells both apart from a backend that keeps the values,
and verify() reads written values back after Gio.Settings.sync().
"""

from dataclasses import dataclass, field
from gettext import gettext as _

import gi
from gi.repository import Gio, GLib, GObject

from . import presets
from .features import UUIDS

try:  # GLib 2.86+; Gio.DesktopAppInfo before.
    gi.require_version("GioUnix", "2.0")
    from gi.repository import GioUnix
    DesktopAppInfo = GioUnix.DesktopAppInfo
except (ValueError, ImportError):
    DesktopAppInfo = Gio.DesktopAppInfo

WM_PREFERENCES = presets.WM_PREFERENCES
WINDOWS = presets.SCHEMA + ".Windows"

# --- Where settings go ------------------------------------------------------


@dataclass
class Storage:
    backend: str          # "dconf", "keyfile", "memory" or the GType name
    persistent: bool
    reason: str = ""      # why values would not be kept


def storage():
    name = GObject.type_name(Gio.SettingsBackend.get_default().__gtype__)
    if name == "DConfSettingsBackend":
        try:
            Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error:
            return Storage("dconf", False, _(
                "The session bus is not available, so dconf cannot save settings. "
                "Run the command in a terminal of your GNOME session or after logging in "
                "on a text console as the same user."))
        return Storage("dconf", True)
    if name == "GKeyfileSettingsBackend":
        return Storage("keyfile", True)
    if name == "GMemorySettingsBackend":
        return Storage("memory", False, _(
            "Settings are only kept in memory (GSETTINGS_BACKEND=memory) and would be lost."))
    return Storage(name, True)


def verify(store, values):
    """After writing: the (schema, key) of values ({(schema, key): value})
    that do not read back as written."""
    store.sync()
    return [k for k, v in values.items() if store.get(*k) != v]


# --- Features ---------------------------------------------------------------

def enabled_features(shell):
    """Which features the user wants on (saved state, not the session)."""
    return {module: shell.is_enabled(uuid) for module, uuid in UUIDS.items()}


def set_sort_mode(grid, set_feature, mode):
    grid.set_mode(mode)
    # Alphabetical order is kept up by its extension.
    set_feature("app-grid", mode == "alphabetical")


def preset_setters(grid, set_feature):
    """Keys whose change needs more than the value (presets.apply_plan)."""
    return {(presets.APP_GRID, "sort-mode"): lambda mode: set_sort_mode(grid, set_feature, mode)}


def import_context(features, connectors=()):
    """What an import needs to know about this computer. connectors: the
    monitors, when known (the command line has no display)."""
    return presets.Context(
        home=GLib.get_home_dir(), dirs=presets.user_dirs(), connectors=list(connectors),
        app_exists=lambda app_id: DesktopAppInfo.new(app_id) is not None,
        features=dict(features))


# --- Restoring defaults -----------------------------------------------------

# What "Restore Default Settings" restores, for one page of the settings
# window or one feature on the command line. Keys of the dock schema that
# belong to other pages or are items the user added stay with the dock.
DOCK_KEYS_KEPT = ("app-grid-", "folder-stacks", "folder-stack-sorting")

# Never restored: how the clipboard history is kept. Back at the defaults
# ("nothing", 50 items) the clipboard feature would delete the saved history
# or drop older items, and restoring settings must not destroy data.
KEPT = {(presets.CLIPBOARD, "remember"), (presets.CLIPBOARD, "max-entries")}

RESET_SCOPES = ("dock", "desktop-icons", "tray", "app-grid", "clipboard", "keep-awake",
                "windows")


def _schema_keys(store, schema, keep=lambda key: False):
    if not store.available(schema):
        return []
    return [(schema, key) for key in sorted(store.keys(schema))
            if not keep(key) and (schema, key) not in KEPT]


def reset_keys(store, scope):
    """The (schema, key) a scope restores; scope "all" is every Deskence
    setting except internal state (presets.RESET_EXCLUDED)."""
    if scope == "all":
        keys = []
        for schema in presets.DESKENCE_SCHEMAS:
            keys += [k for k in _schema_keys(store, schema)
                     if k not in presets.RESET_EXCLUDED]
        return keys
    if scope == "dock":
        return _schema_keys(store, presets.DOCK, lambda key: key.startswith(DOCK_KEYS_KEPT))
    if scope == "app-grid":
        return _schema_keys(store, presets.DOCK, lambda key: not key.startswith("app-grid-"))
    if scope == "windows":
        keys = [(WINDOWS, "original-button-layout"), (WINDOWS, "last-written-button-layout")]
        if store.available(WM_PREFERENCES, "button-layout"):
            keys.insert(0, (WM_PREFERENCES, "button-layout"))
        return [k for k in keys if store.available(*k)]
    schema = {
        "desktop-icons": presets.DESKTOP,
        "tray": presets.TRAY,
        "clipboard": presets.CLIPBOARD,
        "keep-awake": presets.KEEP_AWAKE,
    }[scope]
    return _schema_keys(store, schema)


@dataclass
class ResetPlan:
    scope: str
    # (schema, key, current value) of the keys that differ from the default;
    # only those change.
    changes: list = field(default_factory=list)
    # The applications view returns to the custom order ("app-grid" and
    # "all"), and the sorting feature, which only keeps up the alphabetical
    # order, is turned off.
    custom_order: bool = False
    disables_sorting: bool = False

    @property
    def empty(self):
        return not self.changes and not self.custom_order and not self.disables_sorting


def plan_reset(store, scope, features):
    """What restoring the defaults of a scope would change. Nothing is
    written. features: enabled_features()."""
    plan = ResetPlan(scope)
    for schema, key in reset_keys(store, scope):
        settings = store.settings(schema)
        if settings.get_user_value(key) is not None and \
                settings.get_value(key) != settings.get_default_value(key):
            plan.changes.append((schema, key, store.get(schema, key)))
    if scope in ("app-grid", "all"):
        plan.custom_order = store.available(presets.APP_GRID, "sort-mode") and \
            store.get(presets.APP_GRID, "sort-mode") != "custom"
        plan.disables_sorting = features.get("app-grid", False)
    return plan


def reset(store, plan, grid, set_feature):
    """Restores the defaults of a plan. Files are never deleted here: the
    settings window additionally removes the unused copy of a custom
    applications button image."""
    for schema, key, _value in plan.changes:
        store.reset(schema, key)
    if plan.custom_order:
        set_sort_mode(grid, set_feature, "custom")
    elif plan.disables_sorting:
        set_feature("app-grid", False)
    store.sync()
