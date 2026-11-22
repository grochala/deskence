# SPDX-License-Identifier: GPL-3.0-or-later
from deskence_desktop import model
from deskence_desktop.model import CellSize, Grid, Placement, SortInfo, Surface


def grid(c="A", cols=3, rows=2):
    return Grid(c, cols, rows)


CELL = CellSize(100, 100)


def surface(c="A", width=316, height=216):
    """3 x 2 cells of 100 px, with 8 px margins."""
    return Surface(c, width, height, CELL)


def test_fill_order_top_left_is_column_major():
    assert list(grid().cells_from("top-left")) == [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)]


def test_fill_order_bottom_right():
    assert list(grid().cells_from("bottom-right"))[:3] == [(2, 1), (2, 0), (1, 1)]


def test_surface_grid_geometry():
    s = surface()
    assert (s.grid.columns, s.grid.rows) == (3, 2)
    assert s.origin(0, 0) == (8, 8)
    assert s.origin(2, 1) == (208, 108)
    assert s.nearest_cell(150, 60) == (1, 1)
    assert s.nearest_cell(130, 20) == (1, 0)


def test_saved_positions_are_kept_and_new_items_fill_free_cells():
    saved = {"a": Placement("A", 8, 8)}
    result = model.layout(["a", "b"], saved, {"A": surface()}, "A", "top-left")
    assert result.placements["a"] == Placement("A", 8, 8)
    assert result.placements["b"] == Placement("A", 8, 108)
    assert list(result.to_save) == ["b"]


def test_free_position_is_kept_exactly():
    saved = {"a": Placement("A", 57, 33)}
    result = model.layout(["a"], saved, {"A": surface()}, "A", "top-left")
    assert result.placements["a"] == Placement("A", 57, 33)
    assert result.to_save == {}


def test_free_icon_blocks_the_cells_it_covers():
    # "a" sits between cells (0, 0) and (1, 0); "b" must not land on it.
    saved = {"a": Placement("A", 50, 8)}
    result = model.layout(["a", "b"], saved, {"A": surface()}, "A", "top-left")
    b = result.placements["b"]
    assert not surface().collides((50, 8), (b.x, b.y))


def test_icon_from_missing_monitor_is_moved_but_not_saved():
    saved = {"a": Placement("GONE", 108, 108)}
    result = model.layout(["a"], saved, {"A": surface()}, "A", "top-left")
    assert result.placements["a"].connector == "A"
    assert result.to_save == {}


def test_out_of_bounds_after_resolution_change_is_pulled_back_not_saved():
    saved = {"a": Placement("A", 900, 700)}
    result = model.layout(["a"], saved, {"A": surface()}, "A", "top-left")
    p = result.placements["a"]
    assert (p.x, p.y) == (216, 116), "clamped to the area edge, exactly"
    assert result.to_save == {}, "the remembered position returns with the resolution"


def test_collision_moves_second_item_to_nearest_free_cell():
    saved = {"a": Placement("A", 208, 108), "b": Placement("A", 210, 110)}
    result = model.layout(["a", "b"], saved, {"A": surface()}, "A", "top-left")
    assert result.placements["a"] == Placement("A", 208, 108)
    assert result.placements["b"] in (Placement("A", 208, 8), Placement("A", 108, 108))
    assert result.to_save == {}


def test_overflow_to_second_monitor():
    surfaces = {"A": surface("A", 116, 116), "B": surface("B", 116, 116)}
    result = model.layout(["a", "b"], {}, surfaces, "A", "top-left")
    assert {p.connector for p in result.placements.values()} == {"A", "B"}


def test_everything_full_stacks_instead_of_dropping():
    result = model.layout(["a", "b", "c"], {}, {"A": surface("A", 116, 116)}, "A", "top-left")
    assert len(result.placements) == 3


def test_place_dropped_free_keeps_exact_position_and_relative_offsets():
    slots = model.place_dropped(["a", "b"], (37, 12), {"a": (0, 0), "b": (60, 90)},
                                surface("A", 1000, 800), [], snap=False)
    assert slots == {"a": (37, 12), "b": (97, 102)}


def test_place_dropped_moves_group_inside_area_as_a_whole():
    # Dropped too far right: both move left by the same amount.
    s = surface("A", 1000, 800)
    slots = model.place_dropped(["a", "b"], (880, 10), {"a": (0, 0), "b": (50, 0)}, s, [],
                                snap=False)
    assert slots["b"][0] == 900
    assert slots["b"][0] - slots["a"][0] == 50


def test_place_dropped_snaps_to_grid():
    s = surface()
    slots = model.place_dropped(["a"], (120, 15), {}, s, [], snap=True)
    assert slots == {"a": (108, 8)}


def test_place_dropped_on_occupied_cell_is_not_refused():
    s = surface()
    slots = model.place_dropped(["a"], (8, 8), {}, s, [(8, 8)], snap=True)
    assert slots["a"] != (8, 8)
    assert slots["a"] in ((8, 108), (108, 8))


def test_place_dropped_free_next_to_another_icon_is_allowed():
    s = surface("A", 1000, 800)
    slots = model.place_dropped(["a"], (60, 8), {}, s, [(8, 8)], snap=False)
    assert slots == {"a": (60, 8)}, "half a cell apart is not a collision"


def test_place_dropped_keeps_grid_offsets_when_snapping():
    s = surface("A", 1000, 800)
    slots = model.place_dropped(["a", "b"], (110, 10), {"a": (0, 0), "b": (0, 100)}, s, [],
                                snap=True)
    assert slots["b"][1] - slots["a"][1] == 100


def test_align_to_grid_moves_to_nearest_free_cells():
    s = surface()
    slots = {"a": (20, 15), "b": (25, 20), "c": (208, 108)}
    aligned = model.align_to_grid(slots, s)
    assert aligned["c"] == (208, 108)
    assert aligned["a"] == (8, 8)
    assert aligned["b"] != (8, 8)
    assert len(set(aligned.values())) == 3


def test_only_the_dock_is_excluded_not_its_band():
    # 6 x 3 cells; a short dock covers the middle of the bottom row.
    s = Surface("A", 616, 316, CELL, exclusions=[(208, 220, 200, 96)])
    blocked = s.blocked_cells()
    assert blocked == {(2, 2), (3, 2)}
    assert (0, 2) not in blocked and (5, 2) not in blocked, "beside the dock stays usable"


def test_icons_are_kept_off_the_dock():
    s = Surface("A", 616, 316, CELL, exclusions=[(208, 220, 200, 96)])
    saved = {"a": Placement("A", 300, 200)}
    result = model.layout(["a"], saved, {"A": s}, "A", "top-left")
    p = result.placements["a"]
    assert not s.blocked((p.x, p.y))
    assert result.to_save == {}, "the wish is remembered for when the dock goes"
    slots = model.place_dropped(["b"], (300, 210), {}, s, [], snap=False)
    assert not s.blocked(slots["b"])
    slots = model.place_dropped(["b"], (450, 205), {}, s, [], snap=False)
    assert slots["b"] == (450, 205), "beside the dock: exact position kept"


def test_new_icons_fill_cells_beside_the_dock():
    s = Surface("A", 616, 316, CELL, exclusions=[(208, 220, 200, 96)])
    result = model.layout([str(i) for i in range(16)], {}, {"A": s}, "A", "top-left")
    used = {(p.x, p.y) for p in result.placements.values()}
    assert s.origin(0, 2) in used and s.origin(5, 2) in used
    assert s.origin(2, 2) not in used and s.origin(3, 2) not in used


def test_moving_the_dock_keeps_icons_that_still_fit():
    """Dock moved from the bottom to the left: positions are monitor pixels,
    so icons stay; only one under the new dock moves, and only for now."""
    cell = CellSize(100, 120)
    bottom = Surface("A", 1280, 768, cell, exclusions=[(373, 718, 533, 82)], x=0, y=32)
    left = Surface("A", 1280, 768, cell, exclusions=[(0, 200, 80, 400)], x=0, y=32)
    saved = {"right": Placement("A", 1172, 40), "middle": Placement("A", 600, 300),
             "under-left-dock": Placement("A", 10, 300)}
    for surface in (bottom, left, bottom, left):
        result = model.layout(list(saved), saved, {"A": surface}, "A", "top-left")
        assert result.placements["right"] == Placement("A", 1172, 40)
        assert result.placements["middle"] == Placement("A", 600, 300)
        assert result.to_save == {}, "nothing drifts by being re-saved"
    moved = model.layout(list(saved), saved, {"A": left}, "A", "top-left").placements
    assert not left.blocked((moved["under-left-dock"].x, moved["under-left-dock"].y))


def test_icons_stay_inside_their_monitor():
    s = Surface("A", 1024, 736, CellSize(100, 120), x=0, y=32)
    for x, y in ((5000, 40), (-300, 40), (500, -50), (500, 5000)):
        p = model.layout(["a"], {"a": Placement("A", x, y)}, {"A": s}, "A", "top-left") \
            .placements["a"]
        assert 0 <= p.x and p.x + 100 <= 1024
        assert 32 <= p.y and p.y + 120 <= 768


def test_area_offset_is_counted_once():
    s = Surface("A", 1200, 768, CellSize(100, 100), x=80, y=32)
    assert s.origin(0, 0)[0] >= 80
    assert s.cell_at(*s.origin(3, 2)) == (3, 2)
    assert s.nearest_cell(*s.origin(4, 1)) == (4, 1)
    assert model.slot_for_point(*s.origin(2, 2), s, 64, snap=True) == s.origin(2, 2)
    slots = model.place_dropped(["a"], (2000, 40), {}, s, [], snap=False)
    assert slots["a"][0] == 80 + 1200 - 100


def test_slot_for_point():
    s = surface("A", 1000, 800)
    assert model.slot_for_point(500, 400, s, 64, snap=False) == (450, 364)
    x, y = model.slot_for_point(500, 400, s, 64, snap=True)
    assert (x, y) == s.origin(*s.cell_at(500, 400))


def info(i, name, is_dir=False, modified=0, size=0, ctype="text/plain", rank=-1):
    return SortInfo(i, name, name.lower(), is_dir, modified, size, ctype, rank)


def test_sort_specials_then_folders_then_name():
    items = [info("f", "b.txt"), info("d", "zeta", is_dir=True), info("t", "Trash", rank=1),
             info("h", "Home", rank=0), info("g", "a.txt")]
    assert [i.id for i in model.sort_items(items, "name")] == ["h", "t", "d", "g", "f"]


def test_sort_modified_newest_first():
    items = [info("old", "a", modified=1), info("new", "b", modified=5)]
    assert [i.id for i in model.sort_items(items, "modified")] == ["new", "old"]


def test_sort_size_largest_first():
    items = [info("s", "a", size=1), info("l", "b", size=9)]
    assert [i.id for i in model.sort_items(items, "size")] == ["l", "s"]


def test_validate_names():
    existing = {"a.txt", "dir"}
    assert model.validate_file_name("", existing) == "empty"
    assert model.validate_file_name("a/b", existing) == "slash"
    assert model.validate_file_name("..", existing) == "dot"
    assert model.validate_file_name("dir", existing) == "exists"
    assert model.validate_file_name("dir", existing, current="dir") is None
    assert model.validate_file_name("x" * 300, existing) == "too-long"
    assert model.validate_file_name("ok.txt", existing) is None


def test_cell_geometry_round_trip():
    cell = model.cell_size("medium", 17.0)
    g = Grid.for_area("A", 1280, 700, cell)
    x, y = model.cell_origin(2, 1, cell, 1280, 700, g)
    assert model.cell_at(x + 5, y + 5, cell, 1280, 700, g) == (2, 1)


def test_text_scaling_grows_cells():
    assert model.cell_size("medium", 25).height > model.cell_size("medium", 17).height


# The grid starts at the chosen corner with GRID_MARGIN from both edges; the
# space left after the whole cells is on the opposite sides, never split
# into wide margins around the grid.
def test_grid_starts_at_its_corner():
    cell = CellSize(104, 125)
    # 1280 x 768 below a 32 px top bar: 12 columns use 1248 px, 32 left.
    expected = {
        "top-left": (model.GRID_MARGIN, 32 + model.GRID_MARGIN),
        "top-right": (1280 - model.GRID_MARGIN - 12 * 104, 32 + model.GRID_MARGIN),
        "bottom-left": (model.GRID_MARGIN, 32 + 768 - model.GRID_MARGIN - 6 * 125),
        "bottom-right": (1280 - model.GRID_MARGIN - 12 * 104, 32 + 768 - model.GRID_MARGIN - 6 * 125),
    }
    for corner, origin in expected.items():
        s = Surface("A", 1280, 768, cell, x=0, y=32, corner=corner)
        assert (s.grid.columns, s.grid.rows) == (12, 6)
        assert s.origin(0, 0) == origin, corner


def test_grid_margin_at_the_corner_edges_is_small_and_even():
    cell = CellSize(104, 125)
    for width in range(900, 1500, 37):
        s = Surface("A", width, 700, cell, corner="top-left")
        assert s.origin(0, 0) == (model.GRID_MARGIN, model.GRID_MARGIN)
        s = Surface("A", width, 700, cell, corner="bottom-right")
        x, y = s.origin(s.grid.columns - 1, s.grid.rows - 1)
        assert width - (x + cell.width) == model.GRID_MARGIN
        assert 700 - (y + cell.height) == model.GRID_MARGIN


def test_first_icons_fill_from_the_corner():
    cell = CellSize(100, 100)
    for corner in model.CORNERS:
        s = Surface("A", 1010, 710, cell, corner=corner)
        placed = model.layout(["a"], {}, {"A": s}, "A", corner).placements["a"]
        right = corner.endswith("right")
        bottom = corner.startswith("bottom")
        assert placed.x == (1010 - model.GRID_MARGIN - 100 if right else model.GRID_MARGIN)
        assert placed.y == (710 - model.GRID_MARGIN - 100 if bottom else model.GRID_MARGIN)


def test_cells_round_trip_from_every_corner():
    cell = model.cell_size("medium", 17.0)
    for corner in model.CORNERS:
        s = Surface("A", 1280, 700, cell, x=80, y=32, corner=corner)
        for col, row in ((0, 0), (2, 1), (s.grid.columns - 1, s.grid.rows - 1)):
            x, y = s.origin(col, row)
            assert s.cell_at(x + 5, y + 5) == (col, row)
            assert s.nearest_cell(x, y) == (col, row)


def test_free_positions_are_not_moved_by_the_corner():
    saved = {"a": Placement("A", 333, 222)}
    for corner in model.CORNERS:
        s = Surface("A", 1280, 768, CellSize(104, 125), x=0, y=32, corner=corner)
        assert model.layout(["a"], saved, {"A": s}, "A", corner).placements["a"] == \
            Placement("A", 333, 222)
