# SPDX-License-Identifier: GPL-3.0-or-later
import itertools

import pytest

from deskence import preview_geometry as geo

# Widget sizes from a narrow window (sidebar collapsed) to a wide one, and
# monitors of different shapes and interface scales (logical sizes).
WIDGETS = [(120, 150), (200, 150), (312, 150), (600, 150), (1400, 150), (300, 60),
           (330, 240), (560, 240), (900, 240)]
MONITORS = [(1280, 800), (1920, 1080), (1280, 1024), (3440, 1440), (1024, 768), (960, 600)]
POSITIONS = ["bottom", "left", "right"]
LENGTHS = ["fit", "full"]
ICON_SIZES = [24, 32, 48, 64]
APPS_BUTTONS = ["start", "end", None]


def inside_rounded(rect, scr, margin=0.0):
    """rect lies inside the rounded inner area of the screen, at least
    margin pixels from its outline (the border is outside it)."""
    inner, r = scr.inner, scr.inner_radius
    if not inner.inset(margin).contains(rect):
        return False
    for x, y in ((rect.x, rect.y), (rect.right, rect.y),
                 (rect.x, rect.bottom), (rect.right, rect.bottom)):
        cx = min(max(x, inner.x + r), inner.right - r)
        cy = min(max(y, inner.y + r), inner.bottom - r)
        if (x - cx) ** 2 + (y - cy) ** 2 > (r - margin) ** 2 + 1e-9:
            return False
    return True


def screens():
    for (w, h), monitor in itertools.product(WIDGETS, MONITORS):
        yield geo.screen(w, h, monitor)


def test_screen_fits_widget_with_whole_pixels():
    for (w, h), monitor in itertools.product(WIDGETS, MONITORS):
        scr = geo.screen(w, h, monitor)
        assert scr.frame.x >= 0 and scr.frame.y >= 0
        assert scr.frame.right <= w and scr.frame.bottom <= h
        for value in (scr.frame.x, scr.frame.y, scr.frame.w, scr.frame.h):
            assert value == int(value)
        assert scr.frame.contains(scr.inner)
        assert scr.inner.contains(scr.safe)
        assert scr.inner.contains(scr.top_bar)
        assert scr.inner.contains(scr.area)
        assert scr.area.y == scr.top_bar.bottom


def test_safe_area_is_inside_rounded_inner_area():
    for scr in screens():
        assert inside_rounded(scr.safe, scr)


@pytest.mark.parametrize("position,length,icon_size,apps_button", list(itertools.product(
    POSITIONS, LENGTHS, ICON_SIZES, APPS_BUTTONS)))
def test_dock_stays_inside_the_screen(position, length, icon_size, apps_button):
    for scr in screens():
        dock = geo.dock(scr, position, length, icon_size, apps_button)
        assert scr.area.contains(dock.box), (scr, dock.box)
        apps = [item for item in dock.items if not item.apps_button]
        assert geo.MIN_DOCK_APPS <= len(apps) <= 5
        assert sum(item.apps_button for item in dock.items) == (1 if apps_button else 0)
        for item in dock.items:
            # Items: inside the dock, away from the rounded corners.
            assert dock.box.contains(item.rect)
            assert inside_rounded(item.rect, scr), (scr, item.rect)
            if item.indicator:
                assert dock.box.contains(item.indicator)
                assert not item.indicator.overlaps(item.rect)
        rects = [item.rect for item in dock.items]
        for a, b in itertools.combinations(rects, 2):
            assert not a.overlaps(b)


@pytest.mark.parametrize("length", LENGTHS)
def test_dock_edge_and_gap(length):
    scr = geo.screen(600, 150)
    bottom = geo.dock(scr, "bottom", length, 48)
    left = geo.dock(scr, "left", length, 48)
    right = geo.dock(scr, "right", length, 48)
    if length == "full":
        assert bottom.box.bottom == scr.area.bottom
        assert bottom.box.x == scr.inner.x and bottom.box.right == scr.inner.right
        assert left.box.x == scr.area.x
        assert left.box.y == scr.area.y and left.box.bottom == scr.area.bottom
        assert right.box.right == scr.area.right
        assert bottom.radius == 0
    else:
        assert bottom.box.bottom < scr.area.bottom
        assert left.box.x > scr.area.x
        assert right.box.right < scr.area.right
        # Centered along its edge.
        assert abs((bottom.box.x - scr.area.x) - (scr.area.right - bottom.box.right)) < 1e-6
        assert bottom.radius > 0


def test_dock_is_an_illustration_with_true_relative_sizes():
    # Icons are drawn at the illustration scale, the same on every monitor,
    # and keep their sizes relative to each other.
    for monitor in MONITORS:
        scr = geo.screen(560, 240, monitor)
        for position in POSITIONS:
            small = geo.dock(scr, position, "fit", 32)
            large = geo.dock(scr, position, "fit", 64)
            assert large.items[0].rect.w == pytest.approx(64 * scr.scale)
            assert large.items[0].rect.w == pytest.approx(2 * small.items[0].rect.w)


def test_dock_icons_are_readable():
    # Much larger than a faithful miniature: a 48 px icon on a 1920 px
    # wide monitor is at least 20 preview pixels in the usual widget.
    scr = geo.screen(560, 240, (1920, 1080))
    dock = geo.dock(scr, "bottom", "fit", 48)
    assert dock.items[0].rect.w >= 20
    assert dock.items[0].rect.w > 2 * 48 * scr.inner.w / 1920


def test_fewer_items_before_smaller_items():
    # A side dock with large icons shows fewer applications at full size.
    scr = geo.screen(560, 240)
    dock = geo.dock(scr, "left", "fit", 64)
    apps = [item for item in dock.items if not item.apps_button]
    assert len(apps) < 5
    assert dock.items[0].rect.w == pytest.approx(64 * scr.scale)


def test_indicators_side():
    scr = geo.screen(600, 150)
    for position in POSITIONS:
        dock = geo.dock(scr, position, "fit", 48, "end")
        running = [item for item in dock.items if item.indicator]
        assert len(running) == 3
        for item in running:
            dot, icon = item.indicator, item.rect
            if position == "bottom":
                assert dot.y >= icon.bottom
            elif position == "left":
                assert dot.x >= icon.right
            else:
                assert dot.right <= icon.x
        assert not any(item.indicator for item in dock.items if item.apps_button)


@pytest.mark.parametrize("apps_button", ["start", "end"])
def test_full_dock_apps_button_at_its_end(apps_button):
    scr = geo.screen(600, 150)
    dock = geo.dock(scr, "bottom", "full", 48, apps_button)
    apps = next(item for item in dock.items if item.apps_button)
    others = [item for item in dock.items if not item.apps_button]
    if apps_button == "start":
        assert all(apps.rect.x < item.rect.x for item in others)
    else:
        assert all(apps.rect.x > item.rect.x for item in others)
        # Free room between the list and the button.
        assert apps.rect.x - others[-1].rect.right > apps.rect.w


@pytest.mark.parametrize("size,corner", list(itertools.product(
    ["small", "medium", "large", "huge"],
    ["top-left", "top-right", "bottom-left", "bottom-right"])))
def test_desktop_icons_inside_and_beside_the_dock(size, corner):
    for scr in screens():
        for position, length in itertools.product(POSITIONS + [None], LENGTHS):
            dock = geo.dock(scr, position, length, 48) if position else None
            cells, icon = geo.desktop_icons(scr, size, corner, dock)
            assert min(5, geo.MIN_DESKTOP_ICONS) <= len(cells) <= 5
            for cell in cells:
                assert inside_rounded(cell, scr), (scr, cell)
                assert scr.area.contains(cell)
                assert icon <= cell.w and icon <= cell.h
                if dock is not None:
                    assert not cell.overlaps(dock.box)
            for a, b in itertools.combinations(cells, 2):
                assert not a.overlaps(b)


def test_desktop_icons_start_at_their_corner():
    scr = geo.screen(600, 150)
    area = geo.icons_area(scr)
    cells, _ = geo.desktop_icons(scr, "medium", "bottom-right")
    assert max(c.right for c in cells) == pytest.approx(area.right - geo.GRID_MARGIN * scr.scale)
    assert max(c.bottom for c in cells) == pytest.approx(area.bottom - geo.GRID_MARGIN * scr.scale)
