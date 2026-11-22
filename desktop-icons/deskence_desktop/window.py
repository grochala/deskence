# SPDX-License-Identifier: GPL-3.0-or-later
"""Desktop windows: one per monitor, showing the icons placed on it."""

from gettext import gettext as _

from gi.repository import Gdk, Gio, GLib, Graphene, Gtk, Pango

from . import legacy, model, shellmenu

# Marks desktop windows for the GNOME Shell extension (extensions/desktop);
# the former tag when started by the former extension (legacy.py).
DESKTOP_TITLE_TAG = legacy.TITLE_TAG if legacy.ACTIVE else "@deskence-desktop:"
# Horizontal space between an icon and the edges of its slot.
ICON_INSET = 4
INTERNAL_MIME = "application/x-deskence-desktop-icons"
# Icons drawn in the drag image of a group; more would only make it huge.
MAX_DRAG_ICONS = 24


class IconWidget(Gtk.Box):
    """One desktop icon: picture and name."""

    def __init__(self, window, item):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                         focusable=True, accessible_role=Gtk.AccessibleRole.BUTTON,
                         halign=Gtk.Align.CENTER, valign=Gtk.Align.START)
        self.add_css_class("desktop-icon")
        self.window = window
        self.item = None
        self._signature = None

        self._overlay = Gtk.Overlay(halign=Gtk.Align.CENTER)
        self._image = Gtk.Image()
        self._picture = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True)
        self._emblem = Gtk.Image(halign=Gtk.Align.END, valign=Gtk.Align.END, pixel_size=16)
        self._emblem.add_css_class("desktop-icon-emblem")
        self._overlay.set_child(self._image)
        self._overlay.add_overlay(self._emblem)
        self.append(self._overlay)

        self._label = Gtk.Label(wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
                                justify=Gtk.Justification.CENTER, lines=model.LABEL_LINES,
                                ellipsize=Pango.EllipsizeMode.END, max_width_chars=1)
        self.append(self._label)

        source = Gtk.DragSource(actions=Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        source.connect("prepare", self._on_drag_prepare)
        source.connect("drag-begin", self._on_drag_begin)
        source.connect("drag-end", self._on_drag_end)
        self.add_controller(source)

        # Slot origin relative to the monitor (the window), see model.Surface.
        self.slot = (0, 0)
        self.update(item)

    def update(self, item):
        self.item = item
        signature = item.signature() + (self.window.icon_size,)
        if signature == self._signature:
            return
        self._signature = signature
        size = self.window.icon_size
        cell = self.window.cell
        self.set_size_request(cell.width - 8, -1)
        self._label.set_text(item.name)
        self.set_tooltip_text(item.name)
        self.update_property([Gtk.AccessibleProperty.LABEL], [item.name])

        if item.thumbnail:
            self._picture.set_filename(item.thumbnail)
            self._picture.set_size_request(size, size)
            self._overlay.set_child(self._picture)
        else:
            self._image.set_from_gicon(item.gicon or Gio.ThemedIcon.new("text-x-generic"))
            self._image.set_pixel_size(size)
            self._overlay.set_child(self._image)
        if item.emblem:
            self._emblem.set_from_icon_name(item.emblem)
            self._emblem.set_visible(True)
        else:
            self._emblem.set_visible(False)
        if item.is_broken_link:
            self.add_css_class("dim-label")
        else:
            self.remove_css_class("dim-label")

    def set_selected(self, selected):
        if selected:
            self.add_css_class("selected")
        else:
            self.remove_css_class("selected")
        # SELECTED is a "boolean or undefined" state, stored as an int.
        self.update_state([Gtk.AccessibleState.SELECTED], [int(selected)])

    def set_cut(self, cut):
        if cut:
            self.add_css_class("cut")
        else:
            self.remove_css_class("cut")

    def set_drop_highlight(self, highlight):
        if highlight:
            self.add_css_class("drop-target")
        else:
            self.remove_css_class("drop-target")

    # Drag source

    def _on_drag_prepare(self, source, x, y):
        app = self.window.app
        if self.item.id not in app.selection:
            app.select([self.item.id])
        # The point held, in canvas coordinates (the drop arrives in them
        # too) and relative to the icon's slot.
        canvas = self.window.canvas
        ok, point = self.compute_point(canvas, Graphene.Point().init(x, y))
        self._grab = (point.x, point.y) if ok else (0, 0)
        grab = (self._grab[0] - self.slot[0], self._grab[1] - self.slot[1])
        return app.begin_drag(self.window, self.item.id, grab)

    def _on_drag_begin(self, source, drag):
        # Only the pictures of the dragged icons, arranged as on the desktop:
        # what moves is the icons, not their selection background or a box.
        window = self.window
        icons = [window.icons[i] for i in window.app.drag_ids if i in window.icons]
        icons.sort(key=lambda icon: icon is not self)
        pictures = []
        for icon in icons[:MAX_DRAG_ICONS]:
            ok, bounds = icon.picture_widget().compute_bounds(window.canvas)
            if ok:
                pictures.append((icon.picture_widget(), bounds))
        if not pictures:
            return
        left = min(b.get_x() for _w, b in pictures)
        top = min(b.get_y() for _w, b in pictures)
        right = max(b.get_x() + b.get_width() for _w, b in pictures)
        bottom = max(b.get_y() + b.get_height() for _w, b in pictures)
        snapshot = Gtk.Snapshot()
        for widget, bounds in pictures:
            snapshot.save()
            snapshot.translate(Graphene.Point().init(bounds.get_x() - left, bounds.get_y() - top))
            Gtk.WidgetPaintable.new(widget).snapshot(snapshot, bounds.get_width(),
                                                     bounds.get_height())
            snapshot.restore()
        paintable = snapshot.to_paintable(Graphene.Size().init(right - left, bottom - top))
        if paintable is None:
            return
        grab_x, grab_y = self._grab
        source.set_icon(paintable, int(grab_x - left), int(grab_y - top))

    def picture_widget(self):
        return self._overlay

    def _on_drag_end(self, source, drag, delete_data):
        self.window.app.end_drag()


class DesktopCanvas(Gtk.Fixed):
    """Holds the icons; reports its size so the grid can be computed.

    It covers the whole monitor and is the drop target of the desktop. The
    "desktop-canvas" style class removes the drop highlight GTK draws around
    a whole drop target: dropping on the desktop is not "into" anything.
    """

    def __init__(self, window):
        super().__init__()
        self.add_css_class("desktop-canvas")
        self._window = window
        self._size = (0, 0)

    def do_measure(self, orientation, for_size):
        # Gtk.Fixed asks for the extent of its children; an icon past the
        # edge would grow the window onto the neighbouring monitor. The
        # window's size comes from its monitor only.
        return 0, 0, -1, -1

    def do_size_allocate(self, width, height, baseline):
        Gtk.Fixed.do_size_allocate(self, width, height, baseline)
        if (width, height) != self._size:
            self._size = (width, height)
            GLib.idle_add(self._window.on_size_changed)


class DesktopWindow(Gtk.ApplicationWindow):
    def __init__(self, app, monitor):
        connector = monitor.get_connector() or ""
        # Resizable, so the shell can size it to the whole monitor (a fixed
        # size would be the one of the first configure). Users cannot resize
        # desktop windows: they have no frame and the shell treats them as
        # the desktop.
        super().__init__(application=app, decorated=False, resizable=True,
                         title=_("Desktop") + " " + DESKTOP_TITLE_TAG + connector)
        self.app = app
        self.monitor = monitor
        self.connector = connector
        self.add_css_class("deskence-desktop")
        self.update_property([Gtk.AccessibleProperty.LABEL], [_("Desktop")])
        self._overlay = None

        self.icons = {}
        self.icon_size = 64
        self.cell = model.CellSize(112, 124)
        self.area = model.Area(0, 0, 0, 0)
        self.workarea = model.Area(0, 0, 0, 0)
        self.surface = model.Surface(connector, 0, 0, self.cell)
        self._rubberband = None
        self._band_base = set()
        self._press_icon = None
        self._press_modifiers = False
        self.menu_point = (0, 0)
        self._menu = None
        self._drop_highlight = None

        self.canvas = DesktopCanvas(self)
        self._band = Gtk.DrawingArea(can_target=False)
        self._band.set_draw_func(self._draw_rubberband)
        overlay = Gtk.Overlay()
        overlay.set_child(self.canvas)
        overlay.add_overlay(self._band)
        self.set_child(overlay)
        self._overlay = overlay
        # GTK keeps toplevels within the "bounds" the shell suggests, which
        # are the work area, and would ignore the shell resizing the window
        # to the monitor. Requiring the monitor size keeps the window
        # covering the whole monitor, so clicks beside the dock reach it.
        monitor.connect("notify::geometry", lambda m, p: self._sync_size())
        self._sync_size()

        click = Gtk.GestureClick(button=0)
        click.connect("pressed", self._on_pressed)
        click.connect("released", self._on_released)
        self.canvas.add_controller(click)

        band = Gtk.GestureDrag(button=Gdk.BUTTON_PRIMARY)
        band.connect("drag-begin", self._on_band_begin)
        band.connect("drag-update", self._on_band_update)
        band.connect("drag-end", self._on_band_end)
        self.canvas.add_controller(band)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key_pressed)
        self.add_controller(keys)

        formats = Gdk.ContentFormats.new([INTERNAL_MIME, "text/uri-list"]).union(
            Gdk.ContentFormats.new_for_gtype(Gdk.FileList))
        drop = Gtk.DropTargetAsync(formats=formats,
                                   actions=Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        drop.connect("accept", lambda t, d: True)
        drop.connect("drag-enter", self._on_drop_motion)
        drop.connect("drag-motion", self._on_drop_motion)
        drop.connect("drag-leave", lambda *a: self._set_drop_highlight(None))
        drop.connect("drop", self._on_drop)
        self.canvas.add_controller(drop)

        app.install_window_actions(self)

    # -- Geometry and layout -------------------------------------------

    def _sync_size(self):
        geometry = self.monitor.get_geometry()
        self.set_default_size(geometry.width, geometry.height)
        self._overlay.set_size_request(geometry.width, geometry.height)

    def area_size(self):
        return self.canvas.get_width(), self.canvas.get_height()

    def layout_ready(self):
        """Whether the window has its size and knows its area.

        Right after it is created the window still has the size the shell
        gave it before covering the monitor; icons placed then would be
        remembered at wrong positions.
        """
        width, height = self.area_size()
        if width <= 0 or height <= 0:
            return False
        reported = self.app.shell_areas.get(self.connector)
        if reported is None:
            return not self.app.shell_areas.in_grace
        x, y, w, h = reported.area
        return (x + w <= width and y + h <= height) or not self.app.shell_areas.in_grace

    def _clip(self, rect):
        """A reported rectangle limited to the window, or None if empty."""
        width, height = self.area_size()
        x, y, w, h = rect
        left, top = min(max(x, 0), width), min(max(y, 0), height)
        right, bottom = min(max(x + w, left), width), min(max(y + h, top), height)
        if right - left <= 0 or bottom - top <= 0:
            return None
        return model.Area(left, top, right - left, bottom - top)

    def _available_area(self):
        """The part of the window icons may use: the whole window, minus the
        top bar as reported by the shell, if it did."""
        width, height = self.area_size()
        reported = self.app.shell_areas.get(self.connector)
        whole = model.Area(0, 0, width, height)
        if reported is None:
            return whole
        return self._clip(reported.area) or whole

    def _exclusions(self):
        """Docks inside the available area."""
        reported = self.app.shell_areas.get(self.connector)
        if reported is None:
            return ()
        result = []
        for rect in reported.exclusions:
            clipped = self._clip(rect)
            if clipped is not None:
                result.append((clipped.x, clipped.y, clipped.width, clipped.height))
        return result

    def _work_area(self):
        reported = self.app.shell_areas.get(self.connector)
        return (self._clip(reported.workarea) if reported else None) or self.area

    def on_size_changed(self):
        self.app.queue_layout()
        return GLib.SOURCE_REMOVE

    def line_height(self):
        metrics = self.get_pango_context().get_metrics(None, None)
        return metrics.get_height() / Pango.SCALE

    def update_geometry(self, icon_size_nick, corner):
        self.icon_size = model.ICON_SIZES.get(icon_size_nick, 64)
        self.cell = model.cell_size(icon_size_nick, self.line_height())
        self.area = self._available_area()
        self.workarea = self._work_area()
        self.surface = model.Surface(self.connector, self.area.width, self.area.height, self.cell,
                                     self._exclusions(), self.area.x, self.area.y, corner)

    def show_items(self, placed):
        """placed: list of (item, x, y) slot origins on this monitor."""
        wanted = {item.id for item, _x, _y in placed}
        for item_id in list(self.icons):
            if item_id not in wanted:
                self.canvas.remove(self.icons.pop(item_id))
        for item, x, y in placed:
            icon = self.icons.get(item.id)
            wx, wy = x + ICON_INSET, y
            if icon is None:
                icon = IconWidget(self, item)
                self.icons[item.id] = icon
                self.canvas.put(icon, wx, wy)
            else:
                icon.update(item)
                self.canvas.move(icon, wx, wy)
            icon.slot = (x, y)
            icon.set_selected(item.id in self.app.selection)
            icon.set_cut(item.id in self.app.cut_ids)

    def refresh_selection(self):
        for item_id, icon in self.icons.items():
            icon.set_selected(item_id in self.app.selection)
            icon.set_cut(item_id in self.app.cut_ids)

    def icon_at(self, x, y):
        widget = self.canvas.pick(x, y, Gtk.PickFlags.DEFAULT)
        while widget is not None and not isinstance(widget, IconWidget):
            if widget is self.canvas:
                return None
            widget = widget.get_parent()
        return widget

    def to_monitor(self, x, y):
        """Window coordinates to monitor coordinates (the same: the window
        covers its monitor)."""
        return x, y

    # -- Pointer -------------------------------------------------------

    def _on_pressed(self, gesture, n_press, x, y):
        button = gesture.get_current_button()
        state = gesture.get_current_event_state()
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        icon = self.icon_at(x, y)
        self._press_icon = icon
        self._press_modifiers = ctrl or shift

        if icon is None:
            if button in (Gdk.BUTTON_PRIMARY, Gdk.BUTTON_SECONDARY) and not (ctrl or shift):
                self.app.select([])
            if button == Gdk.BUTTON_SECONDARY:
                self.canvas.grab_focus()
                self.show_menu(x, y, None)
            return

        icon.grab_focus()
        item_id = icon.item.id
        if button == Gdk.BUTTON_PRIMARY:
            if ctrl:
                self.app.toggle_selected(item_id)
            elif shift:
                self.app.select(list(self.app.selection | {item_id}))
            elif item_id not in self.app.selection:
                self.app.select([item_id])
            if n_press == 2 and not self.app.single_click and not (ctrl or shift):
                self.app.open_items(self.app.selected_items(), self)
        elif button == Gdk.BUTTON_SECONDARY:
            if item_id not in self.app.selection:
                self.app.select([item_id])
            self.show_menu(x, y, icon)
        elif button == Gdk.BUTTON_MIDDLE:
            self.app.select([item_id])
            self.app.open_items([icon.item], self)

    def _on_released(self, gesture, n_press, x, y):
        if gesture.get_current_button() != Gdk.BUTTON_PRIMARY or not self.app.single_click:
            return
        icon = self.icon_at(x, y)
        if icon is not None and icon is self._press_icon and not self._press_modifiers \
                and n_press == 1 and not self.app.drag_in_progress:
            self.app.select([icon.item.id])
            self.app.open_items([icon.item], self)

    # -- Rubberband selection -----------------------------------------

    def _on_band_begin(self, gesture, x, y):
        if self.icon_at(x, y) is not None:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        state = gesture.get_current_event_state()
        additive = bool(state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK))
        self._band_base = set(self.app.selection) if additive else set()
        self._rubberband = (x, y, x, y)

    def _on_band_update(self, gesture, dx, dy):
        if self._rubberband is None:
            return
        x0, y0 = self._rubberband[:2]
        self._rubberband = (x0, y0, x0 + dx, y0 + dy)
        left, right = sorted((x0, x0 + dx))
        top, bottom = sorted((y0, y0 + dy))
        rect = Graphene.Rect().init(left, top, right - left, bottom - top)
        hit = set()
        for item_id, icon in self.icons.items():
            ok, bounds = icon.compute_bounds(self.canvas)
            if ok and bounds.intersection(rect)[0]:
                hit.add(item_id)
        self.app.select(list(self._band_base | hit), notify_windows=False)
        self.refresh_selection()
        self._band.queue_draw()

    def _on_band_end(self, gesture, dx, dy):
        self._rubberband = None
        self._band.queue_draw()
        self.app.refresh_selection()

    def _draw_rubberband(self, area, cr, width, height):
        if self._rubberband is None:
            return
        x0, y0, x1, y1 = self._rubberband
        color = self.app.accent_color()
        cr.rectangle(min(x0, x1) + 0.5, min(y0, y1) + 0.5, abs(x1 - x0), abs(y1 - y0))
        cr.set_source_rgba(color.red, color.green, color.blue, 0.25)
        cr.fill_preserve()
        cr.set_source_rgba(color.red, color.green, color.blue, 0.9)
        cr.set_line_width(1)
        cr.stroke()

    # -- Keyboard ------------------------------------------------------

    def _on_key_pressed(self, controller, keyval, keycode, state):
        directions = {
            Gdk.KEY_Left: (-1, 0), Gdk.KEY_Right: (1, 0),
            Gdk.KEY_Up: (0, -1), Gdk.KEY_Down: (0, 1),
        }
        if keyval in directions:
            self._move_focus(*directions[keyval], state)
            return True
        if keyval == Gdk.KEY_Menu or (keyval == Gdk.KEY_F10 and
                                      state & Gdk.ModifierType.SHIFT_MASK):
            self.show_menu_for_focus()
            return True
        if keyval == Gdk.KEY_Escape:
            self.app.select([])
            return True
        if keyval == Gdk.KEY_space:
            focus = self.get_focus()
            if isinstance(focus, IconWidget):
                if state & Gdk.ModifierType.CONTROL_MASK:
                    self.app.toggle_selected(focus.item.id)
                else:
                    self.app.select([focus.item.id])
                return True
        return False

    def _move_focus(self, dcol, drow, state):
        focus = self.get_focus()
        icons = list(self.icons.values())
        if not icons:
            return
        # Positions in cell units, so free placement navigates like the grid.
        def unit(icon):
            return icon.slot[0] / self.cell.width, icon.slot[1] / self.cell.height

        if not isinstance(focus, IconWidget):
            target = min(icons, key=lambda i: (unit(i)[0], unit(i)[1]))
        else:
            col, row = unit(focus)
            # Icons less than half a cell away in the direction count as
            # beside, not ahead.
            candidates = [i for i in icons if i is not focus and
                          (unit(i)[0] - col) * dcol + (unit(i)[1] - row) * drow > 0.5]
            if not candidates:
                return

            def distance(icon):
                c, r = unit(icon)
                along = (c - col) * dcol + (r - row) * drow
                across = abs((c - col) * drow) + abs((r - row) * dcol)
                return (across * 2 + along, along)
            target = min(candidates, key=distance)
        target.grab_focus()
        if state & Gdk.ModifierType.SHIFT_MASK:
            self.app.select(list(self.app.selection | {target.item.id}))
        elif not state & Gdk.ModifierType.CONTROL_MASK:
            self.app.select([target.item.id])

    # -- Menus ---------------------------------------------------------

    def show_menu_for_focus(self):
        focus = self.get_focus()
        if isinstance(focus, IconWidget):
            if focus.item.id not in self.app.selection:
                self.app.select([focus.item.id])
            ok, bounds = focus.compute_bounds(self.canvas)
            x = bounds.get_x() + bounds.get_width() / 2 if ok else 0
            y = bounds.get_y() + bounds.get_height() / 2 if ok else 0
            self.show_menu(x, y, focus, keyboard=True)
        else:
            width, height = self.area_size()
            self.show_menu(width / 2, height / 2, None, keyboard=True)

    def show_menu(self, x, y, icon, keyboard=False):
        """Context menu at a point of the window (= the monitor).

        Drawn by the shell when it runs us (see shellareas.py): a GTK menu is
        a Wayland popup, which mutter keeps inside the work area, so beside a
        dock it would open above the dock instead of at the click.
        """
        self.menu_point = (x, y)
        menu = self.app.build_item_menu() if icon else self.app.build_desktop_menu()
        areas = self.app.shell_areas
        if areas.shows_menus:
            areas.send_menu({
                "connector": self.connector, "x": round(x), "y": round(y),
                "keyboard": keyboard,
                "sections": shellmenu.serialize(menu, self.lookup_action, self._accel_label),
            })
            return
        if self._menu is not None:
            self._menu.unparent()
        self._menu = Gtk.PopoverMenu.new_from_model(menu)
        self._menu.set_has_arrow(False)
        self._menu.set_halign(Gtk.Align.START)
        self._menu.set_parent(self.canvas)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        self._menu.set_pointing_to(rect)
        self._menu.popup()

    def _accel_label(self, detailed_action):
        for accel in self.app.get_accels_for_action(detailed_action):
            ok, key, mods = Gtk.accelerator_parse(accel)
            if ok:
                return Gtk.accelerator_get_label(key, mods)
        return ""

    def activate_menu_action(self, action, target):
        """An item of a menu drawn by the shell was chosen."""
        parameter = None if target is None else GLib.Variant("s", target)
        self.activate_action(shellmenu.ACTION_PREFIX + action, parameter)

    def _popover_anchor(self, x, y):
        """Rectangle a text entry popover (rename, new folder) points at.

        These stay GTK popups, which mutter keeps inside the work area and
        would squeeze when opened in the band along a dock. They are small,
        so their point is only moved into the work area when it is outside.
        """
        area = self.workarea
        if area.width > 0 and area.height > 0:
            x = min(max(x, area.x), area.x + area.width - 1)
            y = min(max(y, area.y), area.y + area.height - 1)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        return rect

    def popup_at_point(self, widget):
        """Show a popover (rename, new folder) at the last menu point."""
        widget.set_parent(self.canvas)
        widget.set_pointing_to(self._popover_anchor(*self.menu_point))
        widget.connect("closed", lambda p: GLib.idle_add(p.unparent))
        widget.popup()

    def popup_at_icon(self, widget, item_id):
        icon = self.icons.get(item_id)
        if icon is None:
            return self.popup_at_point(widget)
        widget.set_parent(icon)
        widget.connect("closed", lambda p: GLib.idle_add(p.unparent))
        widget.popup()

    # -- Drop target ---------------------------------------------------

    def _set_drop_highlight(self, icon):
        if self._drop_highlight is not None and self._drop_highlight is not icon:
            self._drop_highlight.set_drop_highlight(False)
        self._drop_highlight = icon
        if icon is not None:
            icon.set_drop_highlight(True)

    def _drop_target_icon(self, x, y):
        icon = self.icon_at(x, y)
        if icon is None or not icon.item.is_drop_target:
            return None
        if self.app.drag_in_progress and icon.item.id in self.app.drag_ids:
            return None
        return icon

    def _on_drop_motion(self, target, drop, x, y):
        icon = self._drop_target_icon(x, y)
        self._set_drop_highlight(icon)
        actions = drop.get_actions()
        internal = drop.get_drag() is not None and self.app.drag_in_progress
        if icon is not None and icon.item.kind == "trash":
            return Gdk.DragAction.MOVE if actions & Gdk.DragAction.MOVE else Gdk.DragAction(0)
        if internal and icon is None:
            return Gdk.DragAction.MOVE
        if actions & Gdk.DragAction.MOVE:
            return Gdk.DragAction.MOVE
        return actions & Gdk.DragAction.COPY

    def _on_drop(self, target, drop, x, y):
        icon = self._drop_target_icon(x, y)
        self._set_drop_highlight(None)
        internal = drop.get_drag() is not None and self.app.drag_in_progress
        if internal and icon is None:
            self.app.drop_internal(self, x, y)
            drop.finish(Gdk.DragAction.MOVE)
            return True

        def read_done(drop_, result):
            try:
                value = drop_.read_value_finish(result)
                files = value.get_files() if value else []
            except GLib.Error:
                files = []
            if not files:
                drop_.finish(Gdk.DragAction(0))
                return
            action = drop_.get_actions()
            copy = not action & Gdk.DragAction.MOVE
            self.app.drop_files(self, x, y, files, icon.item if icon else None, copy)
            drop_.finish(Gdk.DragAction.COPY if copy else Gdk.DragAction.MOVE)

        drop.read_value_async(Gdk.FileList, GLib.PRIORITY_DEFAULT, None, read_done)
        return True
