# SPDX-License-Identifier: GPL-3.0-or-later
"""Editing org.gnome.desktop.wm.preferences button-layout.

The value looks like "appmenu:minimize,maximize,close": buttons left of the
colon go to the left side of the title bar. Only the three window buttons
are moved or toggled; other entries (appmenu, icon, menu, spacer) and their
sides are kept as the user had them.
"""

WINDOW_BUTTONS = ("minimize", "maximize", "close")
# Order of the window buttons on each side, as in GNOME's defaults.
ORDER = {
    "right": ("minimize", "maximize", "close"),
    "left": ("close", "minimize", "maximize"),
}


def parse(layout):
    left, _sep, right = (layout or "").partition(":")
    return _tokens(left), _tokens(right)


def _tokens(part):
    return [t.strip() for t in part.split(",") if t.strip()]


def format_layout(left, right):
    return ",".join(left) + ":" + ",".join(right)


def has_button(layout, button):
    left, right = parse(layout)
    return button in left or button in right


def side(layout):
    """Side of the window buttons: where close is, else where any is."""
    left, right = parse(layout)
    for button in ("close", "minimize", "maximize"):
        if button in left:
            return "left"
        if button in right:
            return "right"
    return "right"


def _arrange(tokens, buttons, where):
    """Put the wanted window buttons into tokens, in GNOME order."""
    others = [t for t in tokens if t not in WINDOW_BUTTONS]
    ordered = [b for b in ORDER[where] if b in buttons]
    if where == "right":
        return others + ordered
    return ordered + others


def set_button(layout, button, enabled):
    if button not in WINDOW_BUTTONS:
        raise ValueError(button)
    left, right = parse(layout)
    where = side(layout)
    buttons = {b for b in WINDOW_BUTTONS if b in left or b in right}
    if enabled:
        buttons.add(button)
    else:
        buttons.discard(button)
    return _build(left, right, buttons, where)


def set_side(layout, where):
    if where not in ORDER:
        raise ValueError(where)
    left, right = parse(layout)
    buttons = {b for b in WINDOW_BUTTONS if b in left or b in right}
    return _build(left, right, buttons, where)


def _build(left, right, buttons, where):
    if where == "right":
        left = [t for t in left if t not in WINDOW_BUTTONS]
        right = _arrange(right, buttons, "right")
    else:
        right = [t for t in right if t not in WINDOW_BUTTONS]
        left = _arrange(left, buttons, "left")
    return format_layout(left, right)
