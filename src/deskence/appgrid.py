# SPDX-License-Identifier: GPL-3.0-or-later
"""Order of the applications view: the user's own arrangement or
alphabetical.

GNOME keeps the arrangement in two places: org.gnome.shell app-picker-layout
(pages of the main view: application and folder IDs with their position)
and the "apps" list of each folder (org.gnome.desktop.app-folders). Items
without a stored position are shown after the others, sorted by name.

Before alphabetical sorting starts, both are saved in our manual-layout key;
the app-grid extension then keeps the view sorted (extensions/app-grid).
Going back to the custom order restores what was saved, adapted to what
changed meanwhile: applications that were removed are left out, new ones
appear after the others (GNOME places items without a position there), and
an application moved into another folder stays in that folder.

Only the settings application changes the mode, so the arrangement is
saved and restored here, at the moment of the change, whether the
extension is running or not.
"""

import json

from gi.repository import Gio, GLib

SCHEMA = "io.github.deskence.Deskence.AppGrid"
SHELL = "org.gnome.shell"
FOLDERS = "org.gnome.desktop.app-folders"
FOLDER = "org.gnome.desktop.app-folders.folder"
FOLDERS_PATH = "/org/gnome/desktop/app-folders/folders/"
LAYOUT_TYPE = "aa{sv}"


def layout_to_list(variant):
    """app-picker-layout as [{id: position}] (one dict per page)."""
    return [{item: int(properties.get("position", 0)) if isinstance(properties, dict) else 0
             for item, properties in page.items()}
            for page in variant.unpack()]


def list_to_layout(pages):
    return GLib.Variant(LAYOUT_TYPE, [
        {item: GLib.Variant("a{sv}", {"position": GLib.Variant("i", position)})
         for item, position in page.items()}
        for page in pages])


def restore_pages(saved, known):
    """The saved pages without items that no longer exist (known: IDs of
    installed applications and folders). Positions keep their order;
    GNOME places the remaining items after them."""
    result = []
    for page in saved:
        kept = {item: position for item, position in page.items() if item in known}
        result.append({item: index for index, (item, _p) in
                       enumerate(sorted(kept.items(), key=lambda e: e[1]))})
    while result and not result[-1]:
        result.pop()
    return result


def restore_folder_apps(saved, current):
    """The saved order of a folder's applications, applied to its current
    members: members missing from the saved order (added meanwhile) follow
    in their current order; applications that left the folder are not
    brought back."""
    members = set(current)
    ordered = [app for app in saved if app in members]
    ordered += [app for app in current if app not in set(ordered)]
    return list(dict.fromkeys(ordered))


class AppGrid:
    def __init__(self, source=None, backend=None):
        source = source or Gio.SettingsSchemaSource.get_default()
        self._source = source
        self._backend = backend
        self.settings = self._new(SCHEMA)
        self.shell = self._new(SHELL)
        self.folders = self._new(FOLDERS)

    def _new(self, schema_id, path=None):
        schema = self._source.lookup(schema_id, True)
        if schema is None:
            return None
        return Gio.Settings.new_full(schema, self._backend, path)

    @property
    def available(self):
        return None not in (self.settings, self.shell, self.folders)

    def _folder(self, folder_id):
        return self._new(FOLDER, f"{FOLDERS_PATH}{folder_id}/")

    def capture(self):
        """The current arrangement, as stored in manual-layout."""
        layout = self.shell.get_value("app-picker-layout")
        folders = {f: self._folder(f).get_strv("apps")
                   for f in self.folders.get_strv("folder-children")}
        return {"app-picker-layout": layout_to_list(layout), "folders": folders}

    def set_mode(self, mode, installed=None):
        """Changes sort-mode, saving or restoring the arrangement.
        installed: IDs of installed applications (default: from Gio)."""
        if not self.available or self.settings.get_string("sort-mode") == mode:
            if self.settings is not None:
                self.settings.set_string("sort-mode", mode)
            return
        if mode == "alphabetical":
            self.settings.set_string("manual-layout", json.dumps(self.capture()))
            self.settings.set_string("sort-mode", mode)
            return
        # Back to the custom order: first stop the sorting, then restore.
        self.settings.set_string("sort-mode", mode)
        self.restore(installed)

    def restore(self, installed=None):
        try:
            saved = json.loads(self.settings.get_string("manual-layout") or "null")
        except ValueError:
            saved = None
        if not isinstance(saved, dict):
            return False
        if installed is None:
            installed = {info.get_id() for info in Gio.AppInfo.get_all()}
        folder_ids = self.folders.get_strv("folder-children")
        # The pages first: when a folder list changes, GNOME saves the
        # positions its view shows at that moment, which must already be
        # the restored ones.
        pages = saved.get("app-picker-layout")
        if isinstance(pages, list) and all(isinstance(p, dict) for p in pages):
            known = set(installed) | set(folder_ids)
            self.shell.set_value("app-picker-layout",
                                 list_to_layout(restore_pages(pages, known)))
            Gio.Settings.sync()
        saved_folders = saved.get("folders", {})
        for folder_id in folder_ids:
            if isinstance(saved_folders.get(folder_id), list):
                folder = self._folder(folder_id)
                apps = restore_folder_apps(saved_folders[folder_id], folder.get_strv("apps"))
                if apps != folder.get_strv("apps"):
                    folder.set_strv("apps", apps)
        self.settings.reset("manual-layout")
        Gio.Settings.sync()
        return True
