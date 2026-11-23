# SPDX-License-Identifier: GPL-3.0-or-later
"""Presets: saving, exporting and importing the configuration.

A preset is a readable JSON document:

    {
      "format": "io.github.deskence.Deskence.preset",
      "version": 1,
      "name": "Work",
      "settings-version": 5,
      "modules": {"dock": {"position": "left", ...}, "windows": {...}, ...},
      "features": {"dock": true, "clipboard": false, ...},
      "pinned-apps": ["org.gnome.Nautilus.desktop", ...],        (optional)
      "folder-stacks": {"entries": [...], "sorting": {...}},     (optional)
      "assets": {"apps-button-icon": "assets/apps-button-icon.png"}  (optional)
    }

Only the settings listed in ENTRIES are exported: keys of Deskence and the
GNOME settings Deskence changes (title bar buttons, the "always on top"
shortcut). Never the whole dconf database, and never internal state: the
clipboard history, a running "keep awake" session, window state, the saved
arrangement of the applications view or migration markers.

Values are plain JSON (booleans, numbers, strings, lists of strings, string
maps); enumerations are their names. Folders in the dock are stored by
identity ("xdg:DOWNLOAD", "home:Projects/site"), so a preset works for
another user name or a translated folder name.

A preset with images (the custom applications button icon) is a ZIP archive
(ARCHIVE_SUFFIX) with preset.json at its root and the images under assets/.
Only those two kinds of members are ever read; nothing is extracted by the
name stored in the archive, and nothing in a preset is ever executed. A
preset without images is a plain .json file.

Importing never writes before the user saw a summary: plan_import() checks
the format, version, types and ranges and lists what would change, what is
skipped and why. apply_plan() writes a backup of the current configuration
first and restores it when writing fails; the same backup lets the user
undo an import.
"""

import json
import os
import re
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from gettext import gettext as _

from gi.repository import Gio, GLib

from . import keybindings, languages
from .features import UUIDS as FEATURES

FORMAT_ID = "io.github.deskence.Deskence.preset"
FORMAT_VERSION = 1
ARCHIVE_SUFFIX = ".deskence"
ARCHIVE_PRESET = "preset.json"

MAX_JSON_BYTES = 1024 * 1024
MAX_ASSET_BYTES = 4 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 32
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
ASSET_NAME = re.compile(r"assets/[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
MAX_NAME_LENGTH = 80
MAX_LIST_LENGTH = 500

SCHEMA = "io.github.deskence.Deskence"
DOCK = SCHEMA + ".Dock"
DESKTOP = SCHEMA + ".DesktopIcons"
TRAY = SCHEMA + ".Tray"
APP_GRID = SCHEMA + ".AppGrid"
CLIPBOARD = SCHEMA + ".Clipboard"
KEEP_AWAKE = SCHEMA + ".KeepAwake"
WM_PREFERENCES = "org.gnome.desktop.wm.preferences"
WM_KEYBINDINGS = "org.gnome.desktop.wm.keybindings"
SHELL = "org.gnome.shell"


@dataclass(frozen=True)
class Entry:
    module: str
    name: str      # name in the preset
    schema: str
    key: str


def _entries(module, schema, keys, names=None):
    return [Entry(module, (names or {}).get(k, k), schema, k) for k in keys]


# The exported settings, by module. Anything not listed here is neither
# exported nor imported.
ENTRIES = (
    _entries("general", SCHEMA, ("show-desktop-at-login", "language"))
    + _entries("dock", DOCK, (
        "position", "length", "icon-size", "hide-mode", "monitor-mode", "selected-monitor",
        "show-trash", "show-mounts", "show-network-mounts", "show-apps-button",
        "apps-button-position", "apps-button-icon", "magnify", "magnify-strength",
        "background-custom-color", "background-color", "background-custom-transparency",
        "background-transparency", "click-action", "isolate-workspaces", "window-previews",
        "window-peek", "show-folder-stacks", "folder-stack-view", "show-app-counts",
        "show-app-progress"))
    + _entries("desktop-icons", DESKTOP, (
        "icon-size", "start-corner", "show-home", "show-trash", "show-mounts",
        "icon-placement", "click-mode", "sort-order"))
    + _entries("app-grid", DOCK, (
        "app-grid-custom-color", "app-grid-color", "app-grid-custom-transparency",
        "app-grid-transparency", "app-grid-folder-custom-color", "app-grid-folder-color",
        "app-grid-folder-custom-transparency", "app-grid-folder-transparency",
        "app-grid-hover-custom-color", "app-grid-hover-color",
        "app-grid-hover-custom-transparency", "app-grid-hover-transparency"))
    + _entries("app-grid", APP_GRID, ("sort-mode",))
    + _entries("top-bar", TRAY, ("show-passive",))
    + _entries("keep-awake", KEEP_AWAKE, (
        "keep-screen-on", "last-choice", "custom-duration", "until-time"))
    + _entries("windows", WM_PREFERENCES, ("button-layout",))
    + _entries("windows", WM_KEYBINDINGS, ("toggle-above",),
               {"toggle-above": "always-on-top-shortcut"})
    + _entries("clipboard", CLIPBOARD, (
        "shortcut", "max-entries", "remember", "include-primary", "paste-plain-text",
        "paste-on-select"))
)

PINNED_APPS = Entry("pinned-apps", "favorite-apps", SHELL, "favorite-apps")
STACKS = Entry("folder-stacks", "entries", DOCK, "folder-stacks")
STACK_SORTING = Entry("folder-stacks", "sorting", DOCK, "folder-stack-sorting")
CUSTOM_ICON = Entry("dock", "apps-button-custom-icon", DOCK, "apps-button-custom-icon")
ICON_ASSET = "apps-button-icon"

# Keys "Restore Default Settings" of all of Deskence leaves alone: internal
# state and markers (see control.reset_keys()).
RESET_EXCLUDED = {
    (SCHEMA, "settings-version"), (SCHEMA, "legacy-settings-migrated"),
    (SCHEMA + ".Windows", "original-button-layout"),
    (SCHEMA + ".Windows", "last-written-button-layout"),
    (APP_GRID, "manual-layout"), (APP_GRID, "sort-mode"),
}
DESKENCE_SCHEMAS = (SCHEMA, DOCK, DESKTOP, TRAY, SCHEMA + ".Windows", APP_GRID, CLIPBOARD,
                    KEEP_AWAKE)

MODULE_TITLES = {
    "features": lambda: _("Features"),
    "general": lambda: _("General"),
    "dock": lambda: _("Dock"),
    "desktop-icons": lambda: _("Desktop Icons"),
    "app-grid": lambda: _("Applications View"),
    "top-bar": lambda: _("Top Bar"),
    "keep-awake": lambda: _("Keep Awake"),
    "windows": lambda: _("Windows"),
    "clipboard": lambda: _("Clipboard"),
    "pinned-apps": lambda: _("Pinned Applications"),
    "folder-stacks": lambda: _("Folders in the Dock"),
}

XDG_NAMES = ("DESKTOP", "DOCUMENTS", "DOWNLOAD", "MUSIC", "PICTURES", "PUBLIC_SHARE",
             "TEMPLATES", "VIDEOS")


class PresetError(Exception):
    """The file is not a usable preset; the message is for the user."""


def module_title(module):
    title = MODULE_TITLES.get(module)
    return title() if title else module


# --- Values ---------------------------------------------------------------

def to_variant(type_string, value):
    """A GLib.Variant of the given type from a JSON value; ValueError when
    the value has another type."""
    def strings(v):
        if not isinstance(v, list) or len(v) > MAX_LIST_LENGTH or \
                not all(isinstance(s, str) for s in v):
            raise ValueError("list of strings expected")
        return v

    if type_string == "b":
        if not isinstance(value, bool):
            raise ValueError("boolean expected")
    elif type_string in ("i", "u", "x", "t"):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("whole number expected")
    elif type_string == "d":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("number expected")
        value = float(value)
    elif type_string == "s":
        if not isinstance(value, str):
            raise ValueError("text expected")
    elif type_string == "as":
        value = strings(value)
    elif type_string == "a{ss}":
        if not isinstance(value, dict) or len(value) > MAX_LIST_LENGTH or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            raise ValueError("map of strings expected")
    else:
        raise ValueError(f"unsupported type {type_string}")
    try:
        return GLib.Variant(type_string, value)
    except (OverflowError, TypeError) as e:
        raise ValueError(str(e)) from e


class SettingsStore:
    """Access to the listed settings through Gio.Settings. Schemas that are
    not installed are reported as unavailable instead of failing."""

    def __init__(self, source=None, backend=None):
        self._source = source or Gio.SettingsSchemaSource.get_default()
        self._backend = backend
        self._settings = {}

    @property
    def source(self):
        return self._source

    @property
    def backend(self):
        return self._backend

    def schema(self, schema_id):
        return self._source.lookup(schema_id, True) if self._source else None

    def available(self, schema_id, key=None):
        schema = self.schema(schema_id)
        return schema is not None and (key is None or schema.has_key(key))

    def settings(self, schema_id):
        if schema_id not in self._settings:
            schema = self.schema(schema_id)
            if schema is None:
                return None
            self._settings[schema_id] = Gio.Settings.new_full(schema, self._backend, None)
        return self._settings[schema_id]

    def type_string(self, schema_id, key):
        return self.schema(schema_id).get_key(key).get_value_type().dup_string()

    def get(self, schema_id, key):
        return self.settings(schema_id).get_value(key).unpack()

    def writable(self, schema_id, key):
        return self.settings(schema_id).is_writable(key)

    def check(self, schema_id, key, value):
        """None when value fits the key, otherwise the reason."""
        try:
            variant = to_variant(self.type_string(schema_id, key), value)
        except ValueError as e:
            return str(e)
        if not self.schema(schema_id).get_key(key).range_check(variant):
            return "out of range"
        return None

    def set(self, schema_id, key, value):
        variant = to_variant(self.type_string(schema_id, key), value)
        if not self.settings(schema_id).set_value(key, variant):
            raise OSError(f"{schema_id} {key} is not writable")

    def reset(self, schema_id, key):
        self.settings(schema_id).reset(key)

    def keys(self, schema_id):
        return self.schema(schema_id).list_keys()

    def sync(self):
        Gio.Settings.sync()


# --- Folders --------------------------------------------------------------

def user_dirs():
    """Paths of the standard folders by XDG name (only those set up)."""
    GLib.reload_user_special_dirs_cache()
    home = os.path.realpath(GLib.get_home_dir())
    result = {}
    for name in XDG_NAMES:
        path = GLib.get_user_special_dir(getattr(GLib.UserDirectory, f"DIRECTORY_{name}"))
        if path and os.path.realpath(path) != home:
            result[name] = path
    return result


def stack_entry(path, home, dirs):
    """The portable entry of a folder: a standard folder by its identity,
    a folder in the home folder relative to it, otherwise a file URI."""
    real = os.path.normpath(path)
    for name, directory in dirs.items():
        if os.path.normpath(directory) == real:
            return f"xdg:{name}"
    home = os.path.normpath(home)
    if real == home:
        return "home:"
    if real.startswith(home + os.sep):
        return "home:" + os.path.relpath(real, home)
    return GLib.filename_to_uri(real, None)


def stack_path(entry, home, dirs):
    """The folder of an entry on this computer, or None when the entry is
    malformed or names a standard folder that is not set up."""
    if entry.startswith("xdg:"):
        return dirs.get(entry[4:])
    if entry.startswith("home:"):
        relative = entry[5:]
        if os.path.isabs(relative) or ".." in relative.split("/"):
            return None
        return os.path.join(home, relative) if relative else home
    if entry.startswith("file://"):
        try:
            path, _host = GLib.filename_from_uri(entry)
        except GLib.Error:
            return None
        return path
    return None


def adapt_stack_entry(entry, home, dirs, exists=os.path.isdir):
    """An imported entry for this computer: an absolute folder of another
    user's home that does not exist here is moved to this home when the
    folder exists there ("/home/anna/Projects" -> "home:Projects")."""
    if not entry.startswith("file://"):
        return entry
    path = stack_path(entry, home, dirs)
    if path is None or exists(path):
        return entry
    parts = path.split(os.sep)
    # /home/<user>/rest or /var/home/<user>/rest (Silverblue)
    for start in (2, 3):
        if len(parts) > start + 1 and parts[start - 1] == "home":
            candidate = os.path.join(home, *parts[start + 1:])
            if exists(candidate):
                return stack_entry(candidate, home, dirs)
    return entry


# --- Export ---------------------------------------------------------------

def export_preset(store, name, features, *, pinned=False, stacks=False, assets=False):
    """The current configuration as a preset. features: module name -> bool.
    Returns (preset, files) where files maps an asset path inside the
    preset to the local file to include."""
    modules = {}
    for entry in ENTRIES:
        if store.available(entry.schema, entry.key):
            modules.setdefault(entry.module, {})[entry.name] = store.get(entry.schema, entry.key)
    preset = {
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "name": name,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "settings-version": store.get(SCHEMA, "settings-version") if
        store.available(SCHEMA, "settings-version") else 0,
        "modules": modules,
        "features": dict(features),
    }
    if pinned and store.available(SHELL, "favorite-apps"):
        preset["pinned-apps"] = store.get(SHELL, "favorite-apps")
    if stacks:
        preset["folder-stacks"] = {
            "entries": store.get(STACKS.schema, STACKS.key),
            "sorting": store.get(STACK_SORTING.schema, STACK_SORTING.key),
        }
    files = {}
    if assets:
        path = store.get(CUSTOM_ICON.schema, CUSTOM_ICON.key)
        if path and os.path.isfile(path):
            member = f"assets/{ICON_ASSET}.png"
            preset["assets"] = {ICON_ASSET: member}
            files[member] = path
    return preset, files


def write_preset(path, preset, files=None):
    """Writes a .json preset or, when files are given, an archive. The
    file appears complete or not at all."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, temporary = tempfile.mkstemp(prefix=".deskence-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as f:
            text = json.dumps(preset, ensure_ascii=False, indent=2).encode() + b"\n"
            if files:
                with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr(ARCHIVE_PRESET, text)
                    for member, source in files.items():
                        archive.write(source, member)
            else:
                f.write(text)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


# --- Reading --------------------------------------------------------------

def read_file(path, work_dir):
    """Reads a preset file (.json or archive). Assets of an archive are
    copied into work_dir under names of our own. Returns (preset, assets)
    with assets mapping an asset name to a local file. Raises PresetError."""
    try:
        if zipfile.is_zipfile(path):
            return _read_archive(path, work_dir)
        with open(path, "rb") as f:
            raw = f.read(MAX_JSON_BYTES + 1)
    except OSError as e:
        raise PresetError(e.strerror or str(e)) from e
    if len(raw) > MAX_JSON_BYTES:
        raise PresetError(_("The file is too large to be a preset."))
    return parse(raw), {}


def parse(raw):
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise PresetError(_("The file is not a Deskence preset.")) from e
    if not isinstance(data, dict) or data.get("format") != FORMAT_ID:
        raise PresetError(_("The file is not a Deskence preset."))
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise PresetError(_("The preset has no valid format version."))
    if version > FORMAT_VERSION:
        raise PresetError(_("The preset was made by a newer version of Deskence. "
                            "Update Deskence to use it."))
    return migrate_format(data)


# Upgrades of older preset formats: FORMAT_MIGRATIONS[n] turns version n
# into n + 1. Version 1 is the first one.
FORMAT_MIGRATIONS = {}


def migrate_format(data):
    data = dict(data)
    while data["version"] < FORMAT_VERSION:
        data = FORMAT_MIGRATIONS[data["version"]](data)
    return data


def _read_archive(path, work_dir):
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        raise PresetError(_("The file is not a Deskence preset.")) from e
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ARCHIVE_MEMBERS or \
                sum(i.file_size for i in infos) > MAX_ARCHIVE_BYTES:
            raise PresetError(_("The archive is too large to be a preset."))
        members = {i.filename: i for i in infos}
        info = members.get(ARCHIVE_PRESET)
        if info is None or info.file_size > MAX_JSON_BYTES:
            raise PresetError(_("The archive does not contain a Deskence preset."))
        try:
            data = parse(archive.read(info))
            assets = {}
            references = data.get("assets", {})
            if not isinstance(references, dict):
                references = {}
            for name, member in references.items():
                # Only known assets, only by an exact member name in assets/;
                # the file is written under a name of our own.
                if name != ICON_ASSET or not isinstance(member, str) or \
                        not ASSET_NAME.fullmatch(member) or member not in members or \
                        members[member].file_size > MAX_ASSET_BYTES:
                    continue
                target = os.path.join(work_dir, f"asset-{name}")
                with archive.open(members[member]) as source, open(target, "wb") as out:
                    out.write(source.read(MAX_ASSET_BYTES + 1)[:MAX_ASSET_BYTES])
                assets[name] = target
        except (OSError, zipfile.BadZipFile, RuntimeError) as e:
            raise PresetError(_("The archive is damaged.")) from e
    return data, assets


# --- Import plan ----------------------------------------------------------

@dataclass
class Change:
    module: str
    name: str
    schema: str
    key: str
    old: object
    new: object


@dataclass
class Context:
    """What the import needs to know about this computer."""
    home: str
    dirs: dict
    connectors: list = field(default_factory=list)
    app_exists: object = lambda app_id: True
    features: dict = field(default_factory=dict)  # module -> currently enabled
    # Languages of the application installed here; None: as found now.
    languages: list = None


@dataclass
class Plan:
    name: str
    changes: list = field(default_factory=list)
    features: dict = field(default_factory=dict)      # module -> enable
    icon: str = None                                  # local image to use
    warnings: list = field(default_factory=list)
    skipped: list = field(default_factory=list)

    @property
    def modules(self):
        names = [c.module for c in self.changes] + \
            (["features"] if self.features else []) + \
            (["dock"] if self.icon else [])
        return list(dict.fromkeys(names))

    @property
    def empty(self):
        return not self.changes and not self.features and not self.icon


def plan_import(data, store, context, assets=None):
    """What importing a parsed preset would change. Nothing is written."""
    assets = assets or {}
    name = data.get("name")
    plan = Plan(name=name[:MAX_NAME_LENGTH] if isinstance(name, str) else "")
    by_name = {(e.module, e.name): e for e in ENTRIES}

    modules = data.get("modules", {})
    if not isinstance(modules, dict):
        modules = {}
        plan.skipped.append(_("The settings part of the preset is damaged."))
    for module, values in modules.items():
        if not isinstance(values, dict):
            plan.skipped.append(_("Unknown part “{}” was ignored.").format(module))
            continue
        for key, value in values.items():
            entry = by_name.get((module, key))
            if entry is None:
                plan.skipped.append(_("Unknown setting “{}” in {} was ignored.").format(
                    key, module_title(module)))
                continue
            _plan_value(plan, store, entry, value)

    _check_shortcuts(plan, store)
    _check_language(plan, context)
    _plan_features(plan, data.get("features"), context)
    if "pinned-apps" in data:
        _plan_pinned(plan, store, data["pinned-apps"], context)
    if "folder-stacks" in data:
        _plan_stacks(plan, store, data["folder-stacks"], context)
    _plan_icon(plan, store, data, assets)

    monitor = next((c for c in plan.changes if c.key == "selected-monitor"), None)
    connector = monitor.new if monitor else None
    if connector and context.connectors and connector not in context.connectors:
        plan.warnings.append(_("Monitor {} is not connected. The dock is shown on the "
                               "primary monitor until it is.").format(connector))
    return plan


def _plan_value(plan, store, entry, value):
    label = f"{module_title(entry.module)}: {entry.name}"
    if not store.available(entry.schema, entry.key):
        plan.skipped.append(_("{} is not available on this computer.").format(label))
        return
    reason = store.check(entry.schema, entry.key, value)
    if reason is not None:
        plan.skipped.append(_("{} has an invalid value and was skipped.").format(label))
        return
    if not store.writable(entry.schema, entry.key):
        plan.skipped.append(_("{} is locked by the administrator.").format(label))
        return
    old = store.get(entry.schema, entry.key)
    if old != value:
        plan.changes.append(Change(entry.module, entry.name, entry.schema, entry.key, old, value))


def _check_language(plan, context):
    """A language without a translation installed here is left out; the
    application would show English."""
    change = next((c for c in plan.changes if (c.schema, c.key) == (SCHEMA, "language")), None)
    if change is None or not change.new:
        return
    codes = context.languages if context.languages is not None else languages.available()
    if languages.resolve(change.new, codes) != change.new:
        plan.changes.remove(change)
        plan.skipped.append(_("The language “{}” is not available on this computer and was "
                              "skipped.").format(change.new))


def _check_shortcuts(plan, store):
    """Imported shortcuts that are not allowed or clash with another
    Deskence or GNOME shortcut are left out, never activated silently."""
    owners = {(a.schema, a.key): a for a in keybindings.actions() if a.schema}
    changes = [c for c in plan.changes if (c.schema, c.key) in owners]
    if not changes:
        return
    gnome = keybindings.gnome_bindings(store.source, store.backend)

    def read(schema, key):
        for change in plan.changes:
            if (change.schema, change.key) == (schema, key):
                return change.new
        return store.get(schema, key) if store.available(schema, key) else None

    current = keybindings.current_shortcuts(read)
    for change in changes:
        action = owners[(change.schema, change.key)]
        for accel in change.new:
            reason = keybindings.check(action.id, accel, current, gnome)
            if reason:
                plan.changes.remove(change)
                current[action.id] = store.get(change.schema, change.key)
                plan.warnings.append(_("The shortcut {} for “{}” was not imported: {}").format(
                    accel, action.title(), reason))
                break


def _plan_features(plan, features, context):
    if features is None:
        return
    if not isinstance(features, dict):
        plan.skipped.append(_("The list of features is damaged and was skipped."))
        return
    for module, enabled in features.items():
        if module not in FEATURES or not isinstance(enabled, bool):
            plan.skipped.append(_("Unknown feature “{}” was ignored.").format(module))
            continue
        if context.features.get(module, False) != enabled:
            plan.features[module] = enabled


def _plan_pinned(plan, store, apps, context):
    entry = PINNED_APPS
    if not store.available(entry.schema, entry.key):
        plan.skipped.append(_("Pinned applications are not available on this computer."))
        return
    if store.check(entry.schema, entry.key, apps) is not None or \
            not all(a.endswith(".desktop") for a in apps):
        plan.skipped.append(_("The list of pinned applications is damaged and was skipped."))
        return
    apps = list(dict.fromkeys(apps))
    missing = [a for a in apps if not context.app_exists(a)]
    if missing:
        plan.warnings.append(_("Not installed: {}. They appear in the dock once installed.")
                             .format(", ".join(a[:-len(".desktop")] for a in missing)))
    old = store.get(entry.schema, entry.key)
    if old != apps:
        plan.changes.append(Change(entry.module, entry.name, entry.schema, entry.key, old, apps))


def _plan_stacks(plan, store, stacks, context):
    if not isinstance(stacks, dict) or \
            store.check(STACKS.schema, STACKS.key, stacks.get("entries", [])) is not None:
        plan.skipped.append(_("The list of folders in the dock is damaged and was skipped."))
        return
    entries = []
    renamed = {}
    for entry in stacks.get("entries", []):
        adapted = adapt_stack_entry(entry, context.home, context.dirs)
        path = stack_path(adapted, context.home, context.dirs)
        if path is None and not entry.startswith("xdg:"):
            plan.skipped.append(_("Folder “{}” has an invalid entry and was skipped.")
                                .format(entry))
            continue
        if adapted in entries:
            continue
        if path is None:
            plan.warnings.append(_("The standard folder {} is not set up on this computer; "
                                   "it is shown as unavailable.").format(entry[4:].title()))
        elif not os.path.isdir(path):
            plan.warnings.append(_("Folder {} does not exist; it is shown as unavailable "
                                   "until it does.").format(path))
        entries.append(adapted)
        renamed[entry] = adapted
    sorting = stacks.get("sorting", {})
    if store.check(STACK_SORTING.schema, STACK_SORTING.key, sorting) is not None:
        sorting = {}
    sorting = {renamed[k]: v for k, v in sorting.items()
               if k in renamed and v in ("name", "modified", "type")}
    for entry, value in ((STACKS, entries), (STACK_SORTING, sorting)):
        old = store.get(entry.schema, entry.key)
        if old != value:
            plan.changes.append(Change(entry.module, entry.name, entry.schema, entry.key,
                                       old, value))


def _plan_icon(plan, store, data, assets):
    wants_custom = data.get("modules", {}).get("dock", {}).get("apps-button-icon") == "custom" \
        if isinstance(data.get("modules"), dict) and \
        isinstance(data["modules"].get("dock"), dict) else False
    if ICON_ASSET in assets:
        plan.icon = assets[ICON_ASSET]
    elif wants_custom:
        # A custom image without the image: keep the current image when
        # there is one, otherwise use the default icon.
        current = store.get(CUSTOM_ICON.schema, CUSTOM_ICON.key)
        if not (current and os.path.isfile(current)):
            for change in plan.changes:
                if change.key == "apps-button-icon":
                    change.new = "default"
            plan.warnings.append(_("The preset uses a custom applications button image that "
                                   "is not included; the default icon is used."))


# --- Applying and undoing -------------------------------------------------
#
# Applying a preset first writes an undo record next to the settings
# (backup_path()): for every setting the preset changes, its value before,
# whether that value was set or only the default, and the value the preset
# set; the same for features it turns on or off. Undoing restores exactly
# those, and only where the setting still has the value the preset gave it:
# a setting changed since then is a conflict, left alone unless the user
# chooses to undo it too. Keys that make one option (a custom color and the
# color, folders in the dock and their order...) are undone together or
# not at all. Applying another preset replaces the record; there is one
# level of undo. Files are never deleted (an imported image stays), and
# nothing else is restored: no other settings, no clipboard history.
#
# The record is a file, so the settings window and the command line
# (deskence preset undo) share it; it stays until it is used or replaced.

UNDO_FORMAT = "io.github.deskence.Deskence.undo"
UNDO_VERSION = 1


def option_group(schema, key):
    """Keys undone together: the ones that make one option."""
    if schema == DOCK:
        match = re.fullmatch(r"(.+?)-(?:custom-)?(color|transparency)", key)
        if match:
            return f"{schema} {match.group(1)}-{match.group(2)}"
        if key in ("apps-button-icon", "apps-button-custom-icon"):
            return f"{schema} apps-button-icon"
        if key in ("folder-stacks", "folder-stack-sorting"):
            return f"{schema} folder-stacks"
    return f"{schema} {key}"


class ApplyError(Exception):
    """Applying stopped half way. restored: settings put back, kept: ones
    that could not be put back safely (changed meanwhile or failing)."""

    def __init__(self, error, restored, kept):
        super().__init__(str(error))
        self.error = error
        self.restored = restored
        self.kept = kept


def _undo_entry(store, schema, key, new):
    settings = store.settings(schema)
    return {"schema": schema, "key": key, "group": option_group(schema, key),
            "before": store.get(schema, key),
            "before-set": settings.get_user_value(key) is not None,
            "after": new, "applied": False}


def _restore_entry(store, entry, setters):
    setter = setters.get((entry["schema"], entry["key"]))
    if setter:
        setter(entry["before"])
    elif entry["before-set"]:
        store.set(entry["schema"], entry["key"], entry["before"])
    else:
        store.reset(entry["schema"], entry["key"])


def _write_record(path, record):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_preset(path, record)


def apply_plan(plan, store, *, features, set_feature, import_icon, backup_path, setters=None):
    """Writes a plan and returns its undo record (also written to
    backup_path, before anything changes). import_icon(path) copies an
    image and returns the path to store; setters maps (schema, key) to a
    function writing that key instead of the store (keys whose change needs
    more than the value). When writing fails half way, what was applied is
    put back where that is safe and ApplyError says what stayed."""
    setters = setters or {}
    planned = [(c.schema, c.key, c.new) for c in plan.changes]
    if plan.icon:
        # The image before the setting that selects it.
        planned.insert(0, (CUSTOM_ICON.schema, CUSTOM_ICON.key, import_icon(plan.icon)))
    record = {
        "format": UNDO_FORMAT, "version": UNDO_VERSION, "name": plan.name,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "changes": [_undo_entry(store, schema, key, new) for schema, key, new in planned],
        "features": [{"module": module, "before": features.get(module, False), "after": on,
                      "applied": False} for module, on in plan.features.items()],
    }
    _write_record(backup_path, record)
    try:
        for entry in record["changes"]:
            setter = setters.get((entry["schema"], entry["key"]))
            entry["applied"] = True        # also when it fails half way
            if setter:
                setter(entry["after"])
            else:
                store.set(entry["schema"], entry["key"], entry["after"])
        for feature in record["features"]:
            feature["applied"] = True
            set_feature(feature["module"], feature["after"])
        store.sync()
    except Exception as error:
        restored, kept = _roll_back(record, store, set_feature, setters)
        try:
            os.unlink(backup_path)
        except OSError:
            pass
        raise ApplyError(error, restored, kept) from error
    # What the preset really set (a setter may store a normalized value).
    for entry in record["changes"]:
        entry["after"] = store.get(entry["schema"], entry["key"])
    _write_record(backup_path, record)
    return record


def _roll_back(record, store, set_feature, setters):
    restored, kept = [], []
    for feature in reversed(record["features"]):
        if feature["applied"]:
            try:
                set_feature(feature["module"], feature["before"])
                restored.append(feature["module"])
            except Exception:  # noqa: BLE001 - report it, go on with the rest
                kept.append(feature["module"])
    for entry in reversed(record["changes"]):
        if not entry["applied"]:
            continue
        label = f"{entry['schema']} {entry['key']}"
        try:
            current = store.get(entry["schema"], entry["key"])
            if current in (entry["after"], entry["before"]):
                if current != entry["before"]:
                    _restore_entry(store, entry, setters)
                restored.append(label)
            else:
                kept.append(label)
        except Exception:  # noqa: BLE001
            kept.append(label)
    try:
        store.sync()
    except Exception:  # noqa: BLE001
        pass
    return restored, kept


@dataclass
class UndoGroup:
    group: str
    entries: list
    conflict: bool        # changed after the preset was applied

    @property
    def label(self):
        schema, _sep, name = self.group.partition(" ")
        module = next((e.module for e in ENTRIES if e.schema == schema and
                       option_group(e.schema, e.key) == self.group), None)
        return f"{module_title(module)}: {name}" if module else name


@dataclass
class UndoPlan:
    name: str
    groups: list = field(default_factory=list)
    features: list = field(default_factory=list)   # (module, before, conflict)
    legacy: dict = None   # a full snapshot of an older release

    @property
    def conflicts(self):
        return [g.label for g in self.groups if g.conflict] + \
            [module_title(m) for m, _b, conflict in self.features if conflict]

    @property
    def empty(self):
        return not self.groups and not self.features and self.legacy is None


def load_undo(backup_path):
    """The undo record, or None when there is none or it cannot be read."""
    try:
        with open(backup_path, "rb") as f:
            return json.loads(f.read(MAX_JSON_BYTES).decode("utf-8"))
    except (OSError, ValueError):
        return None


def plan_undo(record, store, features):
    """What undoing a record would restore. features: which features are
    enabled now."""
    if record.get("format") != UNDO_FORMAT:
        # Written by Deskence 0.9 or older: everything an import could change.
        return UndoPlan(record.get("name", ""), legacy=record)
    plan = UndoPlan(record.get("name", ""))
    groups = {}
    for entry in record.get("changes", []):
        if not entry.get("applied") or not store.available(entry["schema"], entry["key"]):
            continue
        groups.setdefault(entry["group"], []).append(entry)
    for group, entries in groups.items():
        conflict = any(store.get(e["schema"], e["key"]) != e["after"] for e in entries)
        if all(e["before"] == e["after"] for e in entries):
            continue
        plan.groups.append(UndoGroup(group, entries, conflict))
    for feature in record.get("features", []):
        if feature.get("applied") and feature["module"] in FEATURES:
            conflict = features.get(feature["module"], False) != feature["after"]
            plan.features.append((feature["module"], feature["before"], conflict))
    return plan


def undo(plan, store, set_feature, setters=None, include_conflicts=False):
    """Restores an undo plan; settings changed after the preset only with
    include_conflicts. Returns the labels of what was left alone."""
    setters = setters or {}
    if plan.legacy is not None:
        restore_snapshot(store, plan.legacy, set_feature, setters)
        return []
    left = []
    for group in plan.groups:
        if group.conflict and not include_conflicts:
            left.append(group.label)
            continue
        for entry in group.entries:
            _restore_entry(store, entry, setters)
    for module, before, conflict in plan.features:
        if conflict and not include_conflicts:
            left.append(module_title(module))
            continue
        set_feature(module, before)
    store.sync()
    return left


def snapshot(store, features):
    """Everything an import may change (the undo of Deskence 0.9 and older,
    still read for records written by it)."""
    preset, _files = export_preset(store, "backup", features, pinned=True, stacks=True)
    preset["local"] = {"apps-button-custom-icon": store.get(CUSTOM_ICON.schema,
                                                            CUSTOM_ICON.key)}
    return preset


def restore_snapshot(store, backup, set_feature, setters=None):
    setters = setters or {}
    by_name = {(e.module, e.name): e for e in ENTRIES}
    for module, values in backup.get("modules", {}).items():
        for key, value in values.items():
            entry = by_name.get((module, key))
            if entry and store.available(entry.schema, entry.key):
                setter = setters.get((entry.schema, entry.key))
                if setter:
                    setter(value)
                else:
                    store.set(entry.schema, entry.key, value)
    if "pinned-apps" in backup and store.available(SHELL, "favorite-apps"):
        store.set(SHELL, "favorite-apps", backup["pinned-apps"])
    stacks = backup.get("folder-stacks")
    if stacks:
        store.set(STACKS.schema, STACKS.key, stacks["entries"])
        store.set(STACK_SORTING.schema, STACK_SORTING.key, stacks["sorting"])
    icon = backup.get("local", {}).get("apps-button-custom-icon")
    if icon is not None:
        store.set(CUSTOM_ICON.schema, CUSTOM_ICON.key, icon)
    for module, enabled in backup.get("features", {}).items():
        if module in FEATURES:
            set_feature(module, enabled)
    store.sync()


# --- Saved presets --------------------------------------------------------

def presets_directory():
    return os.path.join(GLib.get_user_data_dir(), "deskence", "presets")


def backup_path():
    return os.path.join(GLib.get_user_state_dir(), "deskence", "before-import.json")


@dataclass
class SavedPreset:
    directory: str
    name: str
    created: str
    data: dict

    @property
    def assets(self):
        return {name: os.path.join(self.directory, member)
                for name, member in self.data.get("assets", {}).items()
                if isinstance(member, str) and ASSET_NAME.fullmatch(member) and
                os.path.isfile(os.path.join(self.directory, member))}


def list_saved(directory=None):
    directory = directory or presets_directory()
    result = []
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return result
    for entry in names:
        path = os.path.join(directory, entry)
        try:
            with open(os.path.join(path, ARCHIVE_PRESET), "rb") as f:
                data = parse(f.read(MAX_JSON_BYTES + 1))
        except (OSError, PresetError):
            continue
        result.append(SavedPreset(path, data.get("name") or entry, data.get("created", ""), data))
    result.sort(key=lambda p: p.name.casefold())
    return result


def save(preset, files, directory=None):
    """Stores a preset among the saved ones; returns its folder."""
    directory = directory or presets_directory()
    os.makedirs(directory, exist_ok=True)
    work = tempfile.mkdtemp(prefix=".new-", dir=directory)
    try:
        if files:
            os.makedirs(os.path.join(work, "assets"))
            for member, source in files.items():
                shutil.copyfile(source, os.path.join(work, member))
        write_preset(os.path.join(work, ARCHIVE_PRESET), preset)
        slug = re.sub(r"[^a-z0-9]+", "-", preset["name"].lower()).strip("-")[:40] or "preset"
        target = os.path.join(directory, f"{slug}-{GLib.uuid_string_random()[:8]}")
        os.rename(work, target)
        return target
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise


def rename(saved, name):
    data = dict(saved.data, name=name[:MAX_NAME_LENGTH])
    write_preset(os.path.join(saved.directory, ARCHIVE_PRESET), data)


def delete(saved, directory=None):
    directory = os.path.realpath(directory or presets_directory())
    path = os.path.realpath(saved.directory)
    # Only a preset folder of our own.
    if os.path.dirname(path) != directory:
        raise OSError(f"{path} is not a saved preset")
    shutil.rmtree(path)


def export_saved(saved, path):
    """Writes a saved preset to a file: an archive when it has images."""
    files = {member: os.path.join(saved.directory, member)
             for member in saved.data.get("assets", {}).values()
             if isinstance(member, str) and ASSET_NAME.fullmatch(member)}
    write_preset(path, saved.data, files or None)
