# SPDX-License-Identifier: GPL-3.0-or-later
import os

import pytest

from deskence import migrations


class FakeSettings:
    def __init__(self, version=0, **strings):
        self.version = version
        self.strings = dict(strings)
        self.dock = None

    def get_uint(self, key):
        assert key == "settings-version"
        return self.version

    def set_uint(self, key, value):
        assert key == "settings-version"
        self.version = value

    def get_child(self, name):
        assert name == "dock"
        return self.dock

    def get_string(self, key):
        return self.strings.get(key, "")

    def set_string(self, key, value):
        self.strings[key] = value

    def get_value(self, key):
        return self.strings.get(key)


def root(version, **dock):
    r = FakeSettings(version)
    r.dock = FakeSettings(**dock)
    return r


def test_fresh_settings_are_migrated():
    s = root(0)
    assert migrations.migrate(s)
    assert s.version == migrations.CURRENT_VERSION


def test_current_settings_untouched():
    s = root(migrations.CURRENT_VERSION)
    assert not migrations.migrate(s)


def test_newer_settings_untouched():
    s = root(migrations.CURRENT_VERSION + 5)
    assert not migrations.migrate(s)
    assert s.version == migrations.CURRENT_VERSION + 5


def test_button_position_is_kept():
    s = root(1, **{"apps-button-position": "start"})
    migrations.migrate(s)
    assert s.dock.get_string("apps-button-position") == "start"


def test_missing_custom_image_falls_back_to_default(tmp_path):
    s = root(1, **{"apps-button-icon": "custom",
                   "apps-button-custom-icon": str(tmp_path / "gone.svg")})
    migrations.migrate(s)
    assert s.dock.get_string("apps-button-icon") == "default"
    assert s.dock.get_string("apps-button-custom-icon") == ""


def test_old_custom_image_is_imported_again_as_square(tmp_path, monkeypatch):
    gi = pytest.importorskip("gi")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    from deskence import appsicon
    monkeypatch.setattr(appsicon, "icon_directory", lambda: str(tmp_path / "data"))
    old = tmp_path / "apps-button-icon-old.webp.png"
    wide = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 40, 20)
    wide.fill(0xff0000ff)
    wide.savev(str(old), "png", [], [])
    s = root(1, **{"apps-button-icon": "custom", "apps-button-custom-icon": str(old)})
    migrations.migrate(s)
    new = s.dock.get_string("apps-button-custom-icon")
    assert new != str(old) and os.path.isfile(new)
    copy = GdkPixbuf.Pixbuf.new_from_file(new)
    assert copy.get_width() == copy.get_height()
    assert s.dock.get_string("apps-button-icon") == "custom"


def test_version_3_keeps_button_and_view_settings():
    values = {"apps-button-position": "end", "length": "full",
              "app-grid-custom-transparency": True, "app-grid-transparency": 40,
              "background-custom-color": True, "background-color": "#ffffff"}
    s = root(2, **values)
    assert migrations.migrate(s)
    assert s.version == migrations.CURRENT_VERSION
    assert s.dock.strings == values


def _dirs(tmp_path, monkeypatch):
    from deskence import appsicon
    old_dir, new_dir = tmp_path / "better-gnome-desktop", tmp_path / "deskence"
    monkeypatch.setattr(appsicon, "legacy_icon_directory", lambda: str(old_dir))
    monkeypatch.setattr(appsicon, "icon_directory", lambda: str(new_dir))
    return old_dir, new_dir


def test_version_4_copies_custom_image_to_the_new_data_folder(tmp_path, monkeypatch):
    old_dir, new_dir = _dirs(tmp_path, monkeypatch)
    old_dir.mkdir()
    old = old_dir / "apps-button-icon-0123456789abcdef.png"
    old.write_bytes(b"png")
    values = {"apps-button-icon": "custom", "apps-button-custom-icon": str(old),
              "position": "left"}
    s = root(3, **values)
    assert migrations.migrate(s)
    new = new_dir / old.name
    assert s.dock.get_string("apps-button-custom-icon") == str(new)
    assert new.read_bytes() == b"png"
    # The former settings still point at the former copy.
    assert old.read_bytes() == b"png"
    assert s.dock.get_string("apps-button-icon") == "custom"
    assert s.dock.get_string("position") == "left"


def test_version_4_keeps_other_or_missing_images(tmp_path, monkeypatch):
    old_dir, new_dir = _dirs(tmp_path, monkeypatch)
    elsewhere = tmp_path / "apps-button-icon-0123456789abcdef.png"
    elsewhere.write_bytes(b"png")
    missing = old_dir / "apps-button-icon-fedcba9876543210.png"
    for path in (str(elsewhere), str(missing), ""):
        s = root(3, **{"apps-button-icon": "custom", "apps-button-custom-icon": path})
        migrations.migrate(s)
        assert s.dock.get_string("apps-button-custom-icon") == path
        assert s.dock.get_string("apps-button-icon") == "custom"
    assert not new_dir.exists()


def test_every_version_has_a_step():
    assert sorted(migrations.STEPS) == list(range(1, migrations.CURRENT_VERSION + 1))
