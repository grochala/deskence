# SPDX-License-Identifier: GPL-3.0-or-later
import json

import pytest

from deskence_desktop.model import CellSize, Placement, Surface
from deskence_desktop.positions import PositionStore


def surface(c="DP-1"):
    return Surface(c, 316, 216, CellSize(100, 100))


def test_positions_are_saved_in_pixels(tmp_path):
    path = tmp_path / "positions.json"
    store = PositionStore(str(path))
    store.set("a.txt", Placement("DP-1", 57, 33))
    store.save()
    data = json.loads(path.read_text())
    assert data == {"version": 3, "items": {"a.txt": {"monitor": "DP-1", "x": 57, "y": 33}}}
    assert PositionStore(str(path)).get("a.txt") == Placement("DP-1", 57, 33)


def test_version_1_cells_are_converted_with_the_current_grid(tmp_path):
    path = tmp_path / "positions.json"
    path.write_text(json.dumps({"version": 1, "items": {
        "a": {"monitor": "DP-1", "col": 2, "row": 1},
        "b": {"monitor": "HDMI-1", "col": 0, "row": 0},
    }}))
    store = PositionStore(str(path))
    assert store.get("a") is None
    assert store.upgrade_legacy({"DP-1": surface()})
    assert store.get("a") == Placement("DP-1", 208, 108)
    # The other monitor is not connected: its cell is kept for later and
    # layout knows the icon has a home.
    assert store.has_legacy("b")
    assert store.for_layout()["b"].connector == "HDMI-1"
    store.save()
    again = PositionStore(str(path))
    assert again.get("a") == Placement("DP-1", 208, 108)
    assert again.has_legacy("b")
    assert again.upgrade_legacy({"HDMI-1": surface("HDMI-1")})
    assert again.get("b") == Placement("HDMI-1", 8, 8)


def test_legacy_entries_follow_renames_and_pruning(tmp_path):
    path = tmp_path / "positions.json"
    path.write_text(json.dumps({"version": 1, "items": {
        "a": {"monitor": "X", "col": 0, "row": 0},
        "mount:file:///m": {"monitor": "X", "col": 1, "row": 0}}}))
    store = PositionStore(str(path))
    store.rename("a", "b")
    assert store.has_legacy("b") and not store.has_legacy("a")
    store.prune(set())
    assert not store.has_legacy("b")
    assert store.has_legacy("mount:file:///m")


def test_invalid_pixel_entries_are_skipped(tmp_path):
    path = tmp_path / "positions.json"
    path.write_text(json.dumps({"version": 3, "items": {
        "a": {"monitor": "X", "x": "nope", "y": 1},
        "b": {"monitor": "X", "x": 1, "y": 2},
        "c": "garbage"}}))
    store = PositionStore(str(path))
    assert store.items == {"b": Placement("X", 1, 2)}
    path.write_text(json.dumps({"version": 4, "items": {"b": {"monitor": "X", "x": 1, "y": 2}}}))
    assert PositionStore(str(path)).items == {}, "unknown future format is not misread"


def test_version_2_area_pixels_become_monitor_pixels(tmp_path):
    path = tmp_path / "positions.json"
    path.write_text(json.dumps({"version": 2, "items": {"a": {"monitor": "DP-1", "x": 16, "y": 20}}}))
    store = PositionStore(str(path))
    assert store.get("a") is None and store.has_legacy("a")
    store.save()
    assert PositionStore(str(path)).has_legacy("a"), "kept until the monitor is there"
    area = Surface("DP-1", 1200, 768, CellSize(100, 100), x=80, y=32)
    assert store.upgrade_legacy({"DP-1": area})
    assert store.get("a") == Placement("DP-1", 96, 52)


def test_parse_areas():
    pytest.importorskip("gi")
    from deskence_desktop.shellareas import parse_areas
    full = parse_areas('{"areas": {"DP-1": [0, 32, 1280, 768]}, '
                       '"exclusions": {"DP-1": [[373, 718, 533, 82]]}, '
                       '"workareas": {"DP-1": [0, 32, 1280, 686]}}')
    g = full["DP-1"]
    assert g.area == (0, 32, 1280, 768)
    assert g.exclusions == ((373, 718, 533, 82),)
    assert g.workarea == (0, 32, 1280, 686)
    old = parse_areas('{"areas": {"DP-1": [0, 32, 1280, 686]}}')["DP-1"]
    assert old.exclusions == () and old.workarea == old.area
    assert parse_areas('{"areas": {"DP-1": [0, 0, 0, 10]}}') == {}
    assert parse_areas("not json") is None
    assert parse_areas('{"areas": {"DP-1": [1, 2]}}') is None
    assert parse_areas('{"other": 1}') is None
