# SPDX-License-Identifier: GPL-3.0-or-later
"""The report for bug reports: only the listed fields, nothing private,
missing values marked as unavailable."""
import os
import shutil
import subprocess

import pytest

gi = pytest.importorskip("gi")
from gi.repository import Gio, GLib  # noqa: E402

from deskence import diagnostics, presets  # noqa: E402
from deskence.shell import FeatureStatus  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


HOST = "ws-anna-42"


class Shell:
    """A ShellExtensions with GNOME Shell not reachable."""
    bus_available = False
    shell_available = False
    shell_version = None

    def extensions_globally_disabled(self):
        return False

    def status(self, uuid):
        return FeatureStatus(FeatureStatus.ERROR,
                             f"TypeError in {GLib.get_home_dir()}/.local/share/x.js "
                             f"on {HOST}")

    def info(self, uuid):
        return None

    def is_enabled(self, uuid):
        return uuid.startswith("dock")

    def conflicts(self, feature):
        return []


@pytest.fixture
def store(tmp_path_factory):
    compiler = shutil.which("glib-compile-schemas")
    if compiler is None:
        pytest.skip("glib-compile-schemas is not available")
    directory = tmp_path_factory.mktemp("schemas")
    shutil.copy(os.path.join(ROOT, "data", "schemas", "io.github.deskence.Deskence.gschema.xml"),
                directory)
    subprocess.run([compiler, "--strict", str(directory)], check=True)
    source = Gio.SettingsSchemaSource.new_from_directory(str(directory), None, False)
    return presets.SettingsStore(source, Gio.memory_settings_backend_new())


def test_scrub_hides_home_user_and_host():
    words = diagnostics._private_words()
    text = f"{GLib.get_home_dir()}/Dokumenty/umowa.odt by {GLib.get_user_name()}"
    scrubbed = diagnostics.scrub(text, words)
    assert GLib.get_home_dir() not in scrubbed and GLib.get_user_name() not in scrubbed
    assert scrubbed.startswith("~/")
    assert diagnostics.scrub(None) is None


def test_report_contains_no_private_data(store, monkeypatch):
    secret = os.path.join(GLib.get_home_dir(), "Tajne", "projekt")
    store.set(presets.DOCK, "folder-stacks", [GLib.filename_to_uri(secret, None)])
    store.set(presets.DOCK, "apps-button-custom-icon", secret + ".png")
    monkeypatch.setattr(diagnostics, "_monitors", lambda: None)
    # A host name that cannot also be a distribution or a word of the report.
    words = diagnostics._private_words()
    monkeypatch.setattr(diagnostics, "_private_words", lambda: [HOST, *words])
    report = diagnostics.collect("1.2.3", Shell(), store)
    text = diagnostics.to_text(report) + repr(report)
    for private in (GLib.get_home_dir(), GLib.get_user_name(), HOST, "Tajne"):
        assert private not in text, private
    assert "io.github.deskence.Deskence.Dock folder-stacks" in report["changed-settings"]
    assert report["features"][0]["error"].startswith("TypeError in ~/")


def test_missing_values_are_unavailable(store, monkeypatch):
    monkeypatch.setattr(diagnostics, "_monitors", lambda: None)
    monkeypatch.setattr(diagnostics, "_os_release", lambda: None)
    text = diagnostics.to_text(diagnostics.collect("1.2.3", Shell(), store))
    assert "- Distribution: unavailable" in text
    assert "- Monitors: unavailable" in text
    assert "- GNOME Shell: unavailable (not reachable)" in text
    assert "GTK unavailable" in text
    assert text.startswith("### Deskence diagnostics")


def test_monitors_are_listed_without_identity(store, monkeypatch):
    monkeypatch.setattr(diagnostics, "_monitors", lambda: [
        {"width": 2560, "height": 1440, "refresh": 60.0, "scale": 1.25, "primary": True},
        {"width": None, "height": None, "refresh": None, "scale": None, "primary": False}])
    text = diagnostics.to_text(diagnostics.collect("1.2.3", Shell(), store,
                                                   {"gtk": "4.24.1", "libadwaita": "1.10.0"}))
    assert "- Monitors: 2" in text and "2560×1440 at 60.0 Hz, scale 1.25, primary" in text
    assert "  - 2: unavailable, scale unavailable" in text
    assert "GTK 4.24.1" in text and "libadwaita 1.10.0" in text


def test_os_release_fields_are_listed_only(tmp_path):
    release = tmp_path / "os-release"
    release.write_text('NAME="Fedora Linux"\nVERSION_ID=45\nHOME_URL="https://x"\n'
                       'BUILD_ID=secret\n')
    assert diagnostics._os_release((str(release),)) == {"name": "Fedora Linux",
                                                         "version-id": "45"}
    assert diagnostics._os_release((str(tmp_path / "missing"),)) is None
