# SPDX-License-Identifier: GPL-3.0-or-later
"""Taking over an installation of Better GNOME Desktop (0.3.0 and older).

Deskence was called Better GNOME Desktop up to 0.3.0. Its identifiers
changed with the name: the application ID, the GSettings schema and its
dconf path, the extension UUIDs. This module carries the user's state over:

- settings: every value the user set under the former schema is copied to
  the new one, unless the new one already has a value of its own (newer
  Deskence settings win). The former values stay where they were;
- enabled features: each former extension UUID in org.gnome.shell
  enabled-extensions gets the new UUID at its place. The former UUID is
  removed only when the former extension is not running in this session,
  so updating during a session never stops the running dock before the
  next login, and after that login there is never a second set;
- the application in the user's favorites (pinned in the dock), in the
  application grid layout and in application folders: the former desktop
  ID is replaced by the new one at the same place.

Data folders are handled where they are used: icon positions in
desktop-icons/deskence_desktop/positions.py, the applications button image
in migrations.py (version 4). Nothing is deleted.

Every step only changes something that still has the former form, so
running it again does nothing; an interrupted run is completed by the next
one. It runs at every login (deskence --migrate, an autostart entry, before
GNOME Shell enables the new extensions it lists) and when the application
starts. The former schema is read through a copy compiled for this purpose
only (legacy-schemas/ in the package data folder), never installed among
the system schemas.
"""

import os
import sys

from gi.repository import Gio, GLib

from . import migrations

LEGACY_SCHEMA = "io.github.bettergnome.Desktop"
LEGACY_APP_ID = "io.github.bettergnome.Desktop"
APP_ID = "io.github.deskence.Deskence"
SCHEMA = "io.github.deskence.Deskence"
LEGACY_UUIDS = {
    "dock@bettergnome.github.io": "dock@deskence.github.io",
    "desktop-icons@bettergnome.github.io": "desktop-icons@deskence.github.io",
    "tray@bettergnome.github.io": "tray@deskence.github.io",
}
MIGRATED_KEY = "legacy-settings-migrated"

SHELL_SCHEMA = "org.gnome.shell"
FOLDERS_SCHEMA = "org.gnome.desktop.app-folders"
FOLDER_SCHEMA = "org.gnome.desktop.app-folders.folder"
FOLDERS_PATH = "/org/gnome/desktop/app-folders/folders/"
# Extension states from GNOME Shell (misc/extensionUtils.js).
STATE_ACTIVE = 1
STATE_ACTIVATING = 8


# --- Settings ---------------------------------------------------------------

def _copy_keys(legacy, current):
    """Copies user values of legacy (Gio.Settings) and its children to
    current, except where current has a user value of its own."""
    legacy_schema = legacy.props.settings_schema
    current_schema = current.props.settings_schema
    for key in legacy_schema.list_keys():
        if key == MIGRATED_KEY or not current_schema.has_key(key):
            continue
        value = legacy.get_user_value(key)
        if value is None or current.get_user_value(key) is not None:
            continue
        if not current_schema.get_key(key).range_check(value):
            continue
        current.set_value(key, value)
    for child in legacy_schema.list_children():
        if child in current_schema.list_children():
            _copy_keys(legacy.get_child(child), current.get_child(child))


def _differs(legacy, current):
    """Keys whose former user value did not arrive (for verification)."""
    legacy_schema = legacy.props.settings_schema
    current_schema = current.props.settings_schema
    result = []
    for key in legacy_schema.list_keys():
        if key == MIGRATED_KEY or not current_schema.has_key(key):
            continue
        value = legacy.get_user_value(key)
        if value is None or not current_schema.get_key(key).range_check(value):
            continue
        if current.get_user_value(key) is None:
            result.append(key)
    for child in legacy_schema.list_children():
        if child in current_schema.list_children():
            result += [f"{child}/{k}" for k in _differs(legacy.get_child(child),
                                                        current.get_child(child))]
    return result


def copy_settings(legacy, current):
    """Takes over the former settings once. legacy, current: Gio.Settings
    of the former and the new root schema. Returns True when values were
    copied in this call."""
    if current.get_boolean(MIGRATED_KEY):
        return False
    _copy_keys(legacy, current)
    Gio.Settings.sync()
    missing = _differs(legacy, current)
    if missing:
        # Not marked: the next run tries again.
        print(f"deskence: settings not taken over: {', '.join(missing)}", file=sys.stderr)
        return False
    current.set_boolean(MIGRATED_KEY, True)
    Gio.Settings.sync()
    return True


def legacy_settings(schema_dir, backend=None):
    """Gio.Settings of the former root schema, or None when the copy of the
    former schema is not available."""
    if not schema_dir or not os.path.isfile(os.path.join(schema_dir, "gschemas.compiled")):
        return None
    try:
        source = Gio.SettingsSchemaSource.new_from_directory(schema_dir, None, False)
    except GLib.Error as e:
        print(f"deskence: cannot read the former settings schema: {e.message}", file=sys.stderr)
        return None
    schema = source.lookup(LEGACY_SCHEMA, False)
    if schema is None:
        return None
    return Gio.Settings.new_full(schema, backend, None)


# --- Extensions -------------------------------------------------------------

def migrate_enabled_extensions(enabled, removable):
    """New enabled-extensions list: each former UUID is replaced by the new
    one at its place, and stays after it only while removable(uuid) is
    False. Other entries keep their order."""
    result = []
    for uuid in enabled:
        new = LEGACY_UUIDS.get(uuid)
        if new is None:
            if uuid not in result:
                result.append(uuid)
            continue
        if new not in result:
            result.append(new)
        if not removable(uuid) and uuid not in result:
            result.append(uuid)
    return result


def shell_extension_states(timeout_ms=3000):
    """{uuid: state} from the running GNOME Shell, or None without one."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync("org.gnome.Shell", "/org/gnome/Shell",
                              "org.gnome.Shell.Extensions", "ListExtensions", None,
                              GLib.VariantType.new("(a{sa{sv}})"),
                              Gio.DBusCallFlags.NO_AUTO_START, timeout_ms, None)
    except GLib.Error:
        return None
    (extensions,) = reply.unpack()
    return {uuid: int(info.get("state", 0)) for uuid, info in extensions.items()}


def legacy_removable(states):
    """removable() for migrate_enabled_extensions(): a former extension
    may go unless it runs in this session while GNOME Shell does not know
    the new one yet (updated during the session)."""
    def removable(uuid):
        if states is None:
            return True
        running = states.get(uuid) in (STATE_ACTIVE, STATE_ACTIVATING)
        return not running or LEGACY_UUIDS[uuid] in states
    return removable


def migrate_shell_extensions(shell, states):
    """shell: Gio.Settings of org.gnome.shell. Returns True when changed."""
    enabled = shell.get_strv("enabled-extensions")
    if not any(uuid in LEGACY_UUIDS for uuid in enabled):
        return False
    result = migrate_enabled_extensions(enabled, legacy_removable(states))
    if result == enabled:
        return False
    added = [u for u in result if u not in enabled]
    disabled = shell.get_strv("disabled-extensions")
    if any(u in disabled for u in added):
        shell.set_strv("disabled-extensions", [u for u in disabled if u not in added])
    shell.set_strv("enabled-extensions", result)
    return True


# --- Application ID ---------------------------------------------------------

LEGACY_DESKTOP_ID = LEGACY_APP_ID + ".desktop"
DESKTOP_ID = APP_ID + ".desktop"


def replace_desktop_id(ids):
    """A list of desktop IDs with the former ID replaced in place (once)."""
    result = []
    for app_id in ids:
        app_id = DESKTOP_ID if app_id == LEGACY_DESKTOP_ID else app_id
        if app_id not in result:
            result.append(app_id)
    return result


def replace_in_layout(layout):
    """org.gnome.shell app-picker-layout (GLib.Variant "aa{sv}") with the
    former ID replaced at its place, or None when it does not occur."""
    changed = False
    pages = []
    for i in range(layout.n_children()):
        page = layout.get_child_value(i)
        entries = {}
        for j in range(page.n_children()):
            entry = page.get_child_value(j)
            key = entry.get_child_value(0).get_string()
            if key == LEGACY_DESKTOP_ID:
                key = DESKTOP_ID
                changed = True
            entries.setdefault(key, entry.get_child_value(1).get_variant())
        pages.append(entries)
    return GLib.Variant("aa{sv}", pages) if changed else None


def migrate_app_id(shell, folders=None, folder_settings=None):
    """The former application in favorites, the grid layout and folders."""
    changed = False
    favorites = shell.get_strv("favorite-apps")
    if LEGACY_DESKTOP_ID in favorites:
        shell.set_strv("favorite-apps", replace_desktop_id(favorites))
        changed = True
    if shell.props.settings_schema.has_key("app-picker-layout"):
        layout = replace_in_layout(shell.get_value("app-picker-layout"))
        if layout is not None:
            shell.set_value("app-picker-layout", layout)
            changed = True
    if folders is not None and folder_settings is not None:
        for folder in folders.get_strv("folder-children"):
            settings = folder_settings(folder)
            apps = settings.get_strv("apps")
            if LEGACY_DESKTOP_ID in apps:
                settings.set_strv("apps", replace_desktop_id(apps))
                changed = True
    return changed


# --- Running it -------------------------------------------------------------

def _lookup(schema_id):
    source = Gio.SettingsSchemaSource.get_default()
    return source.lookup(schema_id, True) if source else None


def run(legacy_schema_dir):
    """All steps, for the current user. Safe to run any number of times."""
    if _lookup(SCHEMA) is None:
        print(f"deskence: settings schema {SCHEMA} is not installed", file=sys.stderr)
        return False
    root = Gio.Settings.new(SCHEMA)
    legacy = legacy_settings(legacy_schema_dir)
    if legacy is not None:
        copy_settings(legacy, root)
    # Settings first, so the dock starts with them once it is enabled.
    migrations.migrate(root)
    if _lookup(SHELL_SCHEMA) is not None:
        shell = Gio.Settings.new(SHELL_SCHEMA)
        enabled = shell.get_strv("enabled-extensions")
        if any(uuid in LEGACY_UUIDS for uuid in enabled):
            migrate_shell_extensions(shell, shell_extension_states())
        folders = folder_settings = None
        if _lookup(FOLDERS_SCHEMA) is not None and _lookup(FOLDER_SCHEMA) is not None:
            folders = Gio.Settings.new(FOLDERS_SCHEMA)

            def folder_settings(folder):
                return Gio.Settings.new_with_path(FOLDER_SCHEMA, f"{FOLDERS_PATH}{folder}/")
        migrate_app_id(shell, folders, folder_settings)
    Gio.Settings.sync()
    return True
