# SPDX-License-Identifier: GPL-3.0-or-later
"""Presets: export, validation, portability, partial imports, archives,
rollback and the order of the applications view.

Real GSettings with a memory backend: the Deskence schema plus minimal
stand-ins of the GNOME schemas presets touch, so the tests do not depend on
what is installed.
"""
import json
import os
import shutil
import subprocess
import zipfile

import pytest

gi = pytest.importorskip("gi")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gio, GLib  # noqa: E402

from deskence import appgrid, presets  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMAS = os.path.join(ROOT, "data", "schemas")

GNOME_SCHEMAS = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="org.gnome.shell" path="/org/gnome/shell/">
    <key name="favorite-apps" type="as"><default>['a.desktop']</default></key>
    <key name="app-picker-layout" type="aa{sv}"><default>[]</default></key>
  </schema>
  <schema id="org.gnome.desktop.wm.preferences" path="/org/gnome/desktop/wm/preferences/">
    <key name="button-layout" type="s"><default>'appmenu:close'</default></key>
  </schema>
  <schema id="org.gnome.desktop.wm.keybindings" path="/org/gnome/desktop/wm/keybindings/">
    <key name="toggle-above" type="as"><default>[]</default></key>
  </schema>
  <schema id="org.gnome.desktop.app-folders" path="/org/gnome/desktop/app-folders/">
    <key name="folder-children" type="as"><default>[]</default></key>
  </schema>
  <schema id="org.gnome.desktop.app-folders.folder">
    <key name="apps" type="as"><default>[]</default></key>
    <key name="name" type="s"><default>''</default></key>
  </schema>
</schemalist>
"""


@pytest.fixture(scope="module")
def schema_dir(tmp_path_factory):
    compiler = shutil.which("glib-compile-schemas")
    if compiler is None:
        pytest.skip("glib-compile-schemas is not available")
    directory = tmp_path_factory.mktemp("schemas")
    shutil.copy(os.path.join(SCHEMAS, "io.github.deskence.Deskence.gschema.xml"), directory)
    (directory / "gnome.gschema.xml").write_text(GNOME_SCHEMAS)
    subprocess.run([compiler, "--strict", str(directory)], check=True)
    return str(directory)


@pytest.fixture
def source(schema_dir):
    return Gio.SettingsSchemaSource.new_from_directory(schema_dir, None, False)


@pytest.fixture
def store(source):
    return presets.SettingsStore(source, Gio.memory_settings_backend_new())


@pytest.fixture
def home(tmp_path):
    # Localized XDG folder names (Polish), so that standard folders are
    # matched by their XDG identity and not by an English name.
    h = tmp_path / "home" / "anna"
    for d in ("Pobrane", "Dokumenty", "Projects/site"):
        (h / d).mkdir(parents=True)
    return str(h)


def context(home, **kw):
    dirs = {"DOWNLOAD": os.path.join(home, "Pobrane"),
            "DOCUMENTS": os.path.join(home, "Dokumenty")}
    return presets.Context(home=home, dirs=dirs, **kw)


def roundtrip(preset):
    return presets.parse(json.dumps(preset).encode())


# --- Export ---------------------------------------------------------------

def test_export_lists_modules_and_only_listed_keys(store):
    store.set(presets.DOCK, "position", "left")
    store.set(presets.CLIPBOARD, "paused", True)
    preset, files = presets.export_preset(store, "Praca", {"dock": True})
    assert preset["format"] == presets.FORMAT_ID
    assert preset["version"] == presets.FORMAT_VERSION
    assert preset["name"] == "Praca"
    assert preset["modules"]["dock"]["position"] == "left"
    assert preset["modules"]["windows"]["button-layout"] == "appmenu:close"
    assert preset["modules"]["windows"]["always-on-top-shortcut"] == []
    assert files == {}
    exported = {(m, k) for m, values in preset["modules"].items() for k in values}
    # Internal state never leaves the computer.
    for module, key in (("clipboard", "paused"), ("app-grid", "manual-layout"),
                        ("dock", "apps-button-custom-icon"), ("dock", "folder-stacks"),
                        ("windows", "original-button-layout")):
        assert (module, key) not in exported
    assert "pinned-apps" not in preset and "folder-stacks" not in preset


def test_optional_parts(store, home):
    store.set(presets.DOCK, "folder-stacks", ["xdg:DOWNLOAD", "home:Projects/site"])
    preset, _ = presets.export_preset(store, "x", {}, pinned=True, stacks=True)
    assert preset["pinned-apps"] == ["a.desktop"]
    assert preset["folder-stacks"]["entries"] == ["xdg:DOWNLOAD", "home:Projects/site"]


def test_folder_tile_background_roundtrip(store, home):
    store.set(presets.DOCK, "app-grid-folder-custom-color", True)
    store.set(presets.DOCK, "app-grid-folder-color", "#3584e4")
    store.set(presets.DOCK, "app-grid-folder-custom-transparency", True)
    store.set(presets.DOCK, "app-grid-folder-transparency", 70)
    preset, _ = presets.export_preset(store, "Folders", {})
    assert preset["modules"]["app-grid"]["app-grid-folder-color"] == "#3584e4"
    assert preset["modules"]["app-grid"]["app-grid-folder-transparency"] == 70
    for key in ("app-grid-folder-custom-color", "app-grid-folder-color",
                "app-grid-folder-custom-transparency", "app-grid-folder-transparency"):
        store.reset(presets.DOCK, key)
    plan = presets.plan_import(roundtrip(preset), store, context(home))
    changes = {(c.module, c.name): c.new for c in plan.changes}
    assert changes[("app-grid", "app-grid-folder-custom-color")] is True
    assert changes[("app-grid", "app-grid-folder-transparency")] == 70


def test_hover_highlight_roundtrip(store, home):
    store.set(presets.DOCK, "app-grid-hover-custom-color", True)
    store.set(presets.DOCK, "app-grid-hover-color", "#ffffff")
    store.set(presets.DOCK, "app-grid-hover-custom-transparency", True)
    store.set(presets.DOCK, "app-grid-hover-transparency", 85)
    preset, _ = presets.export_preset(store, "Hover", {})
    exported = preset["modules"]["app-grid"]
    assert exported["app-grid-hover-color"] == "#ffffff"
    assert exported["app-grid-hover-transparency"] == 85
    keys = ("app-grid-hover-custom-color", "app-grid-hover-color",
            "app-grid-hover-custom-transparency", "app-grid-hover-transparency")
    for key in keys:
        store.reset(presets.DOCK, key)
    plan = presets.plan_import(roundtrip(preset), store, context(home))
    changes = {(c.module, c.name): c.new for c in plan.changes}
    assert changes[("app-grid", "app-grid-hover-custom-color")] is True
    assert changes[("app-grid", "app-grid-hover-color")] == "#ffffff"
    assert changes[("app-grid", "app-grid-hover-custom-transparency")] is True
    assert changes[("app-grid", "app-grid-hover-transparency")] == 85


def test_hover_transparency_range_checked(store, home):
    data = roundtrip({"format": presets.FORMAT_ID, "version": 1,
                      "modules": {"app-grid": {"app-grid-hover-transparency": 150}}})
    plan = presets.plan_import(data, store, context(home))
    assert all(c.name != "app-grid-hover-transparency" for c in plan.changes)


def test_older_preset_keeps_hover_highlight(store, home):
    # Presets made before the hover settings existed leave them alone.
    store.set(presets.DOCK, "app-grid-hover-custom-transparency", True)
    store.set(presets.DOCK, "app-grid-hover-transparency", 30)
    data = roundtrip({"format": presets.FORMAT_ID, "version": 1,
                      "modules": {"app-grid": {"app-grid-folder-custom-color": True}}})
    plan = presets.plan_import(data, store, context(home))
    assert {c.name for c in plan.changes} == {"app-grid-folder-custom-color"}


def test_desktop_at_login_in_presets(store, home):
    assert store.get(presets.SCHEMA, "show-desktop-at-login") is False
    store.set(presets.SCHEMA, "show-desktop-at-login", True)
    preset, _ = presets.export_preset(store, "Start", {})
    assert preset["modules"]["general"]["show-desktop-at-login"] is True
    store.reset(presets.SCHEMA, "show-desktop-at-login")
    plan = presets.plan_import(roundtrip(preset), store, context(home))
    assert [(c.module, c.name, c.new) for c in plan.changes
            if c.module == "general"] == [("general", "show-desktop-at-login", True)]
    # Presets made before the setting existed leave it alone.
    store.set(presets.SCHEMA, "show-desktop-at-login", True)
    old = roundtrip({"format": presets.FORMAT_ID, "version": 1,
                     "modules": {"dock": {"position": "left"}}})
    plan = presets.plan_import(old, store, context(home))
    assert all(c.module != "general" for c in plan.changes)


def test_older_preset_keeps_folder_tile_background(store, home):
    # Presets made before the folder settings existed leave them alone.
    store.set(presets.DOCK, "app-grid-folder-custom-transparency", True)
    store.set(presets.DOCK, "app-grid-folder-transparency", 40)
    data = roundtrip({"format": presets.FORMAT_ID, "version": 1,
                      "modules": {"app-grid": {"app-grid-custom-color": True}}})
    plan = presets.plan_import(data, store, context(home))
    assert {c.name for c in plan.changes} == {"app-grid-custom-color"}


def test_export_is_plain_json(store, tmp_path):
    preset, files = presets.export_preset(store, "Zażółć", {})
    path = tmp_path / "p.json"
    presets.write_preset(str(path), preset, files or None)
    text = path.read_text(encoding="utf-8")
    assert "Zażółć" in text
    assert json.loads(text)["modules"]["dock"]["icon-size"] == 48


# --- Validation -----------------------------------------------------------

@pytest.mark.parametrize("raw", [
    b"not json", b"[]", b'{"format": "other", "version": 1}',
    b'{"format": "io.github.deskence.Deskence.preset"}',
    b'{"format": "io.github.deskence.Deskence.preset", "version": "1"}',
    b'{"format": "io.github.deskence.Deskence.preset", "version": true}',
    "{\"format\": \"io.github.deskence.Deskence.preset\", \"version\": 1, \"x\": \"\xff\"}"
    .encode("latin-1"),
])
def test_invalid_files_are_rejected(raw):
    with pytest.raises(presets.PresetError):
        presets.parse(raw)


def test_newer_format_is_rejected():
    raw = json.dumps({"format": presets.FORMAT_ID, "version": presets.FORMAT_VERSION + 1})
    with pytest.raises(presets.PresetError, match="newer"):
        presets.parse(raw.encode())


def test_older_format_is_migrated(monkeypatch):
    monkeypatch.setattr(presets, "FORMAT_VERSION", 2)
    monkeypatch.setitem(presets.FORMAT_MIGRATIONS, 1,
                        lambda d: dict(d, version=2, modules={"dock": d["dock-settings"]}))
    data = presets.parse(json.dumps({"format": presets.FORMAT_ID, "version": 1,
                                     "dock-settings": {"position": "right"}}).encode())
    assert data["version"] == 2 and data["modules"] == {"dock": {"position": "right"}}


def test_types_and_ranges_are_checked(store, home):
    data = roundtrip({"format": presets.FORMAT_ID, "version": 1, "modules": {
        "dock": {"icon-size": 500, "position": "top", "magnify": "yes",
                 "magnify-strength": 1.8, "length": "full"},
        "clipboard": {"max-entries": 20.5, "shortcut": ["<Super>c", 3]},
    }})
    plan = presets.plan_import(data, store, context(home))
    changed = {(c.module, c.name): c.new for c in plan.changes}
    assert changed == {("dock", "magnify-strength"): 1.8, ("dock", "length"): "full"}
    assert len(plan.skipped) == 5
    assert all("invalid value" in s for s in plan.skipped)


def test_unknown_settings_and_modules_are_reported(store, home):
    data = roundtrip({"format": presets.FORMAT_ID, "version": 1, "modules": {
        "dock": {"position": "left", "rainbow": True},
        "teleport": {"enabled": True},
        "windows": "broken",
    }, "features": {"dock": True, "flying": True}})
    plan = presets.plan_import(data, store, context(home, features={"dock": False}))
    assert [(c.module, c.name, c.new) for c in plan.changes] == [("dock", "position", "left")]
    assert plan.features == {"dock": True}
    assert len(plan.skipped) == 4


def test_matching_settings_make_an_empty_plan(store, home):
    preset, _ = presets.export_preset(store, "x", {"dock": True})
    plan = presets.plan_import(roundtrip(preset), store, context(home, features={"dock": True}))
    assert plan.empty


def test_missing_gnome_schema_is_skipped(schema_dir, home, tmp_path):
    # Only the Deskence schema: no GNOME settings on this "computer".
    directory = tmp_path / "only"
    directory.mkdir()
    shutil.copy(os.path.join(SCHEMAS, "io.github.deskence.Deskence.gschema.xml"), directory)
    subprocess.run(["glib-compile-schemas", str(directory)], check=True)
    store = presets.SettingsStore(
        Gio.SettingsSchemaSource.new_from_directory(str(directory), None, False),
        Gio.memory_settings_backend_new())
    data = roundtrip({"format": presets.FORMAT_ID, "version": 1,
                      "modules": {"windows": {"button-layout": "close"}},
                      "pinned-apps": ["a.desktop"]})
    plan = presets.plan_import(data, store, context(home))
    assert plan.empty and len(plan.skipped) == 2


# --- Portability ------------------------------------------------------------

def test_standard_folders_by_identity(home):
    dirs = context(home).dirs
    assert presets.stack_entry(os.path.join(home, "Pobrane"), home, dirs) == "xdg:DOWNLOAD"
    assert presets.stack_entry(os.path.join(home, "Projects", "site"), home, dirs) == \
        "home:Projects/site"
    assert presets.stack_entry("/srv/data", home, dirs) == "file:///srv/data"
    # Another user with an English Downloads folder.
    other = {"DOWNLOAD": "/home/bob/Downloads"}
    assert presets.stack_path("xdg:DOWNLOAD", "/home/bob", other) == "/home/bob/Downloads"
    assert presets.stack_path("home:Projects/site", "/home/bob", other) == \
        "/home/bob/Projects/site"


def test_stack_entries_cannot_leave_home():
    assert presets.stack_path("home:../etc", "/home/bob", {}) is None
    assert presets.stack_path("home:/etc", "/home/bob", {}) is None
    assert presets.stack_path("ftp://x", "/home/bob", {}) is None


def test_other_home_name_is_adapted(home):
    entry = "file:///home/olduser/Projects/site"
    assert presets.adapt_stack_entry(entry, home, {}) == "home:Projects/site"
    assert presets.adapt_stack_entry("file:///var/home/x/Projects/site", home, {}) == \
        "home:Projects/site"
    # Nothing to adapt to: kept, reported as missing later.
    assert presets.adapt_stack_entry("file:///home/olduser/Nope", home, {}) == \
        "file:///home/olduser/Nope"


def test_import_after_reinstall(store, home):
    """A preset from another computer: different user, missing folder,
    missing application, monitor not connected; everything else applies."""
    data = roundtrip({
        "format": presets.FORMAT_ID, "version": 1, "name": "Old laptop",
        "modules": {"dock": {"position": "right", "monitor-mode": "selected",
                             "selected-monitor": "HDMI-9"}},
        "features": {"dock": True, "clipboard": True},
        "pinned-apps": ["a.desktop", "gone.desktop"],
        "folder-stacks": {
            "entries": ["xdg:DOWNLOAD", "xdg:MUSIC", "file:///home/olduser/Projects/site",
                        "home:Missing", "home:../../etc"],
            "sorting": {"xdg:DOWNLOAD": "modified",
                        "file:///home/olduser/Projects/site": "type", "home:Missing": "bogus"}},
    })
    ctx = context(home, connectors=["eDP-1"], app_exists=lambda a: a != "gone.desktop",
                  features={"dock": True})
    plan = presets.plan_import(data, store, ctx)
    changes = {(c.module, c.name): c.new for c in plan.changes}
    assert changes[("dock", "position")] == "right"
    assert changes[("pinned-apps", "favorite-apps")] == ["a.desktop", "gone.desktop"]
    assert changes[("folder-stacks", "entries")] == [
        "xdg:DOWNLOAD", "xdg:MUSIC", "home:Projects/site", "home:Missing"]
    assert changes[("folder-stacks", "sorting")] == {
        "xdg:DOWNLOAD": "modified", "home:Projects/site": "type"}
    assert plan.features == {"clipboard": True}
    text = "\n".join(plan.warnings)
    assert "HDMI-9" in text and "gone" in text and "Music" in text and "Missing" in text
    assert any("../../etc" in s for s in plan.skipped)


# --- Archives ---------------------------------------------------------------

def _png(path, size=32):
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, size, size)
    pixbuf.fill(0x3584e4ff)
    pixbuf.savev(str(path), "png", [], [])


def test_archive_roundtrip(store, home, tmp_path):
    icon = tmp_path / "icon.png"
    _png(icon)
    store.set(presets.DOCK, "apps-button-custom-icon", str(icon))
    store.set(presets.DOCK, "apps-button-icon", "custom")
    preset, files = presets.export_preset(store, "x", {}, assets=True)
    assert preset["assets"] == {"apps-button-icon": "assets/apps-button-icon.png"}
    path = tmp_path / "x.deskence"
    presets.write_preset(str(path), preset, files)
    work = tmp_path / "work"
    work.mkdir()
    data, assets = presets.read_file(str(path), str(work))
    assert data["name"] == "x"
    assert open(assets["apps-button-icon"], "rb").read() == icon.read_bytes()
    assert os.path.dirname(assets["apps-button-icon"]) == str(work)


@pytest.mark.parametrize("member", ["../evil.png", "/tmp/evil.png", "assets/../../evil.png",
                                    "assets/sub/evil.png", "other/evil.png"])
def test_archive_members_cannot_escape(tmp_path, member):
    path = tmp_path / "bad.deskence"
    preset = {"format": presets.FORMAT_ID, "version": 1, "name": "bad",
              "assets": {"apps-button-icon": member}}
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("preset.json", json.dumps(preset))
        z.writestr(member, b"x")
    work = tmp_path / "work"
    work.mkdir()
    data, assets = presets.read_file(str(path), str(work))
    assert assets == {}
    assert os.listdir(work) == []
    assert not (tmp_path / "evil.png").exists()


def test_archive_without_preset_and_too_large(tmp_path):
    path = tmp_path / "a.deskence"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("other.json", "{}")
    with pytest.raises(presets.PresetError):
        presets.read_file(str(path), str(tmp_path))
    with zipfile.ZipFile(path, "w") as z:
        for i in range(presets.MAX_ARCHIVE_MEMBERS + 1):
            z.writestr(f"f{i}", "")
    with pytest.raises(presets.PresetError):
        presets.read_file(str(path), str(tmp_path))


def test_too_large_json(tmp_path):
    path = tmp_path / "big.json"
    path.write_bytes(b" " * (presets.MAX_JSON_BYTES + 1))
    with pytest.raises(presets.PresetError):
        presets.read_file(str(path), str(tmp_path))


def test_missing_image_falls_back_to_default_icon(store, home):
    data = roundtrip({"format": presets.FORMAT_ID, "version": 1,
                      "modules": {"dock": {"apps-button-icon": "custom"}}})
    plan = presets.plan_import(data, store, context(home))
    assert plan.changes == [] or all(c.new != "custom" for c in plan.changes)
    assert plan.warnings


# --- Applying -------------------------------------------------------------

def apply(store, home, tmp_path, modules, features=None, current=None, setters=None,
          calls=None):
    data = roundtrip({"format": presets.FORMAT_ID, "version": 1, "name": "Test",
                      "modules": modules, **({"features": features} if features else {})})
    plan = presets.plan_import(data, store, context(home, features=current or {}))
    path = str(tmp_path / "state" / "undo.json")
    record = presets.apply_plan(plan, store, features=current or {},
                                set_feature=lambda m, e: (calls if calls is not None else [])
                                .append((m, e)),
                                import_icon=lambda p: p, backup_path=path, setters=setters)
    return record, path


def undo(store, path, current=None, include=False, calls=None, setters=None):
    plan = presets.plan_undo(presets.load_undo(path), store, current or {})
    left = presets.undo(plan, store, lambda m, e: (calls if calls is not None else [])
                        .append((m, e)), setters, include_conflicts=include)
    return plan, left


def test_apply_and_undo(store, home, tmp_path):
    calls = []
    store.set(presets.DOCK, "length", "full")            # set before the preset
    record, path = apply(store, home, tmp_path,
                         {"dock": {"position": "left", "length": "fit"},
                          "windows": {"button-layout": "close:"}},
                         features={"dock": True}, current={"dock": False}, calls=calls)
    assert store.get(presets.DOCK, "position") == "left"
    assert calls == [("dock", True)]
    # Only what the preset changes is recorded, with how it was before.
    entries = {e["key"]: e for e in record["changes"]}
    assert set(entries) == {"position", "length", "button-layout"}
    assert entries["position"]["before-set"] is False and entries["length"]["before-set"] is True
    assert presets.load_undo(path)["format"] == presets.UNDO_FORMAT

    plan, left = undo(store, path, current={"dock": True}, calls=calls)
    assert not plan.conflicts and left == []
    assert store.get(presets.DOCK, "position") == "bottom"
    # A default stays a default, a set value comes back set.
    assert store.settings(presets.DOCK).get_user_value("position") is None
    assert store.get(presets.DOCK, "length") == "full"
    assert store.settings(presets.DOCK).get_user_value("length") is not None
    assert store.get(presets.WM_PREFERENCES, "button-layout") == "appmenu:close"
    assert calls[-1] == ("dock", False)


def test_later_changes_are_not_undone_silently(store, home, tmp_path):
    _record, path = apply(store, home, tmp_path,
                          {"dock": {"position": "left", "icon-size": 64}})
    store.set(presets.DOCK, "icon-size", 32)              # the user, afterwards
    plan, left = undo(store, path)
    assert plan.conflicts == ["Dock: icon-size"]
    assert store.get(presets.DOCK, "position") == "bottom"
    assert store.get(presets.DOCK, "icon-size") == 32 and left == ["Dock: icon-size"]

    _record, path = apply(store, home, tmp_path, {"dock": {"icon-size": 56}})
    store.set(presets.DOCK, "icon-size", 40)
    undo(store, path, include=True)
    assert store.get(presets.DOCK, "icon-size") == 32      # by choice


def test_an_option_of_several_keys_is_undone_whole(store, home, tmp_path):
    _record, path = apply(store, home, tmp_path,
                          {"dock": {"background-custom-color": True,
                                    "background-color": "#3584e4"}})
    store.set(presets.DOCK, "background-color", "#e01b24")   # changed afterwards
    plan, left = undo(store, path)
    assert [g.group for g in plan.groups] == [f"{presets.DOCK} background-color"]
    assert plan.groups[0].conflict
    # Not half of it: the switch stays on together with the new color.
    assert store.get(presets.DOCK, "background-custom-color") is True
    assert store.get(presets.DOCK, "background-color") == "#e01b24"
    assert presets.option_group(presets.DOCK, "app-grid-folder-custom-transparency") == \
        presets.option_group(presets.DOCK, "app-grid-folder-transparency")
    assert presets.option_group(presets.DOCK, "app-grid-folder-color") != \
        presets.option_group(presets.DOCK, "app-grid-color")


def test_feature_changed_afterwards_is_a_conflict(store, home, tmp_path):
    calls = []
    _record, path = apply(store, home, tmp_path, {"dock": {"position": "left"}},
                          features={"clipboard": True}, current={"clipboard": False},
                          calls=calls)
    plan, left = undo(store, path, current={"clipboard": False}, calls=calls)
    assert "Clipboard" in plan.conflicts and left == ["Clipboard"]
    assert calls == [("clipboard", True)]                 # not turned off again


def test_another_preset_replaces_the_undo(store, home, tmp_path):
    apply(store, home, tmp_path, {"dock": {"position": "left"}})
    _record, path = apply(store, home, tmp_path, {"dock": {"position": "right"}})
    undo(store, path)
    assert store.get(presets.DOCK, "position") == "left"   # one level


def test_failed_apply_puts_back_only_what_changed(store, home, tmp_path):
    data = roundtrip({"format": presets.FORMAT_ID, "version": 1,
                      "modules": {"dock": {"position": "left", "length": "full"},
                                  "app-grid": {"sort-mode": "alphabetical"}}})
    plan = presets.plan_import(data, store, context(home))
    path = tmp_path / "b.json"

    def broken(value):
        raise OSError("disk full")
    with pytest.raises(presets.ApplyError) as failure:
        presets.apply_plan(plan, store, features={}, set_feature=lambda m, e: None,
                           import_icon=lambda p: p, backup_path=str(path),
                           setters={(presets.APP_GRID, "sort-mode"): broken})
    assert store.get(presets.DOCK, "position") == "bottom"
    assert store.get(presets.DOCK, "length") == "fit"
    assert "disk full" in str(failure.value) and not failure.value.kept
    assert not path.exists()                              # nothing left to undo


def test_older_undo_records_still_work(store, home, tmp_path):
    store.set(presets.DOCK, "position", "right")
    backup = presets.snapshot(store, {})
    path = tmp_path / "old.json"
    presets.write_preset(str(path), backup)
    store.set(presets.DOCK, "position", "left")
    plan, _left = undo(store, str(path))
    assert plan.legacy is not None
    assert store.get(presets.DOCK, "position") == "right"


def test_saved_presets(tmp_path, store):
    directory = str(tmp_path / "presets")
    preset, files = presets.export_preset(store, "Dom", {})
    folder = presets.save(preset, files, directory)
    saved = presets.list_saved(directory)
    assert [p.name for p in saved] == ["Dom"]
    presets.rename(saved[0], "Biuro")
    saved = presets.list_saved(directory)
    assert saved[0].name == "Biuro"
    out = tmp_path / "out.json"
    presets.export_saved(saved[0], str(out))
    assert presets.parse(out.read_bytes())["name"] == "Biuro"
    presets.delete(saved[0], directory)
    assert presets.list_saved(directory) == []
    assert not os.path.exists(folder)


def test_delete_only_own_presets(tmp_path):
    victim = tmp_path / "important"
    victim.mkdir()
    fake = presets.SavedPreset(str(victim), "x", "", {})
    with pytest.raises(OSError):
        presets.delete(fake, str(tmp_path / "presets"))
    assert victim.exists()


# --- Applications view order ----------------------------------------------

def test_restore_pages_drops_removed_items():
    saved = [{"a": 0, "gone": 1, "b": 2}, {"gone2": 0}]
    assert appgrid.restore_pages(saved, {"a", "b", "new"}) == [{"a": 0, "b": 1}]


def test_restore_folder_apps():
    saved = ["c", "a", "gone", "b"]
    # "gone" was uninstalled, "d" was added to the folder meanwhile, "b" left.
    assert appgrid.restore_folder_apps(saved, ["a", "c", "d"]) == ["c", "a", "d"]


def test_manual_layout_saved_and_restored(source):
    backend = Gio.memory_settings_backend_new()
    grid = appgrid.AppGrid(source, backend)
    pages = [{"x.desktop": 0, "Folder1": 1, "y.desktop": 2}, {"z.desktop": 0}]
    grid.shell.set_value("app-picker-layout", appgrid.list_to_layout(pages))
    grid.folders.set_strv("folder-children", ["Folder1"])
    grid._folder("Folder1").set_strv("apps", ["q.desktop", "p.desktop"])

    grid.set_mode("alphabetical")
    assert grid.settings.get_string("sort-mode") == "alphabetical"
    saved = json.loads(grid.settings.get_string("manual-layout"))
    assert saved["app-picker-layout"] == pages
    assert saved["folders"] == {"Folder1": ["q.desktop", "p.desktop"]}

    # What the sorting does meanwhile.
    grid.shell.set_value("app-picker-layout", GLib.Variant("aa{sv}", []))
    grid._folder("Folder1").set_strv("apps", ["n.desktop", "p.desktop", "q.desktop"])

    grid.set_mode("custom", installed={"x.desktop", "z.desktop", "n.desktop",
                                       "p.desktop", "q.desktop"})
    assert grid.settings.get_string("sort-mode") == "custom"
    assert appgrid.layout_to_list(grid.shell.get_value("app-picker-layout")) == \
        [{"x.desktop": 0, "Folder1": 1}, {"z.desktop": 0}]
    assert grid._folder("Folder1").get_strv("apps") == ["q.desktop", "p.desktop", "n.desktop"]
    assert grid.settings.get_string("manual-layout") == ""
