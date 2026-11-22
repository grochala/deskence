# SPDX-License-Identifier: GPL-3.0-or-later
"""Previews of the dock and the desktop icon layout.

Both pages draw the same screen (ScreenPreview): border, top bar and, when
it is shown, the dock; each page adds what it is about. The geometry is in
preview_geometry.py: an illustration in which the dock and the icons are
drawn larger than a faithful miniature would show them, so the effect of a
setting is easy to see. Everything is drawn in shades of the foreground
color of the current style, so it follows light, dark and high contrast
styles: application icons are neutral tiles with simple symbolic signs,
folders and documents are monochrome shapes, and there is no wallpaper. The
only color shown is one the user chose, such as a custom dock background,
since it tells what the setting does. Previews describe themselves to
screen readers.
"""

import math
from gettext import gettext as _

from gi.repository import Gtk

from . import preview_geometry as geo

# Contrast of the drawn elements against the screen, as alpha of the
# foreground color.
TILE_ALPHA = 0.16
SIGN_ALPHA = 0.7
DOCK_ALPHA = 0.12


def _rounded(cr, rect, r):
    x, y, w, h = rect.x, rect.y, rect.w, rect.h
    r = max(0.0, min(r, w / 2, h / 2))
    if r == 0:
        cr.rectangle(x, y, w, h)
        return
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _fill(cr, color, alpha):
    cr.set_source_rgba(color.red, color.green, color.blue, alpha)
    cr.fill()


class ScreenPreview(Gtk.DrawingArea):
    """A monitor with the top bar and, optionally, the dock.

    The monitor has the aspect ratio of the one the window is on. Content is
    clipped to the inside of the border as a last safeguard only; the layout
    itself keeps everything inside, see preview_geometry.py.
    """

    def __init__(self):
        super().__init__(accessible_role=Gtk.AccessibleRole.IMG, hexpand=True)
        self.dock_settings = None
        self.dock_background = None
        self.set_draw_func(self._draw)

    def set_dock(self, position, length, icon_size, apps_button="end", background=None):
        """apps_button: "start", "end" or None when hidden. background: a
        custom dock color as (r, g, b, alpha) in 0..1, or None for the
        style's own."""
        self.dock_settings = (position, length, icon_size, apps_button)
        self.dock_background = background
        self.queue_draw()

    def hide_dock(self):
        self.dock_settings = None
        self.queue_draw()

    def _monitor_size(self):
        native = self.get_native()
        surface = native.get_surface() if native else None
        if surface is not None:
            monitor = self.get_display().get_monitor_at_surface(surface)
            if monitor is not None:
                geometry = monitor.get_geometry()
                return geometry.width, geometry.height
        return geo.DEFAULT_SCREEN

    def _draw(self, area, cr, width, height):
        fg = self.get_color()
        scr = geo.screen(width, height, self._monitor_size())
        if scr.inner.w <= 0 or scr.inner.h <= 0:
            return
        cr.save()
        _rounded(cr, scr.inner, scr.inner_radius)
        cr.clip()
        cr.rectangle(scr.inner.x, scr.inner.y, scr.inner.w, scr.inner.h)
        _fill(cr, fg, 0.07)
        cr.rectangle(scr.top_bar.x, scr.top_bar.y, scr.top_bar.w, scr.top_bar.h)
        _fill(cr, fg, 0.55)
        dock = None
        if self.dock_settings is not None:
            dock = geo.dock(scr, *self.dock_settings)
        self.draw_content(cr, fg, scr, dock)
        cr.restore()
        # The border last, so nothing is drawn over it.
        frame = scr.frame
        _rounded(cr, geo.Rect(frame.x + 0.5, frame.y + 0.5, frame.w - 1, frame.h - 1),
                 scr.inner_radius + 0.5)
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.35)
        cr.set_line_width(geo.BORDER)
        cr.stroke()

    def draw_content(self, cr, fg, scr, dock):
        if dock is not None:
            self.draw_dock(cr, fg, dock, 1.0)

    def draw_dock(self, cr, fg, dock, emphasis):
        """emphasis 1 on the Dock page; lower where the dock is context."""
        ink = fg
        _rounded(cr, dock.box, dock.radius)
        if self.dock_background is not None:
            # The color the user chose is information, not decoration.
            r, g, b, a = self.dock_background
            cr.set_source_rgba(r, g, b, a * emphasis)
            cr.fill_preserve()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.25 * emphasis)
            cr.set_line_width(1)
            cr.stroke()
            if a > 0.4:
                ink = _ink_for(r, g, b)
        else:
            _fill(cr, fg, DOCK_ALPHA * emphasis)
        for item in dock.items:
            rect = item.rect
            if item.apps_button:
                # The applications button: a grid of dots.
                r = rect.w / 11
                for gx in range(3):
                    for gy in range(3):
                        cr.new_sub_path()
                        cr.arc(rect.x + rect.w * (0.2 + 0.3 * gx),
                               rect.y + rect.h * (0.2 + 0.3 * gy), r, 0, 2 * math.pi)
                _fill(cr, ink, 0.8 * emphasis)
                continue
            _draw_app_icon(cr, rect, item.index, ink, emphasis)
            if item.indicator:
                dot = item.indicator
                cr.new_sub_path()
                cr.arc(dot.x + dot.w / 2, dot.y + dot.h / 2, dot.w / 2, 0, 2 * math.pi)
                _fill(cr, ink, 0.9 * emphasis)


class _Ink:
    def __init__(self, value):
        self.red = self.green = self.blue = value


def _ink_for(r, g, b):
    """Light or dark signs on a custom dock color, like the dock does."""
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return _Ink(1.0 if luminance < 0.5 else 0.12)


def _draw_app_icon(cr, rect, index, fg, emphasis):
    """A neutral rounded tile with a symbolic sign; the signs differ so
    the icons are told apart without colors."""
    _rounded(cr, rect, rect.w * 0.22)
    _fill(cr, fg, TILE_ALPHA * emphasis)
    cx, cy, u = rect.x + rect.w / 2, rect.y + rect.h / 2, rect.w * 0.18
    kind = index % 4
    if kind == 0:
        cr.new_sub_path()
        cr.arc(cx, cy, u, 0, 2 * math.pi)
    elif kind == 1:
        _rounded(cr, geo.Rect(cx - u, cy - u, 2 * u, 2 * u), u * 0.3)
    elif kind == 2:
        cr.move_to(cx, cy - u * 1.1)
        cr.line_to(cx + u * 1.1, cy + u * 0.9)
        cr.line_to(cx - u * 1.1, cy + u * 0.9)
        cr.close_path()
    else:
        for i in range(3):
            cr.rectangle(cx - u, cy - u + i * u * 0.8, 2 * u * (1 if i < 2 else 0.6), u * 0.4)
    _fill(cr, fg, SIGN_ALPHA * emphasis)


class DockPreview(ScreenPreview):
    __gtype_name__ = "DeskenceDockPreview"

    def update(self, position, length, icon_size, apps_button="end", background=None):
        names = {"left": _("left"), "bottom": _("bottom"), "right": _("right")}
        self.update_property([Gtk.AccessibleProperty.LABEL],
                             [_("Preview: dock at the {} of the screen").format(
                                 names.get(position, position))])
        self.set_dock(position, length, icon_size, apps_button, background)


class IconsPreview(ScreenPreview):
    """Desktop icons placed from the chosen corner, next to the dock when
    the dock is shown."""

    __gtype_name__ = "DeskenceIconsPreview"

    def __init__(self):
        super().__init__()
        self.size = "medium"
        self.corner = "top-left"

    def update(self, size, corner):
        self.size, self.corner = size, corner
        names = {"top-left": _("top left"), "top-right": _("top right"),
                 "bottom-left": _("bottom left"), "bottom-right": _("bottom right")}
        self.update_property([Gtk.AccessibleProperty.LABEL],
                             [_("Preview: new icons are placed from the {} corner").format(
                                 names.get(corner, corner))])
        self.queue_draw()

    def draw_content(self, cr, fg, scr, dock):
        if dock is not None:
            self.draw_dock(cr, fg, dock, 0.45)
        cells, icon = geo.desktop_icons(scr, self.size, self.corner, dock)
        for i, cell in enumerate(cells):
            ix = cell.x + (cell.w - icon) / 2
            iy = cell.y + cell.h * 0.06
            rect = geo.Rect(ix, iy, icon, icon)
            # Folders first, then documents, as on a typical desktop.
            if i < 2:
                _draw_folder(cr, rect, fg)
            else:
                _draw_document(cr, rect, fg)
            # The name: two centered lines under the icon.
            line = max(1.5, icon * 0.09)
            y = iy + icon + max(1.0, icon * 0.08)
            for width in (0.8, 0.5):
                w = cell.w * width
                _rounded(cr, geo.Rect(cell.x + (cell.w - w) / 2, y, w, line), line / 2)
                _fill(cr, fg, 0.5)
                y += line * 1.6


def _draw_folder(cr, rect, fg):
    x, y, w, h = rect.x, rect.y, rect.w, rect.h
    # Back with the tab, then the front, in two shades.
    _rounded(cr, geo.Rect(x + w * 0.04, y + h * 0.16, w * 0.4, h * 0.2), w * 0.05)
    _fill(cr, fg, 0.3)
    _rounded(cr, geo.Rect(x + w * 0.04, y + h * 0.22, w * 0.92, h * 0.64), w * 0.07)
    _fill(cr, fg, 0.3)
    _rounded(cr, geo.Rect(x + w * 0.04, y + h * 0.32, w * 0.92, h * 0.54), w * 0.07)
    _fill(cr, fg, 0.45)


def _draw_document(cr, rect, fg):
    x, y, w, h = rect.x, rect.y, rect.w, rect.h
    page = geo.Rect(x + w * 0.18, y + h * 0.06, w * 0.64, h * 0.84)
    _rounded(cr, page, w * 0.05)
    _fill(cr, fg, 0.1)
    _rounded(cr, page.inset(0.5), w * 0.05)
    cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.45)
    cr.set_line_width(1)
    cr.stroke()
    # Lines of text.
    for i in range(4):
        ly = page.y + page.h * (0.25 + 0.15 * i)
        cr.rectangle(page.x + page.w * 0.18, ly, page.w * (0.64 if i < 3 else 0.4),
                     max(1.0, page.h * 0.05))
    _fill(cr, fg, 0.4)
