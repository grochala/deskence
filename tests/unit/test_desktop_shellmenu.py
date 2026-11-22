# SPDX-License-Identifier: GPL-3.0-or-later
import json

import pytest

gi = pytest.importorskip("gi")
from gi.repository import Gio, GLib  # noqa: E402

from deskence_desktop import shellmenu  # noqa: E402
from deskence_desktop.shellareas import parse_activation, parse_areas  # noqa: E402


def actions():
    group = {}
    for name in ("new-folder", "paste", "arrange"):
        group[name] = Gio.SimpleAction.new(name, None)
    group["paste"].set_enabled(False)
    group["sort-order"] = Gio.SimpleAction.new_stateful(
        "sort-order", GLib.VariantType.new("s"), GLib.Variant("s", "size"))
    return group


def desktop_menu():
    menu = Gio.Menu()
    section = Gio.Menu()
    section.append("New _Folder…", "win.new-folder")
    section.append("_Paste", "win.paste")
    section.append("Unknown", "win.missing")
    menu.append_section(None, section)
    section = Gio.Menu()
    section.append("A_rrange Icons", "win.arrange")
    sort = Gio.Menu()
    sort.append("_Name", "win.sort-order::name")
    sort.append("_Size", "win.sort-order::size")
    section.append_submenu("_Sort By", sort)
    menu.append_section(None, section)
    return menu


def test_menu_is_serialized_for_the_shell():
    group = actions()
    accels = {"win.new-folder": "Shift+Ctrl+N"}
    sections = shellmenu.serialize(desktop_menu(), group.get, lambda a: accels.get(a, ""))
    json.dumps(sections)  # what is sent must be plain JSON
    assert [[i["label"] for i in s] for s in sections] == \
        [["New Folder…", "Paste"], ["Arrange Icons", "Sort By"]]
    new_folder, paste = sections[0]
    assert new_folder["action"] == "new-folder" and new_folder["accel"] == "Shift+Ctrl+N"
    assert new_folder["enabled"] and not paste["enabled"]
    sort = sections[1][1]["submenu"][0]
    assert [(i["target"], i["checked"]) for i in sort] == [("name", False), ("size", True)]


def test_mnemonics():
    assert shellmenu.strip_mnemonic("Select _All") == "Select All"
    assert shellmenu.strip_mnemonic("a__b") == "a_b"


def test_activation_lines():
    line = json.dumps({"activate": {"connector": "DP-1", "action": "sort-order",
                                    "target": "name"}})
    assert parse_activation(line) == ("DP-1", "sort-order", "name")
    assert parse_activation(json.dumps({"activate": {"connector": "DP-1",
                                                     "action": "paste"}})) == \
        ("DP-1", "paste", None)
    areas = json.dumps({"areas": {"DP-1": [0, 32, 1280, 768]}})
    assert parse_activation(areas) is None
    assert parse_areas(areas) is not None
    assert parse_activation("not json") is None
