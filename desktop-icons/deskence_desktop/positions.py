# SPDX-License-Identifier: GPL-3.0-or-later
"""Remembered icon positions.

Stored in $XDG_STATE_HOME/deskence/icon-positions.json as
{"version": 3, "items": {"<id>": {"monitor": "DP-1", "x": 120, "y": 40}}}:
the slot origin in logical pixels relative to the top-left corner of the
monitor (see model.Surface), so moving the dock or the top bar does not move
icons. File ids are their names inside the desktop folder; special icons use
"special:home", "special:trash" and "mount:<uri>".

Older versions are converted the first time the monitor they belong to is
connected, with its geometry of that moment, so upgrading does not move
icons: version 1 stored grid cells ({"col": 0, "row": 1}), version 2 pixels
relative to the available area ({"x": .., "y": .., "area": true} once read).

Before the project was renamed to Deskence (0.4.0) the file was in
$XDG_STATE_HOME/better-gnome-desktop/. When only that file exists it is
copied to the new place; the old file stays, so an older version installed
again still finds its positions.

The file only holds layout data; it is never needed to keep user files safe.
"""

import json
import os
import shutil

from .model import Placement

VERSION = 3


FILE_NAME = "icon-positions.json"
STATE_DIR = "deskence"
LEGACY_STATE_DIR = "better-gnome-desktop"


def _state_home():
    return os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")


def default_path():
    return os.path.join(_state_home(), STATE_DIR, FILE_NAME)


def legacy_path():
    return os.path.join(_state_home(), LEGACY_STATE_DIR, FILE_NAME)


def migrate_legacy_file(path, old_path):
    """Copy the positions file of the old name to path, once.

    Returns True when it was copied. An existing file at path always wins.
    """
    if os.path.exists(path) or not os.path.isfile(old_path):
        return False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        shutil.copyfile(old_path, tmp)
        os.replace(tmp, path)
    except OSError:
        return False
    return True


class PositionStore:
    def __init__(self, path=None):
        if path is None:
            path = default_path()
            migrate_legacy_file(path, legacy_path())
        self.path = path
        self._items = {}
        self._legacy = {}
        self.load()

    def load(self):
        self._items = {}
        self._legacy = {}
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        version = data.get("version") if isinstance(data, dict) else None
        if version not in (1, 2, VERSION):
            return
        items = data.get("items", {})
        if not isinstance(items, dict):
            return
        for item_id, value in items.items():
            try:
                connector = str(value["monitor"])
                if "x" in value and version == 2 or value.get("area"):
                    self._legacy[item_id] = (connector, "area", int(value["x"]), int(value["y"]))
                elif "x" in value:
                    self._items[item_id] = Placement(
                        connector, int(value["x"]), int(value["y"]))
                else:
                    self._legacy[item_id] = (connector, "cell", int(value["col"]), int(value["row"]))
            except (KeyError, TypeError, ValueError):
                continue

    def save(self):
        items = {}
        for item_id, (c, kind, a, b) in self._legacy.items():
            items[item_id] = {"monitor": c, "col": a, "row": b} if kind == "cell" \
                else {"monitor": c, "x": a, "y": b, "area": True}
        items.update({item_id: {"monitor": p.connector, "x": p.x, "y": p.y}
                      for item_id, p in self._items.items()})
        data = {"version": VERSION, "items": dict(sorted(items.items()))}
        directory = os.path.dirname(self.path)
        os.makedirs(directory, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.path)

    @property
    def items(self):
        return dict(self._items)

    def for_layout(self):
        """Positions for model.layout().

        Legacy cells left after upgrade_legacy() belong to disconnected
        monitors; they are included with a dummy position, so layout()
        knows the icon has a home and does not save a new one.
        """
        result = {item_id: Placement(legacy[0], 0, 0) for item_id, legacy in self._legacy.items()}
        result.update(self._items)
        return result

    def get(self, item_id):
        return self._items.get(item_id)

    def set(self, item_id, placement):
        self._legacy.pop(item_id, None)
        self._items[item_id] = placement

    def update(self, placements):
        for item_id, placement in placements.items():
            self.set(item_id, placement)

    def upgrade_legacy(self, surfaces):
        """Convert older entries of connected monitors to monitor pixels.

        surfaces: {connector: model.Surface}. Returns True when something
        was converted.
        """
        changed = False
        for item_id, (connector, kind, a, b) in list(self._legacy.items()):
            surface = surfaces.get(connector)
            if surface is None:
                continue
            if kind == "cell":
                col = min(max(a, 0), surface.grid.columns - 1)
                row = min(max(b, 0), surface.grid.rows - 1)
                slot = surface.origin(col, row)
            else:
                slot = (surface.x + a, surface.y + b)
            self.set(item_id, Placement(connector, *slot))
            changed = True
        return changed

    def has_legacy(self, item_id):
        return item_id in self._legacy

    def rename(self, old_id, new_id):
        if old_id in self._items:
            self._items[new_id] = self._items.pop(old_id)
        if old_id in self._legacy:
            self._legacy[new_id] = self._legacy.pop(old_id)

    def remove(self, item_id):
        self._items.pop(item_id, None)
        self._legacy.pop(item_id, None)

    def prune(self, existing_ids):
        """Forget files that no longer exist.

        Drives keep their position while unplugged.
        """
        for store in (self._items, self._legacy):
            for item_id in list(store):
                if item_id not in existing_ids and not item_id.startswith("mount:"):
                    del store[item_id]

    def clear(self):
        self._items = {}
        self._legacy = {}

    def __len__(self):
        return len(self._items) + len(self._legacy)
