# SPDX-License-Identifier: GPL-3.0-or-later
import json

from deskence_desktop import clipboard
from deskence_desktop.model import Placement
from deskence_desktop.positions import PositionStore


def test_gnome_copied_files_round_trip():
    data = clipboard.encode_gnome_copied_files(["file:///a", "file:///b%20c"], cut=True)
    assert data == b"cut\nfile:///a\nfile:///b%20c"
    assert clipboard.decode_gnome_copied_files(data) == (True, ["file:///a", "file:///b%20c"])


def test_gnome_copied_files_rejects_garbage():
    assert clipboard.decode_gnome_copied_files(b"\xff\xfe") is None
    assert clipboard.decode_gnome_copied_files(b"move\nfile:///a") is None
    assert clipboard.decode_gnome_copied_files(b"copy\n") is None


def test_uri_list():
    data = clipboard.encode_uri_list(["file:///a", "file:///b"])
    assert clipboard.decode_uri_list(data) == ["file:///a", "file:///b"]
    assert clipboard.decode_uri_list(b"# comment\r\nfile:///x\r\n") == ["file:///x"]


def test_positions_persist_and_rename(tmp_path):
    path = tmp_path / "state" / "positions.json"
    store = PositionStore(str(path))
    store.set("a.txt", Placement("DP-1", 20, 30))
    store.set("mount:file:///run/media/x", Placement("DP-1", 0, 50))
    store.save()
    again = PositionStore(str(path))
    assert again.get("a.txt") == Placement("DP-1", 20, 30)
    again.rename("a.txt", "b.txt")
    assert again.get("b.txt") == Placement("DP-1", 20, 30)
    again.prune({"other"})
    assert again.get("b.txt") is None
    assert again.get("mount:file:///run/media/x") is not None, "drives keep positions"


def test_corrupt_positions_file_is_ignored(tmp_path):
    path = tmp_path / "positions.json"
    path.write_text("{not json")
    assert PositionStore(str(path)).items == {}
    path.write_text(json.dumps({"version": 1, "items": {"a": {"monitor": "X"}}}))
    assert PositionStore(str(path)).items == {}


def test_positions_copied_from_the_old_state_directory(tmp_path, monkeypatch):
    from deskence_desktop import positions

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    old = tmp_path / "better-gnome-desktop" / "icon-positions.json"
    old.parent.mkdir()
    old.write_text('{"version": 3, "items": {"a.txt": {"monitor": "DP-1", "x": 5, "y": 7}}}')
    store = PositionStore()
    assert store.path == str(tmp_path / "deskence" / "icon-positions.json")
    assert store.get("a.txt") == Placement("DP-1", 5, 7)
    # The old file stays for an older version; the new one wins from now on.
    assert old.exists()
    store.set("a.txt", Placement("DP-1", 50, 70))
    store.save()
    old.write_text('{"version": 3, "items": {}}')
    assert not positions.migrate_legacy_file(store.path, str(old))
    assert PositionStore().get("a.txt") == Placement("DP-1", 50, 70)


def test_no_old_positions_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert len(PositionStore()) == 0
    assert not (tmp_path / "deskence").exists()
