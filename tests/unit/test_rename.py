# SPDX-License-Identifier: GPL-3.0-or-later
"""Taking over Better GNOME Desktop: settings, extensions, application ID.

The settings tests use real GSettings with a memory backend and both
schemas, the new one and the copy under the former ID that the build
generates (data/schemas/make-legacy-schema.py).
"""
import os
import shutil
import subprocess
import sys

import pytest

gi = pytest.importorskip("gi")
from gi.repository import Gio, GLib  # noqa: E402

from deskence import rename  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMAS = os.path.join(ROOT, "data", "schemas")


@pytest.fixture(scope="module")
def schema_dir(tmp_path_factory):
    compiler = shutil.which("glib-compile-schemas")
    if compiler is None:
        pytest.skip("glib-compile-schemas is not available")
    directory = tmp_path_factory.mktemp("schemas")
    source = os.path.join(SCHEMAS, "io.github.deskence.Deskence.gschema.xml")
    shutil.copy(source, directory)
    subprocess.run([sys.executable, os.path.join(SCHEMAS, "make-legacy-schema.py"), source,
                    str(directory / "io.github.bettergnome.Desktop.gschema.xml")], check=True)
    subprocess.run([compiler, "--strict", str(directory)], check=True)
    return str(directory)


@pytest.fixture
def settings(schema_dir):
    source = Gio.SettingsSchemaSource.new_from_directory(schema_dir, None, False)
    backend = Gio.memory_settings_backend_new()
    current = Gio.Settings.new_full(source.lookup(rename.SCHEMA, False), backend, None)
    legacy = Gio.Settings.new_full(source.lookup(rename.LEGACY_SCHEMA, False), backend, None)
    return legacy, current


def test_legacy_schema_has_the_former_id_and_path(settings):
    legacy, current = settings
    assert legacy.props.path == "/io/github/bettergnome/desktop/"
    assert current.props.path == "/io/github/deskence/deskence/"
    assert legacy.get_child("dock").props.path == "/io/github/bettergnome/desktop/dock/"


def test_settings_are_taken_over(settings):
    legacy, current = settings
    legacy.set_uint("settings-version", 3)
    legacy.get_child("dock").set_string("position", "left")
    legacy.get_child("dock").set_int("icon-size", 32)
    legacy.get_child("dock").set_boolean("magnify", True)
    legacy.get_child("desktop-icons").set_string("start-corner", "bottom-right")
    legacy.get_child("windows").set_string("original-button-layout", "appmenu:close")
    assert rename.copy_settings(legacy, current)
    assert current.get_uint("settings-version") == 3
    assert current.get_child("dock").get_string("position") == "left"
    assert current.get_child("dock").get_int("icon-size") == 32
    assert current.get_child("dock").get_boolean("magnify")
    assert current.get_child("desktop-icons").get_string("start-corner") == "bottom-right"
    assert current.get_child("windows").get_string("original-button-layout") == "appmenu:close"
    # Defaults stay defaults (no user value written).
    assert current.get_child("dock").get_user_value("hide-mode") is None
    assert current.get_boolean(rename.MIGRATED_KEY)
    # The former settings are kept.
    assert legacy.get_child("dock").get_string("position") == "left"


def test_newer_deskence_settings_win(settings):
    legacy, current = settings
    legacy.get_child("dock").set_string("position", "left")
    legacy.get_child("dock").set_string("length", "full")
    current.get_child("dock").set_string("position", "right")
    assert rename.copy_settings(legacy, current)
    assert current.get_child("dock").get_string("position") == "right"
    assert current.get_child("dock").get_string("length") == "full"


def test_taken_over_only_once(settings):
    legacy, current = settings
    legacy.get_child("dock").set_string("position", "left")
    assert rename.copy_settings(legacy, current)
    # Changed in Deskence afterwards, then the migration runs again (next
    # login): nothing is brought back.
    current.get_child("dock").reset("position")
    assert not rename.copy_settings(legacy, current)
    assert current.get_child("dock").get_string("position") == "bottom"


def test_nothing_to_take_over(settings):
    legacy, current = settings
    assert rename.copy_settings(legacy, current)
    assert current.get_child("dock").get_user_value("position") is None


def test_missing_legacy_schema(tmp_path):
    assert rename.legacy_settings(str(tmp_path)) is None
    assert rename.legacy_settings("") is None


def test_legacy_settings_from_compiled_directory(schema_dir):
    legacy = rename.legacy_settings(schema_dir, Gio.memory_settings_backend_new())
    assert legacy is not None
    assert legacy.props.schema_id == rename.LEGACY_SCHEMA


# --- Extensions

OLD_DOCK, NEW_DOCK = "dock@bettergnome.github.io", "dock@deskence.github.io"
OLD_TRAY, NEW_TRAY = "tray@bettergnome.github.io", "tray@deskence.github.io"


def test_former_uuids_replaced_in_place():
    enabled = ["a@x", OLD_DOCK, "b@x", OLD_TRAY]
    assert rename.migrate_enabled_extensions(enabled, lambda u: True) == \
        ["a@x", NEW_DOCK, "b@x", NEW_TRAY]


def test_running_former_extension_kept_until_next_login():
    states = {OLD_DOCK: rename.STATE_ACTIVE, OLD_TRAY: 2}
    result = rename.migrate_enabled_extensions([OLD_DOCK, OLD_TRAY],
                                               rename.legacy_removable(states))
    assert result == [NEW_DOCK, OLD_DOCK, NEW_TRAY]
    # Next login: the former one is gone, the new one known.
    states = {NEW_DOCK: rename.STATE_ACTIVE}
    assert rename.migrate_enabled_extensions(result, rename.legacy_removable(states)) == \
        [NEW_DOCK, NEW_TRAY]


def test_former_extension_running_next_to_known_new_one_is_dropped():
    states = {OLD_DOCK: rename.STATE_ACTIVE, NEW_DOCK: rename.STATE_ACTIVE}
    assert rename.migrate_enabled_extensions([OLD_DOCK, NEW_DOCK],
                                             rename.legacy_removable(states)) == [NEW_DOCK]


def test_no_shell_means_nothing_runs():
    assert rename.legacy_removable(None)(OLD_DOCK)


class FakeSchema:
    def __init__(self, keys):
        self.keys = keys

    def has_key(self, key):
        return key in self.keys


class FakeSettings:
    def __init__(self, **values):
        self.values = values
        self.props = type("Props", (), {"settings_schema": FakeSchema(values)})()

    def get_strv(self, key):
        return list(self.values[key])

    def set_strv(self, key, value):
        self.values[key] = list(value)

    def get_value(self, key):
        return self.values[key]

    def set_value(self, key, value):
        self.values[key] = value


def test_shell_extensions_migration_is_idempotent():
    shell = FakeSettings(**{"enabled-extensions": ["a@x", OLD_DOCK],
                            "disabled-extensions": [NEW_DOCK, "c@x"]})
    assert rename.migrate_shell_extensions(shell, {})
    assert shell.values["enabled-extensions"] == ["a@x", NEW_DOCK]
    assert shell.values["disabled-extensions"] == ["c@x"]
    assert not rename.migrate_shell_extensions(shell, {})


# --- Application ID

OLD_ID, NEW_ID = "io.github.bettergnome.Desktop.desktop", "io.github.deskence.Deskence.desktop"


def test_favorites_keep_their_order():
    assert rename.replace_desktop_id(["a.desktop", OLD_ID, "b.desktop"]) == \
        ["a.desktop", NEW_ID, "b.desktop"]
    assert rename.replace_desktop_id([OLD_ID, NEW_ID]) == [NEW_ID]


def test_grid_layout_keeps_the_position():
    layout = GLib.Variant("aa{sv}", [
        {"a.desktop": GLib.Variant("a{sv}", {"position": GLib.Variant("i", 0)}),
         OLD_ID: GLib.Variant("a{sv}", {"position": GLib.Variant("i", 1)})}])
    result = rename.replace_in_layout(layout).unpack()
    assert result == [{"a.desktop": {"position": 0}, NEW_ID: {"position": 1}}]
    assert rename.replace_in_layout(GLib.Variant("aa{sv}", [{}])) is None


def test_application_id_everywhere():
    layout = GLib.Variant("aa{sv}", [{OLD_ID: GLib.Variant("a{sv}", {})}])
    shell = FakeSettings(**{"favorite-apps": ["x.desktop", OLD_ID], "app-picker-layout": layout})
    folders = FakeSettings(**{"folder-children": ["Utilities"]})
    utilities = FakeSettings(apps=[OLD_ID, "y.desktop"])
    assert rename.migrate_app_id(shell, folders, lambda name: utilities)
    assert shell.values["favorite-apps"] == ["x.desktop", NEW_ID]
    assert NEW_ID in shell.values["app-picker-layout"].unpack()[0]
    assert utilities.values["apps"] == [NEW_ID, "y.desktop"]
    assert not rename.migrate_app_id(shell, folders, lambda name: utilities)
