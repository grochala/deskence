# SPDX-License-Identifier: GPL-3.0-or-later
import os

import pytest

gi = pytest.importorskip("gi")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

from deskence import appsicon  # noqa: E402


def write_png(path, size=8):
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, size, size)
    pixbuf.fill(0x3584e4ff)
    pixbuf.savev(str(path), "png", [], [])


def test_import_copies_into_data_folder(tmp_path):
    source = tmp_path / "logo.png"
    write_png(source)
    data = tmp_path / "data"
    copy = appsicon.import_icon(str(source), str(data))
    assert os.path.dirname(copy) == str(data)
    assert copy.endswith(".png")
    source.unlink()
    assert os.path.isfile(copy), "the copy survives deleting the original"


def test_copy_is_a_square_with_preserved_proportions(tmp_path):
    source = tmp_path / "wide.png"
    wide = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 80, 40)
    wide.fill(0xe01b24ff)
    wide.savev(str(source), "png", [], [])
    copy = GdkPixbuf.Pixbuf.new_from_file(appsicon.import_icon(str(source), str(tmp_path / "d")))
    assert (copy.get_width(), copy.get_height()) == (80, 80)
    pixels = copy.get_pixels()
    stride, channels = copy.get_rowstride(), copy.get_n_channels()
    alpha = lambda x, y: pixels[y * stride + x * channels + 3]  # noqa: E731
    assert alpha(40, 5) == 0, "transparent margin above"
    assert alpha(40, 40) == 255, "image in the middle"


def test_large_image_is_shrunk(tmp_path):
    source = tmp_path / "big.png"
    write_png(source, 600)
    copy = GdkPixbuf.Pixbuf.new_from_file(appsicon.import_icon(str(source), str(tmp_path / "d")))
    assert copy.get_width() == appsicon.SIDE


def test_svg_is_rendered(tmp_path):
    source = tmp_path / "logo.svg"
    source.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10">'
                      '<rect width="20" height="10" fill="#3584e4"/></svg>')
    try:
        path = appsicon.import_icon(str(source), str(tmp_path / "d"))
    except appsicon.InvalidIcon:
        pytest.skip("no SVG loader for GdkPixbuf installed")
    copy = GdkPixbuf.Pixbuf.new_from_file(path)
    assert copy.get_width() == copy.get_height() == appsicon.SIDE


def test_new_image_gets_new_name_and_replaces_old_copy(tmp_path):
    data = tmp_path / "data"
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    write_png(a, 8)
    write_png(b, 16)
    first = appsicon.import_icon(str(a), str(data))
    second = appsicon.import_icon(str(b), str(data))
    assert first != second
    assert not os.path.exists(first)
    assert os.listdir(data) == [os.path.basename(second)]


def test_invalid_files_are_refused_without_touching_existing_copy(tmp_path):
    data = tmp_path / "data"
    good = tmp_path / "good.png"
    write_png(good)
    kept = appsicon.import_icon(str(good), str(data))
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"\x89PNG\r\n\x1a\nnot really")
    with pytest.raises(appsicon.InvalidIcon):
        appsicon.import_icon(str(bad), str(data))
    text = tmp_path / "notes.txt"
    text.write_text("hello")
    with pytest.raises(appsicon.InvalidIcon):
        appsicon.import_icon(str(text), str(data))
    with pytest.raises(appsicon.InvalidIcon):
        appsicon.import_icon(str(tmp_path / "missing.png"), str(data))
    assert os.path.isfile(kept)


def test_too_large_file_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(appsicon, "MAX_BYTES", 10)
    source = tmp_path / "logo.png"
    write_png(source)
    with pytest.raises(appsicon.InvalidIcon):
        appsicon.import_icon(str(source), str(tmp_path / "data"))


def test_distribution_logo_names():
    fedora = appsicon.distribution_logo_names({"LOGO": "fedora-logo-icon", "ID": "fedora"})
    assert fedora[0] == "fedora-logo-icon"
    assert len(fedora) == len(set(fedora)), "no duplicates"
    debian = appsicon.distribution_logo_names({"LOGO": None, "ID": "debian"})
    assert "emblem-debian" in debian
    assert debian[-1] == "distributor-logo"
    assert appsicon.distribution_logo_names({"ID": "../etc"}) == ["distributor-logo"]
