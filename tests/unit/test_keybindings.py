# SPDX-License-Identifier: GPL-3.0-or-later
"""Keyboard shortcuts: spelling, GNOME's rules, clashes, presets.

GNOME's keybinding schemas are stand-ins compiled for the test, with a
memory backend, so nothing installed or set on this computer is read.
"""
import json
import os
import shutil
import subprocess

import pytest

gi = pytest.importorskip("gi")
from gi.repository import Gio  # noqa: E402

from deskence import keybindings, presets  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCHEMAS = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="org.gnome.desktop.wm.keybindings" path="/org/gnome/desktop/wm/keybindings/">
    <key name="toggle-above" type="as"><default>[]</default></key>
    <key name="close" type="as"><default>['&lt;Alt&gt;F4']</default>
      <summary>Close window</summary></key>
  </schema>
  <schema id="org.gnome.shell.keybindings" path="/org/gnome/shell/keybindings/">
    <key name="toggle-message-tray" type="as"><default>['&lt;Super&gt;v', '&lt;Super&gt;m']</default>
      <summary>Show the notification list</summary></key>
  </schema>
  <schema id="org.gnome.settings-daemon.plugins.media-keys"
          path="/org/gnome/settings-daemon/plugins/media-keys/">
    <key name="screensaver" type="as"><default>['&lt;Super&gt;l']</default>
      <summary>Lock screen</summary></key>
    <key name="custom-keybindings" type="as"><default>[]</default></key>
  </schema>
  <schema id="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding">
    <key name="binding" type="s"><default>''</default></key>
    <key name="name" type="s"><default>''</default></key>
    <key name="command" type="s"><default>''</default></key>
  </schema>
  <schema id="org.gnome.shell" path="/org/gnome/shell/">
    <key name="favorite-apps" type="as"><default>[]</default></key>
  </schema>
</schemalist>
"""


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    compiler = shutil.which("glib-compile-schemas")
    if compiler is None:
        pytest.skip("glib-compile-schemas is not available")
    directory = tmp_path_factory.mktemp("schemas")
    shutil.copy(os.path.join(ROOT, "data", "schemas", "io.github.deskence.Deskence.gschema.xml"),
                directory)
    (directory / "gnome.gschema.xml").write_text(SCHEMAS)
    subprocess.run([compiler, "--strict", str(directory)], check=True)
    return Gio.SettingsSchemaSource.new_from_directory(str(directory), None, False)


@pytest.fixture
def backend():
    return Gio.memory_settings_backend_new()


def test_one_spelling_for_equal_shortcuts():
    assert keybindings.normalize("<Primary><shift>V") == keybindings.normalize("<Shift><Control>v")
    assert keybindings.normalize("<Ctrl><Alt>Delete") == "<Control><Alt>delete"
    assert keybindings.normalize("<Mod4>Left") == keybindings.normalize("<Super>Left")
    assert keybindings.normalize("Print") == "print"
    for bad in ("", "<Bogus>x", "<Super>", None, 5):
        assert keybindings.normalize(bad) is None


def test_gnome_rules():
    assert keybindings.problem("<Shift><Super>v") is None
    assert keybindings.problem("F9") is None and keybindings.problem("<Super>Print") is None
    assert keybindings.problem("v")                       # a key alone
    assert keybindings.problem("<Shift>v")                # Shift only types a capital
    assert keybindings.problem("<Super>Super_L")          # a modifier alone
    # Global shortcuts must not take what applications use...
    assert keybindings.problem("<Control>c") and keybindings.problem("<Control><Shift>t")
    assert keybindings.problem("<Alt>f")
    # ...but Ctrl and Alt together, or with a non-character key, are fine,
    # and in the settings window Ctrl+F is its own.
    assert keybindings.problem("<Control><Alt>v") is None
    assert keybindings.problem("<Control>F5") is None
    assert keybindings.problem("<Control>f", keybindings.WINDOW) is None


def test_gnome_bindings_are_read(source, backend):
    paths = ["/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/"]
    media = Gio.Settings.new_full(source.lookup("org.gnome.settings-daemon.plugins.media-keys",
                                                True), backend, None)
    media.set_strv("custom-keybindings", paths)
    custom = Gio.Settings.new_full(source.lookup(keybindings.CUSTOM_SCHEMA, True), backend,
                                   paths[0])
    custom.set_string("binding", "<Super>t")
    custom.set_string("name", "Terminal")
    found = {(b.accel, b.label) for b in keybindings.gnome_bindings(source, backend)}
    assert ("<Alt>f4", "Close window") in found
    assert ("<Super>v", "Show the notification list") in found
    assert ("<Super>t", "Terminal") in found


def test_clashes(source, backend):
    gnome = keybindings.gnome_bindings(source, backend)
    current = {"clipboard-history": ["<Shift><Super>v"], "always-on-top": ["<Super>a"]}
    assert keybindings.check("clipboard-history", "<Shift><Super>v", current, gnome) is None
    assert "notification list" in keybindings.check("clipboard-history", "<Super>v",
                                                       current, gnome)
    assert "Always on Top" in keybindings.check("clipboard-history", "<Super>a", current, gnome)
    assert "Lock screen" in keybindings.check("always-on-top", "<super>L", current, gnome)
    # Its own storage is not a clash; nor are local and global shortcuts.
    gnome_with_own = gnome + [keybindings.Binding(keybindings.WM_KEYBINDINGS, "toggle-above",
                                                  "<super>a", "Always on top")]
    assert keybindings.clashes("always-on-top", "<Super>a", current, gnome_with_own) == []
    assert keybindings.clashes("clipboard-history", "<Control>f", current, gnome) == []
    assert keybindings.clashes("search-settings", "<Super>v", current, gnome) == []


def test_preset_with_a_clashing_shortcut_is_not_applied(source, backend, tmp_path):
    store = presets.SettingsStore(source, backend)
    data = presets.parse(json.dumps({
        "format": presets.FORMAT_ID, "version": 1,
        "modules": {"clipboard": {"shortcut": ["<Super>m"], "paste-on-select": False}}}).encode())
    plan = presets.plan_import(data, store, presets.Context(home=str(tmp_path), dirs={}))
    assert [c.key for c in plan.changes] == ["paste-on-select"]
    assert any("<Super>m" in w and "notification list" in w for w in plan.warnings)

    data["modules"]["clipboard"]["shortcut"] = ["<Shift><Super>c"]
    plan = presets.plan_import(data, store, presets.Context(home=str(tmp_path), dirs={}))
    assert "shortcut" in [c.key for c in plan.changes] and not plan.warnings


def test_every_action_is_stored_or_fixed():
    for action in keybindings.actions():
        assert (action.schema and action.key) or action.fixed
        assert action.title() and action.description()
        assert action.scope in (keybindings.GLOBAL, keybindings.WINDOW)
