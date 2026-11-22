# SPDX-License-Identifier: GPL-3.0-or-later
"""Geometry of the screen previews on the Dock and Desktop Icons pages.

Pure functions, without GTK, so they can be tested.

A preview is an illustration of a setting, not a photograph of the screen.
The drawn screen has the aspect ratio of the real monitor, but its contents
are measured in "illustration pixels": the screen is treated as if it were
ILLUSTRATION_HEIGHT logical pixels tall, whatever the real resolution. A
dock or a desktop icon is therefore drawn about twice as large as a
faithful miniature of a 1280×800 screen would show it, so icon sizes and
the chosen layout are easy to tell apart, and every monitor looks alike.
Relative sizes stay true: a 64 px dock icon is drawn twice as large as a
32 px one.

Everything is laid out inside the inner area of the drawn screen (inside
its border) and away from its rounded corners. When the chosen sizes do not
fit, fewer items are shown first; only then are the items made smaller.
"""

import math
from dataclasses import dataclass

# Sizes in logical pixels of the real screen, see extensions/dock/stylesheet.css
# and the GNOME Shell theme.
TOP_BAR = 32
ICON_PADDING = 6      # .overview-icon padding around a dock icon
ITEM_MARGIN = 2       # margin of a dock item
BOX_PADDING = 6       # padding of the dock's item box
EDGE_GAP = 6          # a dock that fits its items keeps off the screen edge
DOCK_RADIUS = 20
# Desktop icons, see desktop-icons/deskence_desktop/model.py.
DESKTOP_ICON_SIZES = {"small": 48, "medium": 64, "large": 96, "huge": 128}
GRID_MARGIN = 8
LABEL_HEIGHT = 46     # three label lines and the spacing above them

# The drawn screen is as tall as this many logical pixels (see above).
ILLUSTRATION_HEIGHT = 440
# Fewest items shown before items are made smaller to fit.
MIN_DOCK_APPS = 3
MIN_DESKTOP_ICONS = 3

BORDER = 1
SCREEN_RADIUS = 10
DEFAULT_SCREEN = (1280, 800)


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self):
        return self.x + self.w

    @property
    def bottom(self):
        return self.y + self.h

    def inset(self, dx, dy=None):
        dy = dx if dy is None else dy
        return Rect(self.x + dx, self.y + dy, max(0.0, self.w - 2 * dx), max(0.0, self.h - 2 * dy))

    def contains(self, other, tolerance=1e-6):
        return (other.x >= self.x - tolerance and other.y >= self.y - tolerance and
                other.right <= self.right + tolerance and other.bottom <= self.bottom + tolerance)

    def overlaps(self, other, tolerance=1e-6):
        """Shares more than an edge with other."""
        return (other.x < self.right - tolerance and self.x < other.right - tolerance and
                other.y < self.bottom - tolerance and self.y < other.bottom - tolerance)


@dataclass(frozen=True)
class Screen:
    frame: Rect          # outer edge of the border, whole pixels
    inner: Rect          # inside the border
    inner_radius: float
    safe: Rect           # inner area away from the rounded corners
    top_bar: Rect
    area: Rect           # inner area below the top bar
    scale: float         # preview pixels per illustration pixel


@dataclass(frozen=True)
class DockItem:
    rect: Rect           # the icon
    apps_button: bool
    indicator: Rect      # None when the application is not running
    index: int           # position among the applications, -1 for the button


@dataclass(frozen=True)
class Dock:
    box: Rect
    radius: float
    items: tuple
    position: str


def screen_size(width, height):
    """Logical monitor size used for a preview, with a sane aspect ratio."""
    if not width or not height:
        width, height = DEFAULT_SCREEN
    aspect = min(2.4, max(1.25, width / height))
    return width, width / aspect


def screen(width, height, monitor=DEFAULT_SCREEN, margin=4):
    """The screen drawn in a widget of width x height pixels."""
    mon_w, mon_h = screen_size(*monitor)
    aspect = mon_w / mon_h
    h = max(0.0, height - 2 * margin)
    w = min(max(0.0, width - 2 * margin), h * aspect)
    h = w / aspect
    # Whole pixels, so the one pixel border is sharp.
    w, h = math.floor(w), math.floor(h)
    frame = Rect(math.floor((width - w) / 2), math.floor((height - h) / 2), w, h)
    inner = frame.inset(BORDER)
    inner_radius = max(0.0, min(SCREEN_RADIUS - BORDER, inner.w / 4, inner.h / 4))
    # A rectangle inset by r(1 - 1/sqrt(2)) has its corners on the arcs of
    # a rounded rectangle with radius r; one more pixel keeps it off them.
    corner = math.ceil(inner_radius * (1 - 1 / math.sqrt(2))) + 1 if inner_radius else 0
    safe = inner.inset(corner)
    scale = inner.h / ILLUSTRATION_HEIGHT if inner.h else 0.0
    bar = Rect(inner.x, inner.y, inner.w, min(inner.h / 4, max(3.0, TOP_BAR * scale)))
    area = Rect(inner.x, bar.bottom, inner.w, max(0.0, inner.bottom - bar.bottom))
    return Screen(frame, inner, inner_radius, safe, bar, area, scale)


def dock(scr, position, length, icon_size, apps_button="end", apps=5, running=3):
    """Dock with up to apps application icons and the applications button.

    apps_button: "start", "end" or None when the button is hidden. The
    first running applications get indicators. When icons of the chosen
    size do not fit, fewer applications are shown (down to MIN_DOCK_APPS);
    only then is the dock made smaller as a whole.
    """
    vertical = position in ("left", "right")
    full = length == "full"
    area, safe = scr.area, scr.safe
    button = 1 if apps_button else 0

    # Along the edge: what the items may use. A whole-edge dock lies on
    # the edge, where its items have to keep clear of the screen's rounded
    # corners; the top bar may be lower than a corner is round.
    corner = scr.inner_radius + 0.5 if full else 0.0
    if vertical:
        along_start = max(area.y, safe.y, scr.inner.y + corner)
        along_end = min(safe.bottom, scr.inner.bottom - corner)
        across_room = area.w
    else:
        along_start = max(safe.x, scr.inner.x + corner)
        along_end = min(safe.right, scr.inner.right - corner)
        across_room = area.h
    along_room = max(0.0, along_end - along_start)

    k = scr.scale
    tile = (icon_size + 2 * ICON_PADDING + 2 * ITEM_MARGIN) * k
    pad = BOX_PADDING * k
    gap = 0.0 if full else EDGE_GAP * k
    thick = tile + 2 * pad
    # A whole-edge dock with the button at its far end shows the free room
    # between the list and the button; keep at least one tile of it.
    spare = tile if full and apps_button == "end" else 0.0

    def needed(n):
        return (n + button) * tile + 2 * pad + spare

    apps = max(apps, 1)
    while apps > MIN_DOCK_APPS and needed(apps) > along_room:
        apps -= 1
    fit = 1.0
    if needed(apps) > along_room:
        fit = along_room / needed(apps)
    # A dock never takes more than a third of the screen across.
    if thick * fit > across_room / 3:
        fit = across_room / 3 / thick
    tile, pad, thick, gap = tile * fit, pad * fit, thick * fit, gap * fit
    icon = icon_size * k * fit
    count = apps + button
    length_used = count * tile + 2 * pad
    radius = 0.0 if full else min(DOCK_RADIUS * k * fit, thick / 2)

    # Across the edge: a whole-edge dock lies on the edge, a short one keeps
    # its gap, and both stay clear of the rounded corners.
    if full:
        if vertical:
            box_along = (area.y, area.bottom)
        else:
            box_along = (scr.inner.x, scr.inner.right)
    else:
        start = along_start + (along_room - length_used) / 2
        box_along = (start, start + length_used)
    if position == "bottom":
        edge = area.bottom if full else min(area.bottom - gap, safe.bottom)
        box = Rect(box_along[0], edge - thick, box_along[1] - box_along[0], thick)
    elif position == "left":
        edge = area.x if full else max(area.x + gap, safe.x)
        box = Rect(edge, box_along[0], thick, box_along[1] - box_along[0])
    else:
        edge = area.right if full else min(area.right - gap, safe.right)
        box = Rect(edge - thick, box_along[0], thick, box_along[1] - box_along[0])

    # Item slots along the dock. In a whole-edge dock the list starts at
    # the top or left end; the applications button stays at its end.
    first = max(box_along[0] + pad, along_start)
    last = min(box_along[1] - pad, along_end)
    slots = [first + i * tile for i in range(count)]
    if apps_button == "end" and full:
        slots[-1] = last - tile
    items = []
    app_index = 0
    for i, slot in enumerate(slots):
        is_apps = (apps_button == "start" and i == 0) or (apps_button == "end" and i == count - 1)
        offset = (tile - icon) / 2
        if vertical:
            rect = Rect(box.x + (thick - icon) / 2, slot + offset, icon, icon)
        else:
            rect = Rect(slot + offset, box.y + (thick - icon) / 2, icon, icon)
        running_dot = None
        if not is_apps and app_index < running:
            running_dot = _indicator(rect, position, (thick - icon) / 2)
        items.append(DockItem(rect, is_apps, running_dot, -1 if is_apps else app_index))
        if not is_apps:
            app_index += 1
    return Dock(box, radius, tuple(items), position)


def _indicator(icon, position, room):
    """Running indicator beside an icon: under it in a bottom dock, on the
    side facing the inside of the screen in a side dock. room is the space
    between the icon and the dock's edge; the indicator stays in it, as on
    the real dock, and is large enough to be seen."""
    size = min(max(2.5, room * 0.45), room * 0.7)
    gap = (room - size) / 2.5
    if position == "bottom":
        return Rect(icon.x + (icon.w - size) / 2, icon.bottom + gap, size, size)
    if position == "left":
        return Rect(icon.right + gap, icon.y + (icon.h - size) / 2, size, size)
    return Rect(icon.x - gap - size, icon.y + (icon.h - size) / 2, size, size)


def icons_area(scr, dock_layout=None):
    """Where desktop icons go: the area below the top bar without the dock
    (the desktop keeps icons out of the dock's outline)."""
    area = scr.area
    safe = scr.safe
    x, y, right, bottom = safe.x, max(area.y, safe.y), safe.right, safe.bottom
    if dock_layout is not None:
        box = dock_layout.box
        if dock_layout.position == "bottom":
            bottom = min(bottom, box.y)
        elif dock_layout.position == "left":
            x = max(x, box.right)
        else:
            right = min(right, box.x)
    return Rect(x, y, max(0.0, right - x), max(0.0, bottom - y))


def desktop_icons(scr, size, corner, dock_layout=None, count=5):
    """Cells (rectangles) of desktop icons placed from corner, filling
    columns first like the desktop does. Up to count icons; fewer (down to
    MIN_DESKTOP_ICONS) when large icons do not fit, and only then smaller.
    Returns (cells, icon size)."""
    area = icons_area(scr, dock_layout)
    k = scr.scale
    icon = DESKTOP_ICON_SIZES.get(size, DESKTOP_ICON_SIZES["medium"])
    cell_w = max(icon + 40, icon * 1.5) * k
    cell_h = (icon + LABEL_HEIGHT) * k
    margin = GRID_MARGIN * k
    icon *= k

    def capacity(fit):
        """(icons that fit, rows) with everything scaled by fit."""
        if cell_w <= 0 or cell_h <= 0:
            return 0, 1
        rows = int((area.h - 2 * margin * fit + 1e-9) // (cell_h * fit))
        columns = int((area.w - 2 * margin * fit + 1e-9) // (cell_w * fit))
        return max(rows, 0) * max(columns, 0), max(rows, 1)

    fit = 1.0
    room, rows = capacity(fit)
    for _ in range(60):
        if room >= min(count, MIN_DESKTOP_ICONS):
            break
        fit *= 0.95
        room, rows = capacity(fit)
    count = max(0, min(count, room))
    cell_w, cell_h, margin, icon = cell_w * fit, cell_h * fit, margin * fit, icon * fit
    right = corner.endswith("right")
    bottom = corner.startswith("bottom")
    cells = []
    for i in range(count):
        col, row = divmod(i, rows)
        cx = area.x + margin + col * cell_w if not right else area.right - margin - (col + 1) * cell_w
        cy = area.y + margin + row * cell_h if not bottom else area.bottom - margin - (row + 1) * cell_h
        cells.append(Rect(cx, cy, cell_w, cell_h))
    return cells, icon
