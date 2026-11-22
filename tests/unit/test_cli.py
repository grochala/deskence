# SPDX-License-Identifier: GPL-3.0-or-later
"""The command line, run as a separate process in an isolated environment.

Every run has its own home folder and the GSettings keyfile backend inside
it, so the real configuration of the user running the tests is never read
or changed. Without a session bus GNOME Shell is out of reach; with
fake_shell.py on a private bus (when dbus-daemon is installed) the commands
talk to a stand-in of GNOME Shell's extensions interface.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

gi = pytest.importorskip("gi")
from gi.repository import Gio  # noqa: E402

from deskence import cli, control, presets  # noqa: E402
from deskence.features import UUIDS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "src")
HERE = os.path.dirname(os.path.abspath(__file__))

GNOME_SCHEMAS = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="org.gnome.shell" path="/org/gnome/shell/">
    <key name="enabled-extensions" type="as"><default>[]</default></key>
    <key name="disabled-extensions" type="as"><default>[]</default></key>
    <key name="disable-user-extensions" type="b"><default>false</default></key>
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

RUN = ("import sys; sys.path.insert(0, %r); from deskence import cli; "
       "sys.exit(cli.main(sys.argv[1:], '9.9.9', '/nonexistent'))" % SRC)


@pytest.fixture(scope="module")
def schema_dir(tmp_path_factory):
    compiler = shutil.which("glib-compile-schemas")
    if compiler is None:
        pytest.skip("glib-compile-schemas is not available")
    directory = tmp_path_factory.mktemp("schemas")
    shutil.copy(os.path.join(ROOT, "data", "schemas", "io.github.deskence.Deskence.gschema.xml"),
                directory)
    (directory / "gnome.gschema.xml").write_text(GNOME_SCHEMAS)
    subprocess.run([compiler, "--strict", str(directory)], check=True)
    return str(directory)


class Env:
    def __init__(self, tmp_path, schema_dir):
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.vars = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local/share"),
            "XDG_STATE_HOME": str(self.home / ".local/state"),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
            # Our extensions, "installed" with their metadata only.
            "XDG_DATA_DIRS": str(tmp_path / "data"),
            "XDG_RUNTIME_DIR": str(tmp_path / "runtime"),
            "GSETTINGS_SCHEMA_DIR": schema_dir,
            "GSETTINGS_BACKEND": "keyfile",
            "PATH": os.environ.get("PATH", "/usr/bin"),
            "LANG": "C.UTF-8",
        }
        os.makedirs(self.vars["XDG_RUNTIME_DIR"], mode=0o700)
        for uuid in UUIDS.values():
            directory = tmp_path / "data" / "gnome-shell" / "extensions" / uuid
            directory.mkdir(parents=True)
            (directory / "metadata.json").write_text(json.dumps(
                {"uuid": uuid, "version-name": "test"}))

    def run(self, *args, stdin=subprocess.DEVNULL, **extra):
        env = dict(self.vars, **extra)
        return subprocess.run([sys.executable, "-c", RUN, *args], env=env, stdin=stdin,
                              capture_output=True, text=True, timeout=60)

    def gsettings(self, *args):
        result = subprocess.run(["gsettings", *args], env=self.vars, capture_output=True,
                                text=True, check=True)
        return result.stdout.strip()

    def files(self):
        return sorted(str(p.relative_to(self.home)) for p in self.home.rglob("*") if p.is_file())


@pytest.fixture
def env(tmp_path, schema_dir):
    if shutil.which("gsettings") is None:
        pytest.skip("gsettings is not available")
    return Env(tmp_path, schema_dir)


def as_json(result):
    document = json.loads(result.stdout)
    assert document["format"] in (cli.FORMAT_ID, "io.github.deskence.Deskence.diagnostics")
    assert document["version"] == 1
    return document


# --- Command line and help ----------------------------------------------------

def test_commands_go_to_the_command_line_and_the_rest_to_the_window():
    assert cli.handles(["status"]) and cli.handles(["--help"]) and cli.handles(["--version"])
    assert not cli.handles([]) and not cli.handles(["--page", "dock"])
    assert not cli.handles(["--gapplication-service"]) and not cli.handles(["--migrate"])


def test_help_and_version_without_any_session(env):
    result = env.run("--help")
    assert result.returncode == 0 and "status" in result.stdout and "dock" in result.stdout
    assert env.run("--version").stdout.strip() == "deskence 9.9.9"
    for command in ("status", "enable", "reset", "diagnostics"):
        assert env.run(command, "--help").returncode == 0
    assert env.run("preset", "import", "--help").returncode == 0


def test_invalid_command_lines(env):
    for args in (("frobnicate",), ("enable",), ("enable", "nope"), ("disable", "dock", "--all"),
                 ("reset",), ("reset", "bogus"), ("reset", "dock", "--all"), ("preset",),
                 ("status", "--bad-option")):
        result = env.run(*args)
        assert result.returncode == cli.EXIT_USAGE, args
        assert result.stdout == "" and "Traceback" not in result.stderr


def test_no_gtk_is_loaded(env, tmp_path):
    script = (RUN.replace("sys.exit(cli.main(sys.argv[1:], '9.9.9', '/nonexistent'))",
                          "code = cli.main(['status', '--json'], '9.9.9', '/nonexistent'); "
                          "print(sorted(m for m in sys.modules if m.split('.')[-1] in "
                          "('Gtk', 'Gdk', 'Adw')), file=sys.stderr)"))
    environment = dict(env.vars)
    result = subprocess.run([sys.executable, "-c", script], env=environment,
                            capture_output=True, text=True, timeout=60)
    assert result.stderr.strip().splitlines()[-1] == "[]"
    json.loads(result.stdout)


# --- Status and diagnostics ---------------------------------------------------

def test_status_without_gnome_shell(env):
    env.gsettings("set", "org.gnome.shell", "enabled-extensions", "['dock@deskence.github.io']")
    document = as_json(env.run("status", "--json"))
    assert document["command"] == "status"
    assert document["session"]["gnome-shell"] is False
    features = {f["id"]: f for f in document["features"]}
    assert list(features) == ["dock", "desktop-icons", "tray", "app-grid", "clipboard",
                              "keep-awake"]
    # The saved wish is not presented as a running feature.
    assert features["dock"]["enabled"] is True and features["dock"]["running"] is None
    text = env.run("status")
    assert text.returncode == 0 and "not reachable" in text.stdout


def test_diagnostics_contain_no_private_paths_or_values(env):
    secret = str(env.home / "Documents" / "Tajny projekt")
    env.gsettings("set", "io.github.deskence.Deskence.Dock", "folder-stacks",
                  f"['file://{secret}']")
    env.gsettings("set", "io.github.deskence.Deskence.Dock", "apps-button-custom-icon",
                  str(env.home / "obrazek.png"))
    result = env.run("diagnostics", "--json")
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["format"] == "io.github.deskence.Deskence.diagnostics"
    text = result.stdout + env.run("diagnostics").stdout
    assert str(env.home) not in text and "Tajny" not in text and "obrazek" not in text
    assert "io.github.deskence.Deskence.Dock folder-stacks" in report["changed-settings"]


# --- Enabling and disabling ---------------------------------------------------

def test_enable_and_disable_for_the_next_session(env):
    env.gsettings("set", "org.gnome.shell", "enabled-extensions",
                  "['foreign@example.org', 'tray@deskence.github.io']")
    result = env.run("enable", "dock")
    assert result.returncode == cli.EXIT_UNCONFIRMED
    assert "could not be confirmed" in result.stdout
    assert env.run("enable", "dock").returncode == 0                 # idempotent
    result = env.run("disable", "--all", "--json")
    assert result.returncode == cli.EXIT_UNCONFIRMED
    results = {r["id"]: r["result"] for r in as_json(result)["results"]}
    assert results["dock"] == "saved" and results["tray"] == "saved"
    assert results["clipboard"] == "unchanged"
    # Other extensions and the rest of the list stay.
    assert env.gsettings("get", "org.gnome.shell", "enabled-extensions") == \
        "['foreign@example.org']"
    assert env.run("disable", "--all").returncode == 0


def test_a_feature_that_is_not_installed_is_not_enabled(env, tmp_path):
    result = env.run("enable", "dock", XDG_DATA_DIRS=str(tmp_path / "nothing"))
    assert result.returncode == cli.EXIT_FAILED and "not installed" in result.stderr
    assert env.gsettings("get", "org.gnome.shell", "enabled-extensions") == "@as []"


def test_nothing_is_written_without_a_persistent_backend(env):
    before = env.files()
    result = env.run("disable", "--all", GSETTINGS_BACKEND="memory")
    assert result.returncode == cli.EXIT_FAILED
    assert "cannot be saved" in result.stderr
    assert env.files() == before


def test_dconf_without_a_session_bus_is_refused(env):
    result = env.run("enable", "dock", GSETTINGS_BACKEND="dconf")
    assert result.returncode == cli.EXIT_FAILED
    assert "session bus is not available" in result.stderr
    assert not os.path.exists(env.home / ".config" / "dconf")


# --- Restoring defaults -------------------------------------------------------

def test_reset_asks_and_keeps_the_clipboard_history(env):
    dock, clip = "io.github.deskence.Deskence.Dock", "io.github.deskence.Deskence.Clipboard"
    env.gsettings("set", dock, "position", "left")
    env.gsettings("set", dock, "folder-stacks", "['xdg:DOWNLOAD']")
    env.gsettings("set", clip, "remember", "all")
    env.gsettings("set", clip, "max-entries", "150")
    env.gsettings("set", clip, "paste-on-select", "false")
    env.gsettings("set", "org.gnome.desktop.wm.preferences", "button-layout", "close:")
    files = env.files()

    result = env.run("reset", "dock", "--dry-run")
    assert result.returncode == 0 and "position" in result.stdout
    assert env.files() == files and env.gsettings("get", dock, "position") == "'left'"
    # No terminal and no --yes: a readable failure, not a hang.
    result = env.run("reset", "dock")
    assert result.returncode == cli.EXIT_CONFIRM and "--yes" in result.stderr
    assert env.gsettings("get", dock, "position") == "'left'"
    result = env.run("reset", "dock", "--json")
    assert result.returncode == cli.EXIT_CONFIRM and as_json(result)["exit-status"] == 3

    assert env.run("reset", "dock", "clipboard", "--yes").returncode == 0
    assert env.gsettings("get", dock, "position") == "'bottom'"
    assert env.gsettings("get", dock, "folder-stacks") == "['xdg:DOWNLOAD']"  # not the dock's
    assert env.gsettings("get", clip, "paste-on-select") == "true"
    assert env.gsettings("get", clip, "remember") == "'all'"
    assert env.gsettings("get", clip, "max-entries") == "150"

    document = as_json(env.run("reset", "--all", "--yes", "--json"))
    assert document["reset"] is True
    assert env.gsettings("get", dock, "folder-stacks") == "@as []"
    assert env.gsettings("get", clip, "remember") == "'all'"
    # Not a Deskence setting: only "reset windows" restores it.
    assert env.gsettings("get", "org.gnome.desktop.wm.preferences", "button-layout") == "'close:'"
    assert env.run("reset", "--all", "--yes").stdout.startswith("Everything is at its default")


def test_reset_all_turns_off_alphabetical_order(env):
    env.gsettings("set", "io.github.deskence.Deskence.AppGrid", "sort-mode", "alphabetical")
    env.gsettings("set", "org.gnome.shell", "enabled-extensions",
                  "['app-grid@deskence.github.io', 'foreign@example.org']")
    preview = env.run("reset", "--all", "--dry-run").stdout
    assert "app-grid feature" in preview and "your own order" in preview
    assert env.run("reset", "--all", "--yes").returncode == cli.EXIT_UNCONFIRMED
    assert env.gsettings("get", "io.github.deskence.Deskence.AppGrid", "sort-mode") == "'custom'"
    assert env.gsettings("get", "org.gnome.shell", "enabled-extensions") == \
        "['foreign@example.org']"


# --- Presets ------------------------------------------------------------------

def preset_file(path, **dock):
    data = {"format": presets.FORMAT_ID, "version": 1, "name": "Mój pulpit",
            "modules": {"dock": dict({"position": "left"}, **dock)}}
    path.write_text(json.dumps(data))
    return str(path)


def test_preset_import_list_apply_and_undo(env, tmp_path):
    source = preset_file(tmp_path / "moj.json", **{"icon-size": 999})
    files = env.files()
    result = env.run("preset", "import", source, "--apply", "--dry-run")
    assert result.returncode == 0 and "position" in result.stdout
    assert "icon-size has an invalid value" in result.stderr
    assert env.files() == files                                      # --dry-run writes nothing

    assert env.run("preset", "import", source).returncode == 0       # saved, not applied
    assert env.gsettings("get", "io.github.deskence.Deskence.Dock", "position") == "'bottom'"
    listed = as_json(env.run("preset", "list", "--json"))["presets"]
    assert [p["name"] for p in listed] == ["Mój pulpit"]

    # The same name again: refused unless renamed or replaced.
    result = env.run("preset", "import", source)
    assert result.returncode == cli.EXIT_FAILED and "--replace" in result.stderr
    assert env.run("preset", "import", source, "--name", "Drugi").returncode == 0
    assert env.run("preset", "import", source, "--replace").returncode == 0
    names = sorted(p["name"] for p in as_json(env.run("preset", "list", "--json"))["presets"])
    assert names == ["Drugi", "Mój pulpit"]

    assert env.run("preset", "apply", "Mój pulpit").returncode == cli.EXIT_CONFIRM
    result = env.run("preset", "apply", "mój pulpit", "--yes", "--json")
    assert result.returncode == 0 and as_json(result)["applied"] is True
    assert env.gsettings("get", "io.github.deskence.Deskence.Dock", "position") == "'left'"
    assert env.run("preset", "undo", "--yes").returncode == 0
    assert env.gsettings("get", "io.github.deskence.Deskence.Dock", "position") == "'bottom'"
    assert env.run("preset", "undo", "--yes").returncode == cli.EXIT_FAILED
    assert env.run("preset", "apply", "Nie ma").returncode == cli.EXIT_FAILED


def test_undo_keeps_settings_changed_afterwards(env, tmp_path):
    source = preset_file(tmp_path / "p.json", **{"icon-size": 56})
    assert env.run("preset", "import", source, "--apply", "--yes").returncode == 0
    env.gsettings("set", "io.github.deskence.Deskence.Dock", "icon-size", "32")
    result = env.run("preset", "undo", "--dry-run", "--json")
    document = as_json(result)
    assert document["changed-since"] == ["Dock: icon-size"]
    assert env.run("preset", "undo", "--yes").returncode == 0
    assert env.gsettings("get", "io.github.deskence.Deskence.Dock", "position") == "'bottom'"
    assert env.gsettings("get", "io.github.deskence.Deskence.Dock", "icon-size") == "32"


def test_damaged_presets_are_rejected(env, tmp_path):
    bad = tmp_path / "bad.json"
    for content in ('{"format": "other"}', "not json", '{"format": "%s", "version": 99}'
                    % presets.FORMAT_ID):
        bad.write_text(content)
        result = env.run("preset", "import", str(bad))
        assert result.returncode == cli.EXIT_FAILED and "Traceback" not in result.stderr
    assert env.run("preset", "import", str(tmp_path / "missing.json")).returncode == 1
    assert as_json(env.run("preset", "list", "--json"))["presets"] == []


def test_export_never_replaces_a_file_silently(env, tmp_path):
    history = env.home / ".local/share/deskence/clipboard"
    history.mkdir(parents=True)
    (history / "entry-1.txt").write_text("SECRET-CLIPBOARD-TEXT")
    target = tmp_path / "out.json"
    target.write_text("keep me")
    result = env.run("preset", "export", str(target))
    assert result.returncode == cli.EXIT_FAILED and "--force" in result.stderr
    assert target.read_text() == "keep me"
    assert env.run("preset", "export", str(target), "--force", "--pinned").returncode == 0
    exported = json.loads(target.read_text())
    assert exported["format"] == presets.FORMAT_ID and "pinned-apps" in exported
    assert "SECRET-CLIPBOARD-TEXT" not in target.read_text()


# --- With GNOME Shell ---------------------------------------------------------

@pytest.fixture
def shell_env(env, tmp_path):
    daemon = shutil.which("dbus-daemon")
    if daemon is None:
        pytest.skip("dbus-daemon is not available")
    bus = subprocess.Popen([daemon, "--session", "--nofork", "--print-address=1"],
                           stdout=subprocess.PIPE, text=True, env=env.vars)
    address = bus.stdout.readline().strip()
    env.vars["DBUS_SESSION_BUS_ADDRESS"] = address
    shell = subprocess.Popen([sys.executable, os.path.join(HERE, "fake_shell.py")],
                             stdout=subprocess.PIPE, text=True, env=env.vars)
    assert shell.stdout.readline().strip() == "ready"
    yield env
    shell.terminate()
    bus.terminate()
    shell.wait(10)
    bus.wait(10)


def test_with_gnome_shell_changes_are_applied(shell_env):
    env = shell_env
    env.gsettings("set", "org.gnome.shell", "enabled-extensions", "['foreign@example.org']")
    result = env.run("enable", "dock", "tray")
    assert result.returncode == 0, result.stderr
    assert "dock: enabled" in result.stdout
    status = {f["id"]: f for f in as_json(env.run("status", "--json"))["features"]}
    assert status["dock"]["running"] is True and status["clipboard"]["running"] is False
    assert env.run("enable", "dock").stdout.strip() == "dock: already enabled"
    result = env.run("disable", "--all", "--json")
    assert result.returncode == 0
    results = {r["id"]: r["result"] for r in as_json(result)["results"]}
    assert results["dock"] == "applied" and results["keep-awake"] == "unchanged"
    assert env.gsettings("get", "org.gnome.shell", "enabled-extensions") == \
        "['foreign@example.org']"


# --- Shared definitions (in this process) -------------------------------------

@pytest.fixture
def store(schema_dir):
    source = Gio.SettingsSchemaSource.new_from_directory(schema_dir, None, False)
    return presets.SettingsStore(source, Gio.memory_settings_backend_new())


def test_reset_scopes(store):
    dock = {k for _s, k in control.reset_keys(store, "dock")}
    assert "position" in dock and "folder-stacks" not in dock
    assert not any(k.startswith("app-grid-") for k in dock)
    grid = {k for _s, k in control.reset_keys(store, "app-grid")}
    assert grid and all(k.startswith("app-grid-") for k in grid)
    clipboard = {k for _s, k in control.reset_keys(store, "clipboard")}
    assert "paste-on-select" in clipboard and not clipboard & {"remember", "max-entries"}
    everything = set(control.reset_keys(store, "all"))
    assert not everything & presets.RESET_EXCLUDED and not everything & control.KEPT
    assert (presets.DOCK, "folder-stacks") in everything
    assert control.reset_keys(store, "windows")[0] == (presets.WM_PREFERENCES, "button-layout")


def test_reset_plan_lists_only_changed_settings(store):
    assert control.plan_reset(store, "dock", {}).empty
    store.set(presets.DOCK, "position", "left")
    store.set(presets.DOCK, "length", "fit")       # the default, written explicitly
    plan = control.plan_reset(store, "dock", {})
    assert [(k, v) for _s, k, v in plan.changes] == [("position", "left")]
    store.set(presets.APP_GRID, "sort-mode", "alphabetical")
    plan = control.plan_reset(store, "all", {"app-grid": True})
    assert plan.custom_order and plan.disables_sorting
    calls = []

    class Grid:
        def set_mode(self, mode):
            store.set(presets.APP_GRID, "sort-mode", mode)

    control.reset(store, plan, Grid(), lambda module, on: calls.append((module, on)))
    assert store.get(presets.DOCK, "position") == "bottom"
    assert store.get(presets.APP_GRID, "sort-mode") == "custom"
    assert calls == [("app-grid", False)]


def test_storage_is_known():
    kind = control.storage()
    assert kind.backend and isinstance(kind.persistent, bool)

