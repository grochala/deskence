# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure desktop icon logic: geometry, placement and sorting.

Nothing here touches GTK or the file system, so it is unit tested directly.

Icon positions are logical pixels relative to the top-left corner of their
monitor. The available area of a monitor (without the top bar) and the docks
inside it only bound them: when the dock moves, icons that still fit keep
their exact place, and only icons that would overlap the dock or stick out
are moved - without forgetting where they belong. The grid only decides where
new icons go and where icons snap to; icons placed freely keep their exact
position. The configured start corner decides where the grid starts and the
order in which free cells are filled for icons without a remembered position.
"""

from dataclasses import dataclass, field

ICON_SIZES = {"small": 48, "medium": 64, "large": 96, "huge": 128}

CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")

GRID_MARGIN = 8
LABEL_LINES = 3


@dataclass(frozen=True)
class CellSize:
    width: int
    height: int


def cell_size(icon_size_nick, line_height):
    """Cell size for an icon size, growing with the text size."""
    icon = ICON_SIZES.get(icon_size_nick, ICON_SIZES["medium"])
    width = max(icon + 40, int(icon * 1.5))
    height = icon + 12 + int(round(line_height * LABEL_LINES))
    return CellSize(width, height)


@dataclass
class Grid:
    """Cells available on one monitor."""
    connector: str
    columns: int
    rows: int

    @classmethod
    def for_area(cls, connector, width, height, cell):
        columns = max(1, (width - 2 * GRID_MARGIN) // cell.width)
        rows = max(1, (height - 2 * GRID_MARGIN) // cell.height)
        return cls(connector, columns, rows)

    def contains(self, col, row):
        return 0 <= col < self.columns and 0 <= row < self.rows

    def cells_from(self, corner):
        """Cells in fill order: column by column, starting at the corner."""
        cols = range(self.columns)
        rows = range(self.rows)
        if corner in ("top-right", "bottom-right"):
            cols = reversed(cols)
        cols = list(cols)
        if corner in ("bottom-left", "bottom-right"):
            rows = list(reversed(rows))
        else:
            rows = list(rows)
        for col in cols:
            for row in rows:
                yield col, row


def grid_offset(cell, area_width, area_height, grid, corner="top-left"):
    """Origin of the grid inside the available area.

    The grid starts GRID_MARGIN from the edges of the chosen corner; what is
    left after the whole cells stays on the opposite sides, so the icons keep
    small, even margins at their corner and do not move when the area grows
    or shrinks on the other side.
    """
    used_w = grid.columns * cell.width
    used_h = grid.rows * cell.height
    offset_x = GRID_MARGIN
    offset_y = GRID_MARGIN
    if corner.endswith("right"):
        offset_x = max(GRID_MARGIN, area_width - used_w - GRID_MARGIN)
    if corner.startswith("bottom"):
        offset_y = max(GRID_MARGIN, area_height - used_h - GRID_MARGIN)
    return offset_x, offset_y


def cell_origin(col, row, cell, area_width, area_height, grid, corner="top-left"):
    """Pixel origin of a cell inside the available area."""
    offset_x, offset_y = grid_offset(cell, area_width, area_height, grid, corner)
    return offset_x + col * cell.width, offset_y + row * cell.height


def cell_at(x, y, cell, area_width, area_height, grid, corner="top-left"):
    """Grid cell under a point, clamped to the grid."""
    ox, oy = cell_origin(0, 0, cell, area_width, area_height, grid, corner)
    col = int((x - ox) // cell.width)
    row = int((y - oy) // cell.height)
    return (min(max(col, 0), grid.columns - 1), min(max(row, 0), grid.rows - 1))


@dataclass(frozen=True)
class Area:
    """Part of a desktop window icons may use, in window coordinates.

    The window covers the whole monitor; the area leaves out the top bar and
    the dock.
    """
    x: int
    y: int
    width: int
    height: int


class Surface:
    """The available area of one monitor, with its grid.

    Icon positions are slot origins: the top-left corner of the cell-sized box
    an icon occupies, relative to the monitor. The area is the rectangle
    (x, y, width, height) of the monitor icons may use; on the grid slots
    are cell origins, placed freely they can be anywhere inside the area.

    exclusions are rectangles (x, y, width, height), also relative to the
    monitor, that icons must not overlap: the docks. Only the dock itself is
    excluded, not the whole band along its edge.

    corner is the start corner of the grid, see grid_offset().
    """

    def __init__(self, connector, width, height, cell, exclusions=(), x=0, y=0,
                 corner="top-left"):
        self.connector = connector
        self.corner = corner
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.cell = cell
        self.exclusions = tuple(exclusions)
        self.grid = Grid.for_area(connector, width, height, cell)

    def blocked(self, slot):
        """Whether a slot overlaps an excluded rectangle."""
        x, y = slot
        return any(x < ex + ew and x + self.cell.width > ex and
                   y < ey + eh and y + self.cell.height > ey
                   for ex, ey, ew, eh in self.exclusions)

    def blocked_cells(self):
        return {(c, r) for c in range(self.grid.columns) for r in range(self.grid.rows)
                if self.blocked(self.origin(c, r))}

    def origin(self, col, row):
        x, y = cell_origin(col, row, self.cell, self.width, self.height, self.grid,
                           self.corner)
        return self.x + x, self.y + y

    def cell_at(self, x, y):
        """Cell under a point."""
        return cell_at(x - self.x, y - self.y, self.cell, self.width, self.height, self.grid,
                       self.corner)

    def nearest_cell(self, x, y):
        """Cell whose origin is closest to a slot origin."""
        ox, oy = self.origin(0, 0)
        col = round((x - ox) / self.cell.width)
        row = round((y - oy) / self.cell.height)
        return (min(max(col, 0), self.grid.columns - 1),
                min(max(row, 0), self.grid.rows - 1))

    def clamp(self, x, y):
        """Keep a slot inside the area (at the start edge if it does not fit)."""
        x = max(self.x, min(x, self.x + self.width - self.cell.width))
        y = max(self.y, min(y, self.y + self.height - self.cell.height))
        return int(round(x)), int(round(y))

    def collides(self, a, b):
        """Whether two slots overlap enough to hide each other's icon or name."""
        return abs(a[0] - b[0]) < self.cell.width / 2 and \
            abs(a[1] - b[1]) < self.cell.height / 2

    def covered_cells(self, x, y):
        """Cells a slot collides with; at most two in each direction."""
        col, row = self.nearest_cell(x, y)
        result = set()
        for c in (col - 1, col, col + 1):
            for r in (row - 1, row, row + 1):
                if self.grid.contains(c, r) and self.collides(self.origin(c, r), (x, y)):
                    result.add((c, r))
        return result

    def nearest_free(self, x, y, occupied):
        """Origin of the free cell closest to a slot origin, or None."""
        best = None
        for c in range(self.grid.columns):
            for r in range(self.grid.rows):
                if (c, r) in occupied:
                    continue
                cx, cy = self.origin(c, r)
                distance = (cx - x) ** 2 + (cy - y) ** 2
                if best is None or distance < best[0]:
                    best = (distance, cx, cy)
        return None if best is None else (best[1], best[2])


@dataclass
class Placement:
    connector: str
    x: int
    y: int


@dataclass
class LayoutResult:
    placements: dict = field(default_factory=dict)
    # Positions worth remembering: new icons placed for the first time.
    # Icons moved only because their monitor is missing, the area became
    # smaller or another icon covers them are not remembered, so they return
    # when the monitor or the space comes back.
    to_save: dict = field(default_factory=dict)


class _Occupancy:
    """Slots placed so far on one surface and the grid cells they cover."""

    def __init__(self, surface):
        self.surface = surface
        self.slots = []
        self.cells = surface.blocked_cells()

    def collides(self, slot):
        return self.surface.blocked(slot) or \
            any(self.surface.collides(slot, other) for other in self.slots)

    def add(self, slot):
        self.slots.append(slot)
        self.cells |= self.surface.covered_cells(*slot)

    def free_cells(self, corner):
        for col, row in self.surface.grid.cells_from(corner):
            if (col, row) not in self.cells:
                yield self.surface.origin(col, row)


def layout(item_ids, saved, surfaces, primary, corner):
    """Assign a position to every item.

    item_ids  ordered ids (already sorted); earlier items are placed first
    saved     {id: Placement} remembered positions
    surfaces  {connector: Surface} of connected monitors
    primary   connector of the primary monitor
    corner    one of CORNERS

    Remembered positions are kept as they are, only pulled back inside the
    available area. An icon that would cover another one goes to the nearest
    free cell; icons without a position fill free cells from the corner.
    """
    result = LayoutResult()
    occupancy = {connector: _Occupancy(s) for connector, s in surfaces.items()}
    pending = []

    for item_id in item_ids:
        pos = saved.get(item_id)
        surface = surfaces.get(pos.connector) if pos else None
        if surface is None:
            pending.append((item_id, None))
            continue
        slot = surface.clamp(pos.x, pos.y)
        if occupancy[pos.connector].collides(slot):
            pending.append((item_id, (pos.connector, slot)))
            continue
        occupancy[pos.connector].add(slot)
        result.placements[item_id] = Placement(pos.connector, *slot)

    order = [primary] + [c for c in surfaces if c != primary]
    order = [c for c in order if c in surfaces]

    def first_free():
        for connector in order:
            slot = next(occupancy[connector].free_cells(corner), None)
            if slot is not None:
                return connector, slot
        return None

    for item_id, preferred in pending:
        spot = None
        if preferred is not None:
            connector, (x, y) = preferred
            free = surfaces[connector].nearest_free(x, y, occupancy[connector].cells)
            if free is not None:
                spot = connector, free
        if spot is None:
            spot = first_free()
        if spot is None:
            # Everything is full: stack the rest on the last cell.
            surface = surfaces[order[0]]
            col, row = list(surface.grid.cells_from(corner))[-1]
            spot = order[0], surface.origin(col, row)
        connector, slot = spot
        occupancy[connector].add(slot)
        placement = Placement(connector, *slot)
        result.placements[item_id] = placement
        if saved.get(item_id) is None:
            result.to_save[item_id] = placement
    return result


def place_dropped(item_ids, anchor, offsets, surface, others, snap):
    """Positions for icons dropped together on one surface.

    anchor   slot origin under the pointer for the first item
    offsets  {id: (dx, dy)} relative to the first item before the drag
    others   slot origins of the icons that stay where they are
    snap     align each icon to the grid

    The icons keep their arrangement; the group as a whole is moved back
    inside the area when it would stick out. An icon landing on another one
    is not refused but put into the nearest free cell.
    """
    wanted = {}
    for item_id in item_ids:
        dx, dy = offsets.get(item_id, (0, 0))
        wanted[item_id] = (anchor[0] + dx, anchor[1] + dy)
    if wanted:
        xs = [x for x, _y in wanted.values()]
        ys = [y for _x, y in wanted.values()]
        shift_x = _group_shift(min(xs), max(xs), surface.x,
                               surface.x + surface.width - surface.cell.width)
        shift_y = _group_shift(min(ys), max(ys), surface.y,
                               surface.y + surface.height - surface.cell.height)
        wanted = {i: (x + shift_x, y + shift_y) for i, (x, y) in wanted.items()}

    occupancy = _Occupancy(surface)
    for slot in others:
        occupancy.add(slot)
    result = {}
    for item_id in item_ids:
        slot = surface.clamp(*wanted[item_id])
        if snap:
            slot = surface.origin(*surface.nearest_cell(*slot))
        if occupancy.collides(slot):
            slot = surface.nearest_free(*slot, occupancy.cells) or slot
        occupancy.add(slot)
        result[item_id] = slot
    return result


def _group_shift(low, high, start, limit):
    """Shift keeping [low, high] inside [start, limit], preferring the start."""
    if high > limit:
        return max(limit - high, start - low)
    if low < start:
        return start - low
    return 0


def align_to_grid(slots, surface):
    """Move freely placed icons to the nearest free cells.

    slots: {id: (x, y)}. Icons already on a cell keep it; the others are
    handled from the closest to a cell to the farthest, so the arrangement
    changes as little as possible.
    """
    def distance(item):
        x, y = item[1]
        cx, cy = surface.origin(*surface.nearest_cell(x, y))
        return (cx - x) ** 2 + (cy - y) ** 2

    occupied = surface.blocked_cells()
    result = {}
    for item_id, (x, y) in sorted(slots.items(), key=lambda item: (distance(item), item[0])):
        col, row = surface.nearest_cell(x, y)
        if (col, row) in occupied:
            free = surface.nearest_free(x, y, occupied)
            if free is None:
                result[item_id] = surface.origin(col, row)
                continue
            col, row = surface.nearest_cell(*free)
        occupied.add((col, row))
        result[item_id] = surface.origin(col, row)
    return result


def slot_for_point(px, py, surface, icon_size, snap):
    """Slot for a new icon created at a point of the monitor."""
    if snap:
        return surface.origin(*surface.cell_at(px, py))
    return surface.clamp(px - surface.cell.width / 2, py - icon_size / 2 - 4)


@dataclass
class SortInfo:
    """What sorting needs to know about an item."""
    id: str
    name: str
    collate_key: str
    is_dir: bool
    modified: int
    size: int
    content_type: str
    special_rank: int = -1  # >= 0 for home, trash and drives


def sort_items(items, order):
    """Sort items for "Arrange Icons".

    Special icons (home, trash, drives) always come first. Folders come before
    files, as in Files. "modified" puts the newest first, "size" the largest.
    """
    def key(info):
        special = (0, info.special_rank) if info.special_rank >= 0 else (1, 0)
        folders_first = 0 if info.is_dir else 1
        if order == "modified":
            main = (-info.modified,)
        elif order == "size":
            main = (-info.size,)
        elif order == "type":
            main = (info.content_type,)
        else:
            main = ()
        return special + (folders_first,) + main + (info.collate_key,)
    return sorted(items, key=key)


def validate_file_name(name, existing, current=None):
    """Return an error message id for an invalid new name, or None.

    The ids are translated by the caller.
    """
    stripped = name.strip()
    if not stripped:
        return "empty"
    if "/" in name:
        return "slash"
    if name in (".", ".."):
        return "dot"
    if name != current and name in existing:
        return "exists"
    if len(name.encode("utf-8")) > 255:
        return "too-long"
    return None


def name_is_hidden(name):
    return name.startswith(".")
