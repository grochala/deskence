// SPDX-License-Identifier: GPL-3.0-or-later
//
// Previews of the windows of a running application, shown when the pointer
// rests on its dock icon.
//
// One panel at a time (WindowPreviews belongs to the DockManager). It opens
// after a short delay, on the side of the icon that faces the inside of the
// screen, and stays while the pointer is on the icon or the panel; the
// panel's padding on the dock side reaches back towards the dock, so moving
// across the gap never closes it. Each window is a live clone of its actor
// (nothing is captured or written anywhere) with its title; minimized
// windows and windows without content show the application icon instead,
// never a black or broken image. Clicking a preview activates exactly that
// window (Main.activateWindow: unminimizes it and switches workspace when
// needed); hovering only highlights. The panel is top chrome that reserves
// no space and never changes the work area.
//
// The windows listed are the ones the dock counts for the application
// (DockManager.windowsForApp), so the dock's own workspace filter applies.
//
// Keyboard: the arrow pointing away from the dock opens the panel from a
// focused dock icon; arrows move between previews, Enter activates, Escape
// or the arrow back towards the dock closes it. When the pointer enters the
// panel, the panel takes the keyboard (so Escape works) and gives it back
// to the window that had it when it closes without a window chosen.
//
// Closing: leaving both the icon and the panel (after a short delay),
// Escape, a click, the application menu, a drag, the overview, scrolling
// the dock, the setting turned off, and destroying the dock or the
// extension. Everything the panel created - clones, signal handlers,
// timeouts - goes away with it.
//
// Each preview has a close button in its corner, shown on hover and on
// keyboard focus (also Delete on a focused preview). It asks the window to
// close, the same way its own close button does, so the application may
// ask about unsaved changes; the preview goes away only when the window
// does. Its menu (right click, Menu key) toggles "Always on Top"; a pin
// next to the title shows that state.
//
// Resting the pointer on a preview peeks at its window (peek.js): the
// window is shown over the dimmed others without focusing or moving
// anything; leaving the preview, Escape or a click ends it, and a click
// then activates the window as before.

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import Pango from 'gi://Pango';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

import {setVertical} from './appIcon.js';
import {previewLayout} from './logic.js';
import {WindowPeek, hasContent} from './peek.js';

// Delay before the panel opens on hover, before it closes once the pointer
// left the icon and the panel, and before it moves to another icon while
// it is open.
const SHOW_DELAY = 450;
const HIDE_DELAY = 350;
const SWITCH_DELAY = 120;
// Thumbnail size (logical pixels); smaller when many windows must fit.
const THUMB_WIDTH = 200;
const THUMB_HEIGHT = 128;
const MIN_THUMB_WIDTH = 120;
// Distance between the dock (with magnified icons) and the panel.
const GAP = 8;
// Room a preview takes besides its thumbnail (stylesheet.css): padding
// around it and spacing to the next one along the row, and the title
// below it.
const ITEM_EXTRA = 20;
const TITLE_EXTRA = 28;
// Padding of the panel, the name of the application above the previews.
const PANEL_EXTRA = 12;
const HEADER_EXTRA = 30;
const FALLBACK_ICON_SIZE = 48;
const FADE_TIME = 120;
// Resting on a preview before its window is peeked at; moving to another
// preview while peeking; leaving the previews before the peek ends (moving
// across the gap between two previews keeps it).
const PEEK_DELAY = 600;
const PEEK_SWITCH_DELAY = 150;
const PEEK_END_DELAY = 200;

// A thumbnail: a clipped clone of the window actor scaled so the window's
// frame (without shadows) fills width x height, or the application icon.
function createThumbnail(app, window, width, height) {
    const box = new St.Widget({
        style_class: 'deskence-window-preview-thumbnail',
        width,
        height,
        clip_to_allocation: true,
        layout_manager: new Clutter.FixedLayout(),
    });
    const actor = window.get_compositor_private();
    if (hasContent(window)) {
        const frame = window.get_frame_rect();
        const scale = Math.min(width / Math.max(1, frame.width), height / Math.max(1, frame.height));
        const shownWidth = frame.width * scale;
        const shownHeight = frame.height * scale;
        const clone = new Clutter.Clone({
            source: actor,
            width: actor.width * scale,
            height: actor.height * scale,
            x: (actor.x - frame.x) * scale + (width - shownWidth) / 2,
            y: (actor.y - frame.y) * scale + (height - shownHeight) / 2,
        });
        box.add_child(clone);
        return box;
    }
    box.add_style_class_name('deskence-window-preview-fallback');
    const icon = app.create_icon_texture(FALLBACK_ICON_SIZE);
    icon.set_position(Math.round((width - FALLBACK_ICON_SIZE) / 2),
        Math.round((height - FALLBACK_ICON_SIZE) / 2));
    box.add_child(icon);
    return box;
}

// The windows of an application in a stable order (the order they were
// opened, as clicking the icon cycles through them), so previews do not
// move around after one was chosen.
function previewWindows(manager, app) {
    return manager.windowsForApp(app).sort(
        (a, b) => a.get_stable_sequence() - b.get_stable_sequence());
}

export class WindowPreviews {
    constructor(manager) {
        this._manager = manager;
        this._panel = null;
        this._frame = null;
        this._list = null;
        this._scrollView = null;
        this._icon = null;
        this._dock = null;
        this._pending = null;
        this._showId = 0;
        this._hideId = 0;
        this._previousFocus = null;
        this._activated = false;
        this._fromKeyboard = false;
        this._peek = new WindowPeek();
        this._peekId = 0;
        this._menu = null;
        this._menuManager = null;
    }

    get enabled() {
        return this._manager.windowPreviews;
    }

    isOpenFor(dock) {
        return this._panel !== null && this._dock === dock;
    }

    get isOpen() {
        return this._panel !== null;
    }

    // Whether previews may open for this icon; the dock then shows no
    // tooltip for it, the panel names the application.
    available(icon) {
        return this.enabled && Boolean(icon.app) &&
            this._manager.windowsForApp(icon.app).length > 0;
    }

    // --- Hover --------------------------------------------------------

    // The pointer entered or left a dock application icon.
    iconHoverChanged(icon, dock) {
        if (icon.hover) {
            this._cancelHide();
            if (this._icon === icon && this._panel)
                return;
            if (!this._canShow(icon, dock)) {
                this._cancelShow();
                if (this._panel)
                    this._scheduleHide();
                return;
            }
            this._cancelShow();
            this._pending = {icon, dock};
            this._showId = GLib.timeout_add(GLib.PRIORITY_DEFAULT,
                this._panel ? SWITCH_DELAY : SHOW_DELAY, () => {
                    this._showId = 0;
                    const pending = this._pending;
                    this._pending = null;
                    if (pending?.icon.hover && this._canShow(pending.icon, pending.dock))
                        this.open(pending.icon, pending.dock, false);
                    return GLib.SOURCE_REMOVE;
                });
        } else {
            if (this._pending?.icon === icon)
                this._cancelShow();
            if (this._panel)
                this._scheduleHide();
        }
    }

    _canShow(icon, dock) {
        return this.enabled && dock.shown && !this._manager.dragInProgress &&
            !Main.overview.visible && !icon._menu?.isOpen &&
            this._manager.windowsForApp(icon.app).length > 0;
    }

    _cancelShow() {
        if (this._showId)
            GLib.source_remove(this._showId);
        this._showId = 0;
        this._pending = null;
    }

    _cancelHide() {
        if (this._hideId)
            GLib.source_remove(this._hideId);
        this._hideId = 0;
    }

    _scheduleHide() {
        if (this._hideId)
            return;
        this._hideId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, HIDE_DELAY, () => {
            this._hideId = 0;
            if (!this._panel?.hover && !this._icon?.hover && !this._menu?.isOpen)
                this.close();
            return GLib.SOURCE_REMOVE;
        });
    }

    // --- Panel --------------------------------------------------------

    // Opens the panel for an icon. From the keyboard, the first preview
    // gets the focus at once.
    open(icon, dock, fromKeyboard) {
        this._cancelShow();
        this._cancelHide();
        const windows = previewWindows(this._manager, icon.app);
        if (windows.length === 0) {
            this.close();
            return false;
        }
        this.close();
        this._icon = icon;
        this._dock = dock;
        this._fromKeyboard = fromKeyboard;
        this._activated = false;
        this._previousFocus = null;

        const vertical = dock.position !== 'bottom';
        // The outer actor takes the pointer over the gap towards the dock:
        // its padding on that side is reactive.
        this._panel = new St.Widget({
            style_class: 'deskence-window-previews',
            reactive: true,
            track_hover: true,
            layout_manager: new Clutter.BinLayout(),
            opacity: 0,
        });
        const name = icon.app.get_name();
        this._frame = new St.BoxLayout({
            style_class: 'popup-menu-content deskence-window-previews-content',
            reactive: true,
            accessible_name: _('Windows of %s').replace('%s', name),
        });
        setVertical(this._frame, true);
        // The name of the application: the dock shows no tooltip while
        // previews can open (see DockItem).
        this._frame.add_child(new St.Label({
            style_class: 'deskence-window-previews-header',
            text: name,
        }));
        this._list = new St.BoxLayout({style_class: 'deskence-window-previews-list'});
        setVertical(this._list, vertical);
        this._frame.add_child(this._list);
        this._panel.add_child(this._frame);
        this._panel.connect('notify::hover', () => this._onPanelHover());
        this._panel.connect('key-press-event', (_a, event) => this._onKeyPress(event));

        icon.app.connectObject('windows-changed', () => this._refresh(), this._panel);
        global.workspace_manager.connectObject('active-workspace-changed',
            () => this._refresh(), this._panel);
        // A new window (such as a question about unsaved changes) must not
        // stay hidden under the veil of a peek.
        global.display.connectObject('window-created', () => this._endPeek(true), this._panel);
        this._menuManager = new PopupMenu.PopupMenuManager(this._panel);

        Main.layoutManager.addTopChrome(this._panel);
        this._fill(windows);
        this._panel.ease({opacity: 255, duration: FADE_TIME, mode: Clutter.AnimationMode.EASE_OUT_QUAD});

        if (fromKeyboard)
            this._list.get_first_child()?.grab_key_focus();
        dock.syncVisibility();
        return true;
    }

    // (Re)creates the previews: thumbnails as large as fit along the dock;
    // when even the smallest do not fit, the list scrolls.
    _fill(windows) {
        const dock = this._dock;
        this._list.destroy_all_children();
        const monitor = dock.monitor;
        const area = Main.layoutManager.getWorkAreaForMonitor(dock.monitorIndex);
        const vertical = dock.position !== 'bottom';
        const room = (vertical ? area.height - HEADER_EXTRA : area.width) - 4 * GAP - PANEL_EXTRA;
        const layout = previewLayout(windows.length, room, {
            width: THUMB_WIDTH,
            height: THUMB_HEIGHT,
            minWidth: MIN_THUMB_WIDTH,
            vertical,
            itemExtra: ITEM_EXTRA,
            titleExtra: TITLE_EXTRA,
        });

        for (const window of windows)
            this._list.add_child(this._createItem(window, layout.width, layout.height));

        if (layout.scroll && !this._scrollView) {
            this._frame.remove_child(this._list);
            this._scrollView = new St.ScrollView({
                style_class: 'deskence-window-previews-scroll',
                hscrollbar_policy: vertical ? St.PolicyType.NEVER : St.PolicyType.AUTOMATIC,
                vscrollbar_policy: vertical ? St.PolicyType.AUTOMATIC : St.PolicyType.NEVER,
                overlay_scrollbars: true,
            });
            this._scrollView.set_child(this._list);
            this._frame.add_child(this._scrollView);
        }
        if (this._scrollView) {
            const [, natWidth] = this._list.get_preferred_width(-1);
            const [, natHeight] = this._list.get_preferred_height(natWidth);
            if (vertical)
                this._scrollView.set_size(natWidth, Math.min(natHeight, room));
            else
                this._scrollView.set_size(Math.min(natWidth, room), natHeight);
        }
        this._place(monitor, area);
    }

    _createItem(window, width, height) {
        const app = this._icon.app;
        const item = new St.Button({
            style_class: 'popup-menu-item deskence-window-preview',
            can_focus: true,
            track_hover: true,
            reactive: true,
            accessible_name: window.get_title() ?? app.get_name(),
            button_mask: (St.ButtonMask.PRIMARY ?? St.ButtonMask.ONE) |
                (St.ButtonMask.SECONDARY ?? St.ButtonMask.THREE),
        });
        const box = new St.BoxLayout({style_class: 'deskence-window-preview-box'});
        setVertical(box, true);

        // The thumbnail with the close button in its corner.
        const thumb = new St.Widget({layout_manager: new Clutter.BinLayout()});
        thumb.add_child(createThumbnail(app, window, width, height));
        const close = new St.Button({
            style_class: 'deskence-window-preview-close',
            child: new St.Icon({icon_name: 'window-close-symbolic'}),
            can_focus: true,
            track_hover: true,
            accessible_name: _('Close Window'),
            x_align: Clutter.ActorAlign.END,
            y_align: Clutter.ActorAlign.START,
            x_expand: true,
            y_expand: true,
            opacity: 0,
        });
        close.connect('clicked', () => this._closeWindow(window));
        thumb.add_child(close);

        const titleRow = new St.BoxLayout({
            style_class: 'deskence-window-preview-title-row',
            x_align: Clutter.ActorAlign.CENTER,
            width,
        });
        const pin = new St.Icon({
            style_class: 'deskence-window-preview-pin',
            icon_name: 'view-pin-symbolic',
            accessible_name: _('Always on Top'),
            y_align: Clutter.ActorAlign.CENTER,
        });
        const title = new St.Label({
            style_class: 'deskence-window-preview-title',
            text: window.get_title() ?? app.get_name(),
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        title.clutter_text.ellipsize = Pango.EllipsizeMode.END;
        titleRow.add_child(pin);
        titleRow.add_child(title);
        box.add_child(thumb);
        box.add_child(titleRow);
        item.set_child(box);
        item.label_actor = title;

        const syncAbove = () => {
            pin.visible = window.is_above();
        };
        syncAbove();
        // leaving: the actor losing the focus (key-focus-out comes before
        // the stage moves the focus).
        const syncClose = (leaving = null) => {
            const focus = global.stage.key_focus === leaving ? null : global.stage.key_focus;
            const shown = item.hover || focus === item || focus === close;
            close.ease({opacity: shown ? 255 : 0, duration: FADE_TIME,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD});
        };

        window.connectObject('notify::title', () => {
            const text = window.get_title() ?? app.get_name();
            title.text = text;
            item.accessible_name = text;
        }, 'notify::above', syncAbove, item);
        // Content may become available or go away (minimized, shown).
        window.connectObject('notify::minimized', () => this._refresh(), item);
        item.connect('notify::hover', () => {
            syncClose();
            if (item.hover)
                item.grab_key_focus();
            this._peekHoverChanged(item, window);
        });
        for (const actor of [item, close]) {
            actor.connect('key-focus-in', () => syncClose());
            actor.connect('key-focus-out', () => syncClose(actor));
        }
        item.connect('clicked', (_b, button) => {
            if (button === Clutter.BUTTON_SECONDARY)
                this._openMenu(item, window);
            else
                this._activate(window);
        });
        item.connect('popup-menu', () => this._openMenu(item, window));
        item.connect('key-press-event', (_a, event) => {
            if (event.get_key_symbol() !== Clutter.KEY_Delete)
                return Clutter.EVENT_PROPAGATE;
            this._closeWindow(window);
            return Clutter.EVENT_STOP;
        });
        return item;
    }

    // Asks the window to close, like its own close button: the
    // application may ask about unsaved changes first. The preview stays
    // until the window really goes away (windows-changed).
    _closeWindow(window) {
        this._endPeek(true);
        if (window.can_close())
            window.delete(global.get_current_time());
    }

    // --- Menu ---------------------------------------------------------

    _openMenu(item, window) {
        this._endPeek(true);
        this._menu?.destroy();
        const menu = new PopupMenu.PopupMenu(item, 0.5, this._dock.menuSide);
        this._menu = menu;
        Main.uiGroup.add_child(menu.actor);
        this._menuManager.addMenu(menu);
        const above = new PopupMenu.PopupSwitchMenuItem(_('Always on Top'), window.is_above());
        above.connect('toggled', (_i, state) => {
            if (state)
                window.make_above();
            else
                window.unmake_above();
        });
        menu.addMenuItem(above);
        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const close = menu.addAction(_('Close Window'), () => this._closeWindow(window));
        close.setSensitive(window.can_close());
        window.connectObject('unmanaged', () => menu.close(), menu);
        menu.connect('open-state-changed', (_m, open) => {
            if (open)
                return;
            window.disconnectObject(menu);
            // Destroyed after the closing animation; back to the panel.
            GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
                if (this._menu === menu)
                    this._menu = null;
                menu.destroy();
                if (this._panel && !this._panel.hover && !this._icon?.hover)
                    this._scheduleHide();
                return GLib.SOURCE_REMOVE;
            });
        });
        menu.open();
        menu.actor.navigate_focus(null, St.DirectionType.TAB_FORWARD, false);
    }

    // --- Peeking ------------------------------------------------------

    get _peekEnabled() {
        return this._manager.windowPeek && !this._menu?.isOpen;
    }

    _cancelPeekTimer() {
        if (this._peekId)
            GLib.source_remove(this._peekId);
        this._peekId = 0;
    }

    _peekHoverChanged(item, window) {
        if (!this._peekEnabled)
            return;
        this._cancelPeekTimer();
        if (item.hover) {
            if (this._peek.window === window)
                return;
            const delay = this._peek.active ? PEEK_SWITCH_DELAY : PEEK_DELAY;
            this._peekId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, delay, () => {
                this._peekId = 0;
                if (item.hover && this._panel && this._peekEnabled)
                    this._peek.show(window, this._icon.app, this._peekRoom());
                return GLib.SOURCE_REMOVE;
            });
        } else if (this._peek.active) {
            this._peekId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, PEEK_END_DELAY, () => {
                this._peekId = 0;
                this._endPeek();
                return GLib.SOURCE_REMOVE;
            });
        }
    }

    // The part of the work area beside the panel, for enlarged windows.
    _peekRoom() {
        const area = Main.layoutManager.getWorkAreaForMonitor(this._dock.monitorIndex);
        const [x, y] = this._frame.get_transformed_position();
        const [width, height] = this._frame.get_transformed_size();
        const right = area.x + area.width;
        switch (this._dock.position) {
        case 'left':
            return {x: x + width + GAP, y: area.y, width: right - x - width - GAP, height: area.height};
        case 'right':
            return {x: area.x, y: area.y, width: x - GAP - area.x, height: area.height};
        default:
            return {x: area.x, y: area.y, width: area.width, height: y - GAP - area.y};
        }
    }

    _endPeek(immediate = false) {
        this._cancelPeekTimer();
        this._peek.hide(immediate);
    }

    // Next to the icon, on the side facing the inside of the screen, beyond
    // where magnified icons can reach; kept on the dock's monitor.
    _place(monitor, area) {
        const panel = this._panel;
        const dock = this._dock;
        const item = this._icon.get_parent() ?? this._icon;
        const [across] = dock.magnifier.overflow();
        const reach = across + GAP;
        const extents = item.get_transformed_extents();
        const rect = dock.rect;
        // The padding towards the dock is reactive: no gap to cross.
        const side = {bottom: 'bottom', left: 'left', right: 'right'}[dock.position];
        panel.set_style(`padding-${side}: ${reach}px;`);
        const [, width] = panel.get_preferred_width(-1);
        const [, height] = panel.get_preferred_height(width);
        let x, y;
        const centerX = extents.get_x() + extents.get_width() / 2;
        const centerY = extents.get_y() + extents.get_height() / 2;
        switch (dock.position) {
        case 'left':
            x = rect.x + rect.width;
            y = centerY - height / 2;
            break;
        case 'right':
            x = rect.x - width;
            y = centerY - height / 2;
            break;
        default:
            x = centerX - width / 2;
            y = rect.y - height;
        }
        // Off the screen edges and the top bar by the same gap.
        const top = Math.max(monitor.y, area.y) + GAP;
        x = Math.clamp(x, monitor.x + GAP, Math.max(monitor.x + GAP,
            monitor.x + monitor.width - width - GAP));
        y = Math.clamp(y, top, Math.max(top, monitor.y + monitor.height - height - GAP));
        panel.set_position(Math.round(x), Math.round(y));
        panel.set_size(width, height);
    }

    // Windows opened, closed, minimized or moved to another workspace.
    _refresh() {
        if (!this._panel)
            return;
        const windows = previewWindows(this._manager, this._icon.app);
        if (windows.length === 0) {
            this.close();
            return;
        }
        const focused = this._list.get_children().indexOf(global.stage.key_focus);
        this._fill(windows);
        if (focused >= 0) {
            const children = this._list.get_children();
            children[Math.min(focused, children.length - 1)]?.grab_key_focus();
        }
    }

    // Pointer on the panel: it takes the keyboard (Escape, arrows, Enter)
    // until it closes; the window that had the focus gets it back then,
    // unless a window was chosen.
    _onPanelHover() {
        if (this._panel.hover) {
            this._cancelHide();
            if (!this._panelHasFocus()) {
                this._previousFocus ??= global.display.focus_window;
                this._list.get_first_child()?.grab_key_focus();
            }
        } else {
            this._scheduleHide();
        }
    }

    _panelHasFocus() {
        const focus = global.stage.key_focus;
        return focus !== null && this._panel.contains(focus);
    }

    _onKeyPress(event) {
        const key = event.get_key_symbol();
        if (key === Clutter.KEY_Escape) {
            // A peek first, then the panel.
            if (this._peek.active)
                this._endPeek();
            else
                this.close();
            return Clutter.EVENT_STOP;
        }
        const directions = {
            [Clutter.KEY_Left]: St.DirectionType.LEFT,
            [Clutter.KEY_Right]: St.DirectionType.RIGHT,
            [Clutter.KEY_Up]: St.DirectionType.UP,
            [Clutter.KEY_Down]: St.DirectionType.DOWN,
            [Clutter.KEY_Tab]: St.DirectionType.TAB_FORWARD,
            [Clutter.KEY_ISO_Left_Tab]: St.DirectionType.TAB_BACKWARD,
        };
        const direction = directions[key];
        if (direction === undefined)
            return Clutter.EVENT_PROPAGATE;
        // Back to the dock: the arrow pointing at it from the panel.
        const back = {
            bottom: Clutter.KEY_Down,
            left: Clutter.KEY_Left,
            right: Clutter.KEY_Right,
        }[this._dock.position];
        if (key === back) {
            this.close();
            return Clutter.EVENT_STOP;
        }
        const focus = global.stage.key_focus;
        this._list.navigate_focus(this._list.contains(focus) ? focus : null, direction, true);
        return Clutter.EVENT_STOP;
    }

    _activate(window) {
        this._activated = true;
        this._endPeek(true);
        this.close();
        Main.activateWindow(window);
        Main.overview.hide();
    }

    // Closes the panel. When it had the keyboard, the focus goes back where
    // it came from: the dock icon when the panel was opened from the
    // keyboard, otherwise the window that had it.
    close() {
        this._cancelShow();
        this._cancelHide();
        this._endPeek(true);
        if (!this._panel)
            return;
        this._menu?.destroy();
        this._menu = null;
        this._menuManager = null;
        const panel = this._panel;
        const icon = this._icon;
        const dock = this._dock;
        const hadFocus = this._panelHasFocus();
        const previous = this._previousFocus;
        this._panel = null;
        this._frame = null;
        this._list = null;
        this._scrollView = null;
        this._icon = null;
        this._dock = null;
        this._previousFocus = null;

        if (hadFocus) {
            if (this._fromKeyboard && icon?.get_stage()) {
                icon.grab_key_focus();
            } else {
                global.stage.set_key_focus(null);
                if (!this._activated && previous?.get_compositor_private() &&
                    !previous.minimized &&
                    previous.located_on_workspace(global.workspace_manager.get_active_workspace()))
                    previous.focus(global.get_current_time());
            }
        }
        panel.destroy();
        dock?.syncVisibility();
    }

    // The dock goes away (rebuild, monitor change).
    closeFor(dock) {
        if (this._dock === dock || this._pending?.dock === dock)
            this.close();
    }

    // The peek setting was turned off.
    syncPeek() {
        if (!this._manager.windowPeek)
            this._endPeek(true);
    }

    destroy() {
        this.close();
        this._peek.destroy();
        this._manager = null;
    }
}
