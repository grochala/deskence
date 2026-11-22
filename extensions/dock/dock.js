// SPDX-License-Identifier: GPL-3.0-or-later
//
// The dock: one instance per selected monitor, managed by DockManager.
//
// Pinned applications are GNOME's favorites (org.gnome.shell favorite-apps),
// shared with the overview and the application grid; there is no second list.

import Clutter from 'gi://Clutter';
import GdkPixbuf from 'gi://GdkPixbuf';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as AppFavorites from 'resource:///org/gnome/shell/ui/appFavorites.js';
import * as DND from 'resource:///org/gnome/shell/ui/dnd.js';
import * as IconGrid from 'resource:///org/gnome/shell/ui/iconGrid.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

import {DockAppIcon, isNormalWindow, setVertical} from './appIcon.js';
import {LocationsModel, LocationIcon} from './locations.js';
import {appsButtonMaxScale, backgroundColor, cssColor, distributionLogoNames, effectiveBackground,
    iconRenderSize, inkForBackground, insertionIndex, isSeeThrough, mixBackground, overviewProgress,
    panelLook, scrollToReveal, symbolicLogoNames, viewportLayout} from './logic.js';
import {logoSilhouette} from './logo.js';
import {Magnifier} from './magnifier.js';
import {OverviewBackdrop} from './overviewBackdrop.js';
import {AppGridTiles} from './appFolders.js';
import {FileDrop} from './fileDrop.js';
import {LauncherEntries} from './launcherEntry.js';
import {StackIcon, StackPanel, StacksModel} from './stacks.js';
import {WindowPreviews} from './windowPreviews.js';

const ANIMATION_TIME = 200;
const AUTOHIDE_DELAY = 500;
const REVEAL_DELAY = 150;
const LABEL_DELAY = 300;
// An application that cannot open dragged files is dimmed this far.
const REFUSED_OPACITY = 120;
// Wheel steps and edge scrolling while dragging, in logical pixels.
const SCROLL_STEP = 48;
const DRAG_SCROLL_STEP = 8;
const DRAG_SCROLL_INTERVAL = 16;
const APPS_ICON_NAME = 'view-app-grid-symbolic';
// Custom icons larger than this are not loaded.
const MAX_CUSTOM_ICON_BYTES = 4 * 1024 * 1024;
const SETTINGS_APP_ID = 'io.github.deskence.Deskence';
const SETTINGS_APP_PATH = '/io/github/deskence/Deskence';

// Shows a page of Deskence through its D-Bus activated
// "show-page" action, like "Desktop Settings" in the desktop menu: a running
// instance switches its window to the page, otherwise D-Bus starts one. The
// activation token lets the existing window come to the front.
function openSettingsPage(page) {
    const platformData = {};
    const appInfo = Gio.DesktopAppInfo.new(`${SETTINGS_APP_ID}.desktop`);
    if (appInfo) {
        const context = global.create_app_launch_context(0, -1);
        const token = context.get_startup_notify_id(appInfo, []);
        if (token) {
            platformData['activation-token'] = new GLib.Variant('s', token);
            platformData['desktop-startup-id'] = new GLib.Variant('s', token);
        }
    }
    Gio.DBus.session.call(SETTINGS_APP_ID, SETTINGS_APP_PATH, 'org.freedesktop.Application',
        'ActivateAction',
        new GLib.Variant('(sava{sv})', ['show-page', [new GLib.Variant('s', page)], platformData]),
        null, Gio.DBusCallFlags.NONE, -1, null, (bus, res) => {
            try {
                bus.call_finish(res);
            } catch (e) {
                Main.notifyError(_('Cannot open Deskence'), e.message);
            }
        });
    Main.overview.hide();
}

// A dock item: holds an icon and shows its name as a tooltip, like the
// items of the GNOME dash.
const DockItem = GObject.registerClass({
    GTypeName: 'DeskenceDockItem',
}, class DockItem extends St.Widget {
    _init(dock, child, labelText) {
        super._init({
            style_class: 'dash-item-container',
            layout_manager: new Clutter.BinLayout(),
        });
        this._dock = dock;
        this.child = child;
        this.add_child(child);
        this._labelText = labelText;
        this._dropText = null;
        this._labelTimeoutId = 0;
        this.label = null;
        child.connectObject('notify::hover', () => this._syncLabel(), this);
        child.connectObject(
            'key-focus-in', () => this._syncLabel(),
            'key-focus-out', () => this._syncLabel(), this);
        child.connectObject('clicked', () => this.hideLabel(), this);
        this.connect('destroy', () => {
            this._clearTimeout();
            this.label?.destroy();
            this.label = null;
        });
    }

    setLabelText(text) {
        this._labelText = text;
        if (this.label && this._dropText === null)
            this.label.text = text;
    }

    // While files are dragged over the item: what a drop does, shown at
    // once in place of the name; null takes it away.
    setDropText(text) {
        if (text === this._dropText)
            return;
        this._dropText = text;
        this._clearTimeout();
        if (text === null)
            this.hideLabel();
        else
            this.showLabel();
    }

    _clearTimeout() {
        if (this._labelTimeoutId) {
            GLib.source_remove(this._labelTimeoutId);
            this._labelTimeoutId = 0;
        }
    }

    _syncLabel() {
        if (this.child.has_key_focus())
            this._dock.ensureVisible(this);
        const menuOpen = this.child._menu?.isOpen;
        // Window previews name the application themselves.
        const previews = this.child.app !== undefined &&
            this._dock.manager.previews.available(this.child);
        const wanted = (this.child.hover || this.child.has_key_focus()) && !menuOpen && !previews;
        this._clearTimeout();
        if (!wanted) {
            this.hideLabel();
            return;
        }
        this._labelTimeoutId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, LABEL_DELAY, () => {
            this._labelTimeoutId = 0;
            this.showLabel();
            return GLib.SOURCE_REMOVE;
        });
    }

    showLabel() {
        const text = this._dropText ?? this._labelText;
        if (!text)
            return;
        if (!this.label) {
            this.label = new St.Label({style_class: 'dash-label'});
            Main.layoutManager.addChrome(this.label);
        }
        const label = this.label;
        label.text = text;
        label.opacity = 0;
        label.show();

        // The button may be magnified: place the label next to what is drawn.
        const extents = this.child.get_transformed_extents();
        const stageX = extents.get_x();
        const stageY = extents.get_y();
        const width = extents.get_width();
        const height = extents.get_height();
        const [labelWidth, labelHeight] = label.get_size();
        const offset = label.get_theme_node().get_length('-y-offset') || 8;
        const monitor = this._dock.monitor;
        let x, y;
        switch (this._dock.position) {
        case 'left':
            x = stageX + width + offset;
            y = stageY + Math.floor((height - labelHeight) / 2);
            break;
        case 'right':
            x = stageX - labelWidth - offset;
            y = stageY + Math.floor((height - labelHeight) / 2);
            break;
        default:
            x = stageX + Math.floor((width - labelWidth) / 2);
            y = stageY - labelHeight - offset;
        }
        x = Math.clamp(x, monitor.x, monitor.x + monitor.width - labelWidth);
        y = Math.clamp(y, monitor.y, monitor.y + monitor.height - labelHeight);
        label.set_position(Math.round(x), Math.round(y));
        label.ease({opacity: 255, duration: 150, mode: Clutter.AnimationMode.EASE_OUT_QUAD});
    }

    hideLabel() {
        this._clearTimeout();
        this.label?.ease({
            opacity: 0,
            duration: 100,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => this.label?.hide(),
        });
    }
});

// The scrollable part of the dock. The item list keeps its natural length;
// when it is longer than the space left by the dock, only the list scrolls
// (the applications button outside it stays). When there is room to spare
// (whole-edge dock) the list starts at the top or left, whichever end the
// applications button is at; the spare room stays after the list.
// Geometry: logic.js viewportLayout().
const ViewportLayout = GObject.registerClass({
    GTypeName: 'DeskenceDockViewportLayout',
}, class ViewportLayout extends Clutter.LayoutManager {
    _init(dock) {
        super._init();
        this._dock = dock;
    }

    vfunc_get_preferred_width(_container, forHeight) {
        const [min, nat] = this._dock.box.get_preferred_width(forHeight);
        return this._dock.vertical ? [min, nat] : [0, nat];
    }

    vfunc_get_preferred_height(_container, forWidth) {
        const [min, nat] = this._dock.box.get_preferred_height(this._dock.vertical ? -1 : forWidth);
        return this._dock.vertical ? [0, nat] : [min, nat];
    }

    vfunc_allocate(_container, box) {
        this._dock.allocateViewport(box);
    }
});

const ShowAppsButton = GObject.registerClass({
    GTypeName: 'DeskenceDockShowAppsButton',
}, class ShowAppsButton extends St.Button {
    _init(dock) {
        super._init({
            style_class: 'show-apps',
            track_hover: true,
            can_focus: true,
            toggle_mode: true,
            button_mask: (St.ButtonMask.PRIMARY ?? St.ButtonMask.ONE) |
                (St.ButtonMask.SECONDARY ?? St.ButtonMask.THREE),
            accessible_name: _('Show Apps'),
        });
        this._dock = dock;
        this._menu = null;
        this._menuManager = new PopupMenu.PopupMenuManager(this);
        this.connect('popup-menu', () => this.popupMenu());
        this.connect('destroy', () => this._menu?.destroy());
        // Whatever the image, the icon is a square of the dock icon size, so
        // the button keeps its size and the dock its alignment. Like the
        // other icons it is rendered for its magnified size.
        this.icon = new IconGrid.BaseIcon(_('Show Apps'), {
            setSizeManually: true,
            showLabel: false,
            createIcon: size => new St.Icon({
                gicon: this._dock.manager.appsButtonGicon,
                fallback_icon_name: APPS_ICON_NAME,
                icon_size: this._dock.iconRenderSize(size),
                width: size,
                height: size,
                style_class: 'show-apps-icon',
                track_hover: true,
            }),
        });
        this.set_child(this.icon);
    }

    popupMenu() {
        if (!this._menu) {
            this._menu = new PopupMenu.PopupMenu(this, 0.5, this._dock.menuSide);
            Main.uiGroup.add_child(this._menu.actor);
            this._menu.actor.hide();
            this._menuManager.addMenu(this._menu);
            this._menu.addAction(_('Dock Settings'), () => openSettingsPage('dock'));
            this._menu.connect('open-state-changed', (_m, open) => {
                this._dock.setMenuOpen(this, open);
                if (open)
                    this.add_style_pseudo_class('active');
                else
                    this.remove_style_pseudo_class('active');
            });
        }
        this._menu.open();
        this._menu.actor.navigate_focus(null, St.DirectionType.TAB_FORWARD, false);
    }

    updateIcon() {
        if (this.icon.icon)
            this.icon.icon.gicon = this._dock.manager.appsButtonGicon;
    }

    // Decided on where the overview is going, not on whether it is still
    // on screen: while it animates out, a click opens the application grid
    // again instead of "closing" an overview that is already closing.
    vfunc_clicked(button) {
        if (button === Clutter.BUTTON_SECONDARY) {
            // The menu only: the applications view stays as it is.
            this._dock.manager.syncShowAppsButtons();
            this.popupMenu();
            return;
        }
        const overview = Main.overview;
        const overviewButton = overview.dash.showAppsButton;
        if (overview.visibleTarget && overviewButton.checked)
            overview.hide();
        else if (overview.visibleTarget)
            overviewButton.checked = true;
        else
            overview.showApps();
        this._dock.manager.syncShowAppsButtons();
    }
});

// Decides whether windows overlap a dock ("intellihide").
class WindowOverlapTracker {
    constructor(callback) {
        this._callback = callback;
        this._windows = new Map();
        this._idleId = 0;
        global.display.connectObject(
            'window-created', (_d, w) => this._track(w),
            'restacked', () => this.queue(),
            this);
        global.workspace_manager.connectObject(
            'active-workspace-changed', () => this.queue(), this);
        for (const actor of global.get_window_actors())
            this._track(actor.meta_window);
    }

    _track(window) {
        if (this._windows.has(window))
            return;
        this._windows.set(window, true);
        window.connectObject(
            'position-changed', () => this.queue(),
            'size-changed', () => this.queue(),
            'notify::minimized', () => this.queue(),
            'workspace-changed', () => this.queue(),
            'unmanaged', () => {
                window.disconnectObject(this);
                this._windows.delete(window);
                this.queue();
            }, this);
        this.queue();
    }

    queue() {
        if (this._idleId)
            return;
        this._idleId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 100, () => {
            this._idleId = 0;
            this._callback();
            return GLib.SOURCE_REMOVE;
        });
    }

    overlaps(rect) {
        const workspace = global.workspace_manager.get_active_workspace();
        for (const window of this._windows.keys()) {
            if (window.minimized || !window.showing_on_its_workspace() ||
                !window.located_on_workspace(workspace) ||
                window.get_window_type() === Meta.WindowType.DESKTOP)
                continue;
            const frame = window.get_frame_rect();
            if (frame.x < rect.x + rect.width && frame.x + frame.width > rect.x &&
                frame.y < rect.y + rect.height && frame.y + frame.height > rect.y)
                return true;
        }
        return false;
    }

    destroy() {
        if (this._idleId)
            GLib.source_remove(this._idleId);
        this._idleId = 0;
        global.display.disconnectObject(this);
        global.workspace_manager.disconnectObject(this);
        for (const window of this._windows.keys())
            window.disconnectObject(this);
        this._windows.clear();
    }
}

class Dock {
    constructor(manager, monitorIndex) {
        this.manager = manager;
        this.monitorIndex = monitorIndex;
        this.position = manager.position;
        this.iconSize = manager.iconSize;
        this._appItems = new Map();
        this._locationItems = new Map();
        this._stackItems = new Map();
        this._menusOpen = new Set();
        this._shown = true;
        this._hoverTimeoutId = 0;
        this._revealTimeoutId = 0;
        this._placeholder = null;
        this._placeholderPos = -1;
        this._hiddenItem = null;
        this._sliding = null;
        this._slideTimeoutId = 0;
        this._scrollOffset = 0;
        this._overflow = 0;
        this._dragScrollId = 0;
        // Files dragged from an application (fileDrop.js).
        this._fileDragOver = false;
        this._fileAtEdge = false;
        this._fileRevealId = 0;
        this._fileRepickId = 0;
        this._dropItem = null;

        const vertical = this.vertical;

        // The holder stays at the screen edge and clips the sliding dock, so
        // a hidden dock never leaks onto a neighbouring monitor.
        // Its style classes tell the desktop icons where the dock is, see
        // extensions/desktop/areas.js.
        this._holder = new St.Widget({
            name: 'deskence-dock-holder',
            style_class: `deskence-dock-holder deskence-dock-edge-${this.position}`,
            clip_to_allocation: true,
            layout_manager: new Clutter.BinLayout(),
        });

        // name "dash" gives the dock the colors of the GNOME Shell theme
        // (light, dark and high contrast); the extra classes only adjust
        // geometry, see stylesheet.css.
        this._dash = new St.Widget({
            name: 'dash',
            style_class: `deskence-dock deskence-dock-${this.position} ` +
                `deskence-dock-${manager.length}`,
            layout_manager: new Clutter.BinLayout(),
            reactive: true,
            track_hover: true,
            x_expand: true,
            y_expand: true,
        });
        this._background = new St.Widget({
            style_class: 'dash-background',
            x_expand: true,
            y_expand: true,
        });
        // Holds the dock background color of the theme, without our
        // overrides, see _updateBackground().
        this._themeProbe = new St.Widget({style_class: 'dash-background', visible: false});
        this._themeProbe.connect('style-changed', () => this.updateBackground());

        // Applications button and the scrollable item list.
        const full = manager.length === 'full';
        this._content = new St.BoxLayout({
            style_class: 'deskence-dock-box',
            x_align: full && !vertical ? Clutter.ActorAlign.FILL : Clutter.ActorAlign.CENTER,
            y_align: full && vertical ? Clutter.ActorAlign.FILL : Clutter.ActorAlign.CENTER,
            x_expand: true,
            y_expand: true,
        });
        setVertical(this._content, vertical);
        this._viewport = new St.Widget({
            layout_manager: new ViewportLayout(this),
            reactive: true,
            x_expand: !vertical,
            y_expand: vertical,
        });
        this._viewport.connect('scroll-event', (_a, event) => this._onScroll(event));
        this._box = new St.BoxLayout({style_class: 'deskence-dock-list'});
        setVertical(this._box, vertical);
        this._box._delegate = this;
        this._dash._delegate = this;
        this._viewport.add_child(this._box);
        this._content.add_child(this._viewport);

        this._dash.add_child(this._themeProbe);
        this._dash.add_child(this._background);
        this._dash.add_child(this._content);
        this._holder.add_child(this._dash);

        this._separatorRunning = this._makeSeparator();
        this._separatorLocations = this._makeSeparator();

        this._showApps = new ShowAppsButton(this);
        this._showAppsItem = new DockItem(this, this._showApps, _('Show Apps'));

        // Revealing strip at the screen edge while the dock is hidden.
        this._trigger = new St.Widget({reactive: true, track_hover: true, visible: false});
        this._trigger.connect('notify::hover', () => this._onTriggerHover());

        this._dash.connect('notify::hover', () => this._syncVisibility());

        const affectsStruts = manager.hideMode === 'never';
        Main.layoutManager.addChrome(this._holder, {affectsStruts, trackFullscreen: true});
        Main.layoutManager.addChrome(this._trigger, {trackFullscreen: true});
        // Keep dialogs, notifications and the screen shield above the dock.
        const uiGroup = Main.layoutManager.uiGroup;
        uiGroup.set_child_below_sibling(this._holder, Main.layoutManager.modalDialogGroup);
        uiGroup.set_child_below_sibling(this._trigger, Main.layoutManager.modalDialogGroup);

        Main.ctrlAltTabManager.addGroup(this._dash, _('Dock'), 'user-bookmarks-symbolic',
            {focusCallback: () => this._focusFirst()});

        this.magnifier = new Magnifier(this);
        this.redisplay();
        this.magnifier.sync();
        this.updateBackground();
        this.setOverviewProgress(manager.overviewValue);
    }

    get vertical() {
        return this.position !== 'bottom';
    }

    // Custom color and transparency of the background only: an inline
    // style on the background actor (no shell-wide CSS), computed from the
    // theme color of the moment so a light/dark switch is followed. The
    // background never changes size, and it takes no clicks.
    //
    // The items have no background of their own (stylesheet.css); what is
    // drawn on the background - symbolic icons, indicators, highlights -
    // uses a light or dark "ink" chosen for the resulting color, see
    // logic.js inkForBackground().
    //
    // In the overview the background takes the look of the top bar, see
    // setOverviewProgress(); the settings are not touched.
    updateBackground() {
        const manager = this.manager;
        let theme = {red: 0, green: 0, blue: 0, alpha: 255};
        if (this._themeProbe.get_stage()) {
            const c = this._themeProbe.get_theme_node().get_background_color();
            theme = {red: c.red, green: c.green, blue: c.blue, alpha: c.alpha};
        }
        const color = manager.backgroundCustomColor ? manager.backgroundColor : null;
        const transparency = manager.backgroundCustomTransparency
            ? manager.backgroundTransparency : null;
        this._desktopCss = backgroundColor(theme, color, transparency);
        this._desktopBackground = effectiveBackground(theme, color, transparency);
        this._applyBackground();
    }

    // value: the overview state, 0 (hidden) .. 1 (window picker) .. 2
    // (application grid). For a dock along the whole edge the background
    // moves towards the window picker from the desktop look to the top
    // bar's look (logic.js panelLook) and keeps it in the grid, so the dock
    // and the bar frame the overview alike - also over a wallpaper or color
    // the grid shows below the bar. A short dock keeps its own look.
    // Only the color of the background layer changes, never its size or
    // the items, and it follows the overview's own transition.
    setOverviewProgress(value) {
        this._overviewProgress = overviewProgress(this.manager.length, value);
        this._applyBackground();
    }

    _applyBackground() {
        if (!this._desktopBackground)
            return;
        const progress = this._overviewProgress ?? 0;
        let background = this._desktopBackground;
        let css = this._desktopCss;
        if (progress > 0) {
            background = mixBackground(background, this.manager.overviewLook(), progress);
            css = cssColor(background);
        }
        const style = css ? `background-color: ${css};` : null;
        if (style !== this._backgroundStyle) {
            this._backgroundStyle = style;
            this._background.set_style(style);
        }

        const ink = inkForBackground(background);
        const classes = {
            'deskence-dock-ink-light': ink === 'light',
            'deskence-dock-ink-dark': ink === 'dark',
            'deskence-dock-see-through': isSeeThrough(background),
        };
        for (const [name, wanted] of Object.entries(classes)) {
            if (wanted)
                this._dash.add_style_class_name(name);
            else
                this._dash.remove_style_class_name(name);
        }
    }

    // --- Scrolling ------------------------------------------------------

    get overflowing() {
        return this._overflow > 0;
    }

    allocateViewport(box) {
        const vertical = this.vertical;
        const [viewWidth, viewHeight] = box.get_size();
        const viewLength = vertical ? viewHeight : viewWidth;
        const [, natWidth] = this._box.get_preferred_width(vertical ? -1 : viewHeight);
        const [, natHeight] = this._box.get_preferred_height(vertical ? viewWidth : natWidth);
        const listLength = vertical ? natHeight : natWidth;

        const layout = viewportLayout(viewLength, listLength, this._scrollOffset);
        this._overflow = layout.overflow;
        // Kept while the list fits (it may only be for one layout pass, as
        // during a rebuild); applied again, clamped, when it overflows.
        if (layout.overflow > 0)
            this._scrollOffset = layout.offset;

        const childBox = new Clutter.ActorBox();
        if (vertical)
            childBox.set_size(viewWidth, listLength);
        else
            childBox.set_size(listLength, viewHeight);
        this._box.allocate(childBox);
        this._applyScroll(viewLength);
    }

    _viewLength() {
        return this.vertical ? this._viewport.height : this._viewport.width;
    }

    // Moves the list and dims the items at an edge beyond which more
    // follow. The list is clipped along the dock (not across it, so
    // magnified icons keep their size) whenever it could reach the
    // applications button or past the dock.
    _applyScroll(viewLength = this._viewLength()) {
        const vertical = this.vertical;
        const offset = this._overflow > 0 ? this._scrollOffset : 0;
        if (vertical) {
            this._box.translation_x = 0;
            this._box.translation_y = -offset;
        } else {
            this._box.translation_x = -offset;
            this._box.translation_y = 0;
        }
        const clip = this._overflow > 0 || this.manager.length === 'full';
        if (clip) {
            const across = 4096;
            if (vertical)
                this._viewport.set_clip(-across, 0, 2 * across, viewLength);
            else
                this._viewport.set_clip(0, -across, viewLength, 2 * across);
        } else {
            this._viewport.remove_clip();
        }

        const fade = Math.max(1, this.itemExtent() * 0.75);
        const start = -offset;
        for (const child of this._box.get_children()) {
            let opacity = 255;
            if (this._overflow > 0) {
                const box = child.get_allocation_box();
                const center = start + (vertical ? (box.y1 + box.y2) : (box.x1 + box.x2)) / 2;
                let factor = 1;
                if (offset > 0)
                    factor = Math.min(factor, center / fade);
                if (offset < this._overflow)
                    factor = Math.min(factor, (viewLength - center) / fade);
                opacity = Math.round(255 * Math.min(1, Math.max(0.25, factor)));
            }
            if (child.opacity !== opacity && child !== this._hiddenItem)
                child.opacity = opacity;
        }
    }

    // The visible part of a list clipped along the dock, in list
    // coordinates, or null when it is not clipped.
    visibleSpan() {
        if (this._overflow <= 0 && this.manager.length !== 'full')
            return null;
        const offset = this._overflow > 0 ? this._scrollOffset : 0;
        return [offset, offset + this._viewLength()];
    }

    scrollBy(delta) {
        if (this._overflow <= 0 || delta === 0)
            return;
        const offset = Math.min(Math.max(this._scrollOffset + delta, 0), this._overflow);
        if (offset === this._scrollOffset)
            return;
        this._scrollOffset = offset;
        this._applyScroll();
        this.magnifier.relax();
        // The icons moved away from the previews.
        this.manager.previews.close();
    }

    // Scrolls so an item of the list is entirely visible (keyboard focus).
    ensureVisible(item) {
        if (item.get_parent() !== this._box || this._overflow <= 0)
            return;
        const box = item.get_allocation_box();
        const [a, b] = this.vertical ? [box.y1, box.y2] : [box.x1, box.x2];
        this.scrollBy(scrollToReveal(a, b, this._scrollOffset, this._viewLength()) -
            this._scrollOffset);
    }

    _onScroll(event) {
        if (this._menusOpen.size > 0 || this._overflow <= 0)
            return Clutter.EVENT_PROPAGATE;
        // A wheel click also arrives as an emulated smooth event.
        if (event.get_flags() & Clutter.EventFlags.POINTER_EMULATED)
            return Clutter.EVENT_STOP;
        let delta = 0;
        switch (event.get_scroll_direction()) {
        case Clutter.ScrollDirection.UP:
        case Clutter.ScrollDirection.LEFT:
            delta = -SCROLL_STEP;
            break;
        case Clutter.ScrollDirection.DOWN:
        case Clutter.ScrollDirection.RIGHT:
            delta = SCROLL_STEP;
            break;
        case Clutter.ScrollDirection.SMOOTH: {
            // Touchpads; in a horizontal dock vertical scrolling moves the
            // list too. Wheels also send discrete events, handled above.
            if (event.get_scroll_source() === Clutter.ScrollSource.WHEEL)
                return Clutter.EVENT_STOP;
            const [dx, dy] = event.get_scroll_delta();
            delta = (Math.abs(dx) > Math.abs(dy) ? dx : dy) * SCROLL_STEP;
            break;
        }
        }
        this.scrollBy(delta);
        return Clutter.EVENT_STOP;
    }

    // While dragging over an end of a scrolled list, keep scrolling.
    _updateDragScroll() {
        const [px, py] = global.get_pointer();
        const [ok, x, y] = this._viewport.transform_stage_point(px, py);
        const length = this._viewLength();
        const pos = this.vertical ? y : x;
        const zone = this.itemExtent() / 2;
        let direction = 0;
        if (ok && this._overflow > 0 && pos >= -zone && pos <= length + zone) {
            if (pos < zone && this._scrollOffset > 0)
                direction = -1;
            else if (pos > length - zone && this._scrollOffset < this._overflow)
                direction = 1;
        }
        if (direction === 0) {
            this._stopDragScroll();
            return;
        }
        this._dragScrollDirection = direction;
        this._dragScrollId ||= GLib.timeout_add(GLib.PRIORITY_DEFAULT, DRAG_SCROLL_INTERVAL, () => {
            if (!this._placeholder && !this._fileDragOver) {
                this._dragScrollId = 0;
                return GLib.SOURCE_REMOVE;
            }
            this.scrollBy(this._dragScrollDirection * DRAG_SCROLL_STEP);
            if (this._placeholder)
                this._updateDropPosition();
            else
                this.manager.fileDrop.repick();
            this._updateDragScroll();
            return this._dragScrollId ? GLib.SOURCE_CONTINUE : GLib.SOURCE_REMOVE;
        });
    }

    _stopDragScroll() {
        if (this._dragScrollId)
            GLib.source_remove(this._dragScrollId);
        this._dragScrollId = 0;
    }

    // --- For the magnifier ---------------------------------------------

    get dash() {
        return this._dash;
    }

    get box() {
        return this._box;
    }

    get background() {
        return this._background;
    }

    get shown() {
        return this._shown;
    }

    // The button of a dock item, or null for separators and placeholders.
    itemButton(actor) {
        return actor instanceof DockItem ? actor.child : null;
    }

    // Whether the applications button magnifies on its own instead of
    // together with the list: when the list does not end right next to it
    // (whole-edge dock) or scrolls under a fixed button.
    get _appsButtonSeparate() {
        return this.manager.length === 'full' || this._overflow > 0;
    }

    // What the magnifier moves, as zones that grow independently (see
    // magnifier.js). Each zone has targets ({actor, button, span}),
    // locate(x, y) giving a stage point along the dock in the coordinates
    // of the spans, and contains(x, y) telling whether the zone is under it.
    //  - "list": the list items and, in a short dock without scrolling,
    //    the applications button right next to them (otherwise icons would
    //    slide under it). Spans in list coordinates.
    //  - "apps": the applications button on its own, growing from its
    //    outer end, at most up to the first icon of the list
    //    (_appsButtonMaxScale()). No room is kept free for it.
    magnifyZones() {
        const vertical = this.vertical;
        const span = b => vertical ? [b.y1, b.y2] : [b.x1, b.x2];
        const along = (actor, x, y) => {
            const [ok, ax, ay] = actor.transform_stage_point(x, y);
            return ok ? (vertical ? ay : ax) : null;
        };
        const targets = this._box.get_children().filter(c => c.visible).map(child => ({
            actor: this.itemButton(child) ?? child,
            button: this.itemButton(child),
            span: span(child.get_allocation_box()),
        }));
        const apps = this._showAppsItem;
        const hasApps = apps.get_parent() === this._content;
        const separate = hasApps && this._appsButtonSeparate;
        const atStart = this.manager.appsButtonPosition === 'start';

        if (hasApps && !separate) {
            // Content coordinates to list coordinates.
            const offset = span(this._viewport.get_allocation_box())[0] +
                span(this._box.get_allocation_box())[0];
            const [a, b] = span(apps.get_allocation_box());
            const target = {actor: apps.child, button: apps.child, span: [a - offset, b - offset]};
            if (atStart)
                targets.unshift(target);
            else
                targets.push(target);
        }

        // Pointer positions in content coordinates on either side of the
        // border between the list and a separate button.
        let inApps = () => false;
        if (separate) {
            const [va, vb] = span(this._viewport.get_allocation_box());
            const [aa, ab] = span(apps.get_allocation_box());
            const boundary = atStart ? (ab + va) / 2 : (vb + aa) / 2;
            inApps = (x, y) => {
                const pos = along(this._content, x, y);
                return pos !== null && (atStart ? pos < boundary : pos >= boundary);
            };
        }

        // A whole-edge dock whose list fits: magnified icons may use the
        // spare room after the list and no more (magnification grows the
        // list by up to strength - 1 times the magnifier's radius), so
        // none is cut by the end of the view.
        let room;
        if (this.manager.length === 'full' && this._overflow <= 0) {
            const [la, lb] = span(this._box.get_allocation_box());
            room = this._viewLength() - (lb - la);
        }

        const zones = [{
            name: 'list',
            targets,
            room,
            keepInView: true,
            stretchBackground: this.manager.length !== 'full' && this._overflow <= 0,
            locate: (x, y) => along(this._box, x, y),
            contains: (x, y) => !inApps(x, y),
        }];
        if (separate) {
            const outer = atStart ? 0 : 1;
            zones.push({
                name: 'apps',
                targets: [{actor: apps.child, button: apps.child, span: span(apps.get_allocation_box())}],
                keepInView: false,
                stretchBackground: false,
                scaleOnly: true,
                maxScale: this._appsButtonMaxScale(atStart),
                pivot: {
                    bottom: [outer, 1],
                    left: [0, outer],
                    right: [1, outer],
                }[this.position],
                locate: (x, y) => along(this._content, x, y),
                contains: inApps,
            });
        }
        return zones;
    }

    // The largest scale of a separately magnified applications button: up
    // to the first icon of the list, which stays where it is. Both have
    // their icon centered in their item; a little clearance is kept.
    _appsButtonMaxScale(atStart) {
        const vertical = this.vertical;
        const span = b => vertical ? [b.y1, b.y2] : [b.x1, b.x2];
        const apps = this._showAppsItem;
        const [ia, ib] = span(apps.get_allocation_box());
        const [ba, bb] = span(apps.child.get_allocation_box());
        const [va, vb] = span(this._viewport.get_allocation_box());
        const icon = this.iconSize;
        const item = this.itemExtent();
        const clearance = 4;
        // Distances from the button's outer end, in content coordinates.
        const outer = atStart ? ia + ba : ia + bb;
        const buttonLength = bb - ba;
        const iconEnd = (buttonLength + icon) / 2;
        const listIcon = (item - icon) / 2;
        const room = atStart
            ? va + listIcon - outer - clearance
            : outer - (vb - listIcon) - clearance;
        return appsButtonMaxScale(room, iconEnd, this.manager.magnifyStrength);
    }

    // Logical size icons of the given size are rendered at.
    iconRenderSize(size) {
        return iconRenderSize(size, this.magnifier?.maxScale ?? 1);
    }

    // Magnification turned on or off, or its strength changed: render the
    // icons again for the new largest size. Done once per change.
    updateIconRendering() {
        for (const item of this._allItems())
            item.child.updateIconRendering();
        this._showApps.icon.update();
    }

    // Length of one item along the dock.
    itemExtent() {
        const item = this._iconChildren()[0];
        if (!item)
            return this.iconSize;
        return this.position === 'bottom' ? item.width : item.height;
    }

    // The holder clips the dock so a hidden dock never shows on a
    // neighbouring monitor. Magnified icons may reach beyond the dock
    // (inwards and past its ends), so the clip is widened there - never
    // past the screen edge or the monitor. The holder's own size, which
    // decides the space reserved for windows, does not change.
    updateClip() {
        const [across, along] = this.magnifier?.overflow() ?? [0, 0];
        const monitor = this.monitor;
        if (!monitor || !this._rect || (across === 0 && along === 0)) {
            this._holder.remove_clip();
            this._holder.clip_to_allocation = true;
            return;
        }
        const {x, y, width, height} = this._rect;
        let left = 0, top = 0, right = width, bottom = height;
        if (this.position === 'bottom') {
            top = -across;
            left = Math.max(-along, monitor.x - x);
            right = Math.min(width + along, monitor.x + monitor.width - x);
        } else {
            if (this.position === 'left')
                right = width + across;
            else
                left = -across;
            top = Math.max(-along, monitor.y - y);
            bottom = Math.min(height + along, monitor.y + monitor.height - y);
        }
        this._holder.clip_to_allocation = false;
        this._holder.set_clip(left, top, right - left, bottom - top);
    }

    get monitor() {
        return Main.layoutManager.monitors[this.monitorIndex];
    }

    get menuSide() {
        return {left: St.Side.LEFT, right: St.Side.RIGHT}[this.position] ?? St.Side.BOTTOM;
    }

    _allItems() {
        return [...this._appItems.values(), ...this._stackItems.values(),
            ...this._locationItems.values()];
    }

    _makeSeparator() {
        const vertical = this.position !== 'bottom';
        return new St.Widget({
            style_class: vertical
                ? 'dash-separator deskence-dock-separator-vertical'
                : 'dash-separator',
            y_align: Clutter.ActorAlign.CENTER,
            x_align: Clutter.ActorAlign.CENTER,
        });
    }

    _focusFirst() {
        this.reveal();
        this._content.navigate_focus(null, St.DirectionType.TAB_FORWARD, false);
    }

    // Rebuilds the item list, reusing existing icons.
    redisplay() {
        const apps = this.manager.dockApps();
        const favorites = apps.filter(a => a.pinned);
        const running = apps.filter(a => !a.pinned);
        const locations = this.manager.locations.getItems();
        const stacks = this.manager.stacks.getItems();

        const wantedApps = new Set(apps.map(a => a.app.get_id()));
        for (const [id, item] of this._appItems) {
            if (!wantedApps.has(id)) {
                item.destroy();
                this._appItems.delete(id);
            }
        }
        const wantedStacks = new Set(stacks.map(l => l.id));
        for (const [id, item] of this._stackItems) {
            if (!wantedStacks.has(id)) {
                item.destroy();
                this._stackItems.delete(id);
            }
        }
        const wantedLocations = new Set(locations.map(l => l.id));
        for (const [id, item] of this._locationItems) {
            if (!wantedLocations.has(id)) {
                item.destroy();
                this._locationItems.delete(id);
            }
        }

        const order = [];
        const appItem = ({app}) => {
            let item = this._appItems.get(app.get_id());
            if (!item) {
                const icon = new DockAppIcon(app, this);
                const previews = this.manager.previews;
                icon.connectObject(
                    'menu-state-changed', (_i, open) => this.setMenuOpen(icon, open),
                    'notify::hover', () => previews.iconHoverChanged(icon, this),
                    'key-press-event', (_i, event) => this._onIconKeyPress(icon, event),
                    // A click keeps its usual meaning; the previews go away.
                    'button-press-event', () => {
                        previews.close();
                        return Clutter.EVENT_PROPAGATE;
                    },
                    this);
                item = new DockItem(this, icon, app.get_name());
                this._appItems.set(app.get_id(), item);
            }
            item.child.sync();
            return item;
        };
        favorites.forEach(a => order.push(appItem(a)));
        if (favorites.length && running.length)
            order.push(this._separatorRunning);
        running.forEach(a => order.push(appItem(a)));
        // Folders, then drives and the trash, after one separator; folders
        // are told apart from applications by their place, their folder
        // icons and the arrow under them.
        if (order.length && (locations.length || stacks.length))
            order.push(this._separatorLocations);
        for (const stack of stacks) {
            let item = this._stackItems.get(stack.id);
            if (!item) {
                item = new DockItem(this, new StackIcon(stack, this), stack.name);
                this._stackItems.set(stack.id, item);
            } else {
                item.child.update(stack);
                item.setLabelText(stack.name);
            }
            order.push(item);
        }
        for (const location of locations) {
            let item = this._locationItems.get(location.id);
            if (!item) {
                item = new DockItem(this, new LocationIcon(location, this), location.name);
                this._locationItems.set(location.id, item);
            } else {
                item.child.update(location);
                item.setLabelText(location.name);
            }
            order.push(item);
        }
        // The applications button is outside the scrollable list. "start" is
        // left in a horizontal dock and top in a vertical one; the list keeps
        // its order either way.
        if (this.manager.showAppsButton) {
            if (this._showAppsItem.get_parent() !== this._content)
                this._content.add_child(this._showAppsItem);
            if (this.manager.appsButtonPosition === 'start')
                this._content.set_child_below_sibling(this._showAppsItem, this._viewport);
            else
                this._content.set_child_above_sibling(this._showAppsItem, this._viewport);
        } else if (this._showAppsItem.get_parent()) {
            this._content.remove_child(this._showAppsItem);
        }

        // Remove what is no longer wanted (separators), then put everything
        // in order.
        for (const child of this._box.get_children()) {
            if (!order.includes(child) && child !== this._placeholder)
                this._box.remove_child(child);
        }
        order.forEach((actor, index) => {
            if (actor.get_parent() !== this._box)
                this._box.insert_child_at_index(actor, index);
            else
                this._box.set_child_at_index(actor, index);
        });
        // A rebuild during a drag keeps the drop position.
        if (this._placeholder)
            this._placePlaceholder();

        this._updateIconSize([...order, this._showAppsItem]);
        this.syncShowApps();
        this._updatePosition();
        this._syncVisibility();
    }

    updateAppsButtonIcon() {
        this._showApps.updateIcon();
    }

    // The arrow key pointing away from the dock opens the window previews
    // of a focused application icon.
    _onIconKeyPress(icon, event) {
        const inwards = {
            bottom: Clutter.KEY_Up,
            left: Clutter.KEY_Right,
            right: Clutter.KEY_Left,
        }[this.position];
        if (event.get_key_symbol() !== inwards || !this.manager.previews.available(icon))
            return Clutter.EVENT_PROPAGATE;
        this.manager.previews.open(icon, this, true);
        return Clutter.EVENT_STOP;
    }

    _iconChildren() {
        return this._box.get_children().filter(c => c instanceof DockItem);
    }

    // The size the user chose; what does not fit scrolls.
    _updateIconSize(order) {
        const size = this.manager.iconSize;
        this.iconSize = size;
        const vertical = this.position !== 'bottom';
        for (const item of order) {
            if (item instanceof DockItem)
                item.child.icon.setIconSize(size);
            else if (vertical)
                item.width = size;
            else
                item.height = size;
        }
    }

    _topOffset() {
        if (this.monitorIndex !== Main.layoutManager.primaryIndex)
            return 0;
        const panelBox = Main.layoutManager.panelBox;
        return panelBox.visible ? panelBox.height : 0;
    }

    _updatePosition() {
        const monitor = this.monitor;
        if (!monitor)
            return;
        const top = this._topOffset();
        const full = this.manager.length === 'full';
        const [, natWidth] = this._dash.get_preferred_width(-1);
        const [, natHeight] = this._dash.get_preferred_height(natWidth);
        let x, y, width, height;
        switch (this.position) {
        case 'left':
        case 'right': {
            const available = monitor.height - top;
            width = natWidth;
            height = full ? available : Math.min(natHeight, available);
            x = this.position === 'left' ? monitor.x : monitor.x + monitor.width - width;
            y = monitor.y + top + Math.floor((available - height) / 2);
            break;
        }
        default:
            height = natHeight;
            width = full ? monitor.width : Math.min(natWidth, monitor.width);
            x = monitor.x + Math.floor((monitor.width - width) / 2);
            y = monitor.y + monitor.height - height;
        }
        this._holder.set_position(x, y);
        this._holder.set_size(width, height);
        this._rect = {x, y, width, height};
        // Keep the scroll position valid for the new length.
        this._viewport.queue_relayout();

        // One logical pixel strip along the dock's edge.
        const strip = 1;
        if (this.position === 'bottom')
            this._trigger.set({x, y: y + height - strip, width, height: strip});
        else if (this.position === 'left')
            this._trigger.set({x, y, width: strip, height});
        else
            this._trigger.set({x: x + width - strip, y, width: strip, height});

        this.updateClip();
        this.manager.updateOverviewSpace();
    }

    get rect() {
        return this._rect;
    }

    get extent() {
        if (!this._rect)
            return 0;
        return this.position === 'bottom' ? this._rect.height : this._rect.width;
    }

    syncShowApps() {
        const checked = Main.overview.visibleTarget && Main.overview.dash.showAppsButton.checked;
        this._showApps.checked = checked;
    }

    syncIcons() {
        for (const item of this._appItems.values())
            item.child.sync();
    }

    // What an application reports changed (appId), or the settings (none).
    updateLauncher(appId = null) {
        for (const [id, item] of this._appItems) {
            if (appId === null || id === appId)
                item.child.updateLauncher();
        }
    }

    setMenuOpen(actor, open) {
        if (open) {
            this._menusOpen.add(actor);
            this.manager.previews.close();
        } else {
            this._menusOpen.delete(actor);
        }
        for (const item of this._allItems())
            item.hideLabel();
        this.magnifier.setFrozen(this._menusOpen.size > 0);
        this._syncVisibility();
    }

    // --- Hiding ---------------------------------------------------------

    _keepShown() {
        return Main.overview.visibleTarget ||
            this._menusOpen.size > 0 ||
            this.manager.previews.isOpenFor(this) ||
            this.manager.dragInProgress ||
            this._fileDragOver ||
            this._dash.hover ||
            global.stage.key_focus && this._dash.contains(global.stage.key_focus);
    }

    syncVisibility() {
        this._syncVisibility();
    }

    _syncVisibility() {
        const mode = this.manager.hideMode;
        if (mode === 'never' || this._keepShown()) {
            this._clearHoverTimeout();
            this.reveal();
            return;
        }
        if (mode === 'intellihide' && this._rect &&
            !this.manager.overlapTracker.overlaps(this._rect)) {
            this._clearHoverTimeout();
            this.reveal();
            return;
        }
        // Hide after a short delay so moving across the dock is forgiving.
        if (this._shown && !this._hoverTimeoutId) {
            this._hoverTimeoutId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, AUTOHIDE_DELAY, () => {
                this._hoverTimeoutId = 0;
                if (!this._keepShown() && this.manager.hideMode !== 'never')
                    this._conceal();
                return GLib.SOURCE_REMOVE;
            });
        }
    }

    _clearHoverTimeout() {
        if (this._hoverTimeoutId) {
            GLib.source_remove(this._hoverTimeoutId);
            this._hoverTimeoutId = 0;
        }
    }

    _onTriggerHover() {
        if (this._revealTimeoutId) {
            GLib.source_remove(this._revealTimeoutId);
            this._revealTimeoutId = 0;
        }
        if (!this._trigger.hover)
            return;
        this._revealTimeoutId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, REVEAL_DELAY, () => {
            this._revealTimeoutId = 0;
            if (this._trigger.hover) {
                this.reveal();
                // The pointer is at the edge, not over the dock yet: give it
                // time to move onto the dock before hiding again.
                this._syncVisibility();
            }
            return GLib.SOURCE_REMOVE;
        });
    }

    _hiddenTranslation() {
        const extent = this.extent;
        return {
            bottom: [0, extent],
            left: [-extent, 0],
            right: [extent, 0],
        }[this.position];
    }

    reveal() {
        this._trigger.hide();
        if (this._shown)
            return;
        this._shown = true;
        this._holder.show();
        this._dash.ease({
            translation_x: 0,
            translation_y: 0,
            duration: ANIMATION_TIME,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
    }

    _conceal() {
        if (!this._shown)
            return;
        this._shown = false;
        this.magnifier.reset();
        const [tx, ty] = this._hiddenTranslation();
        this._dash.ease({
            translation_x: tx,
            translation_y: ty,
            duration: ANIMATION_TIME,
            mode: Clutter.AnimationMode.EASE_IN_QUAD,
            onComplete: () => {
                if (!this._shown) {
                    this._holder.hide();
                    this._trigger.show();
                }
            },
        });
    }

    onOverlapChanged() {
        if (this.manager.hideMode === 'intellihide')
            this._syncVisibility();
    }

    onOverviewChanged() {
        this.syncShowApps();
        this._syncVisibility();
    }

    // --- Drag and drop (pinning and reordering) -------------------------
    //
    // While a pinned application is dragged over the dock, its own item is
    // hidden and a placeholder shows where it will land, so the dock already
    // looks like the result. Dropping writes the new favorites order at once
    // (GNOME's AppFavorites updates synchronously) and rebuilds the dock in
    // the same step: nothing goes back to the old place first, and no later
    // rebuild from the settings change can bring back a stale order, since
    // it reads the same favorites. Items slide to their new places while a
    // drag is active and right after the drop. Running applications that
    // are not pinned only become pinned when dropped among the pinned ones;
    // dragging never unpins.

    _pinnedItems(exceptId) {
        const favorites = AppFavorites.getAppFavorites().getFavorites();
        return favorites
            .filter(app => app.get_id() !== exceptId)
            .map(app => this._appItems.get(app.get_id()))
            .filter(item => item?.get_parent() === this._box);
    }

    // Position among the pinned applications (without the dragged one)
    // under a point in list coordinates (scrolling included).
    _dropIndex(items, x, y) {
        const vertical = this.vertical;
        const centers = items.map(item => {
            const box = item.get_allocation_box();
            return vertical ? (box.y1 + box.y2) / 2 : (box.x1 + box.x2) / 2;
        });
        return insertionIndex(centers, vertical ? y : x);
    }

    // List index for a position among the pinned items.
    _boxIndex(items, pos) {
        if (pos < items.length)
            return this._box.get_children().indexOf(items[pos]);
        if (items.length)
            return this._box.get_children().indexOf(items.at(-1)) + 1;
        return 0;
    }

    _setSliding(sliding) {
        if (this._slideTimeoutId) {
            GLib.source_remove(this._slideTimeoutId);
            this._slideTimeoutId = 0;
        }
        this._box.get_children().forEach(child => {
            const eased = this._sliding?.has(child);
            if (sliding && !eased) {
                child.save_easing_state();
                child.set_easing_duration(ANIMATION_TIME);
                child.set_easing_mode(Clutter.AnimationMode.EASE_OUT_QUAD);
            } else if (!sliding && eased) {
                child.restore_easing_state();
            }
        });
        this._sliding = sliding ? new Set(this._box.get_children()) : null;
    }

    _placePlaceholder() {
        if (this._placeholder.get_parent() === this._box)
            this._box.remove_child(this._placeholder);
        const items = this._pinnedItems(this._hiddenItem?.child.app.get_id());
        this._box.insert_child_at_index(this._placeholder,
            this._boxIndex(items, Math.min(this._placeholderPos, items.length)));
    }

    handleDragOver(source, actor, x, y) {
        const app = source?.app;
        if (!app || app.is_window_backed() || !global.settings.is_writable('favorite-apps'))
            return DND.DragMotionResult.NO_DROP;

        const id = app.get_id();
        const isFavorite = AppFavorites.getAppFavorites().isFavorite(id);
        const sourceItem = isFavorite ? this._appItems.get(id) : null;
        this._setSliding(true);
        if (sourceItem && this._hiddenItem !== sourceItem) {
            this._hiddenItem?.show();
            this._hiddenItem = sourceItem;
            sourceItem.hide();
        }

        this._dragId = id;
        this._updateDropPosition();
        this._updateDragScroll();
        return isFavorite ? DND.DragMotionResult.MOVE_DROP : DND.DragMotionResult.COPY_DROP;
    }

    // The pointer is in stage coordinates; transforming it into the list
    // includes the list's scroll translation.
    _updateDropPosition() {
        const items = this._pinnedItems(this._dragId);
        const [px, py] = global.get_pointer();
        const [ok, bx, by] = this._box.transform_stage_point(px, py);
        const pos = ok ? this._dropIndex(items, bx, by) : items.length;
        if (pos === this._placeholderPos && this._placeholder)
            return;
        this._placeholderPos = pos;
        if (!this._placeholder) {
            this._placeholder = new St.Widget({
                style_class: 'dash-item-container deskence-dock-placeholder',
                width: this.itemExtent(),
                height: this.itemExtent(),
            });
        }
        this._placePlaceholder();
    }

    acceptDrop(source) {
        const app = source?.app;
        const pos = this._placeholderPos;
        if (!app || app.is_window_backed() || pos < 0 ||
            !global.settings.is_writable('favorite-apps')) {
            this.clearPlaceholder();
            return false;
        }

        const id = app.get_id();
        const favorites = AppFavorites.getAppFavorites();
        if (favorites.isFavorite(id))
            favorites.moveFavoriteToPos(id, pos);
        else
            favorites.addFavoriteAtPos(id, pos);

        // The item takes the placeholder's place in the same frame, then
        // the rebuild confirms the order the favorites now have.
        if (this._hiddenItem && this._placeholder?.get_parent() === this._box)
            this._box.set_child_at_index(this._hiddenItem, this._box.get_children().indexOf(this._placeholder));
        this.clearPlaceholder();
        // The scroll position is kept, so the item stays where it was
        // dropped, in view.
        this.manager.redisplayNow();
        return true;
    }

    clearPlaceholder() {
        this._stopDragScroll();
        this._placeholder?.destroy();
        this._placeholder = null;
        this._placeholderPos = -1;
        this._hiddenItem?.show();
        this._hiddenItem = null;
        if (this._sliding) {
            // Let the items slide into place, then stop easing layout.
            this._slideTimeoutId ||= GLib.timeout_add(GLib.PRIORITY_DEFAULT, ANIMATION_TIME * 2, () => {
                this._slideTimeoutId = 0;
                this._setSliding(false);
                return GLib.SOURCE_REMOVE;
            });
        }
    }

    onDragMotion(dragEvent) {
        if (!this._placeholder)
            return;
        if (!this._dash.contains(dragEvent.targetActor))
            this.clearPlaceholder();
    }

    hideLabels() {
        for (const item of this._allItems())
            item.hideLabel();
    }

    // --- Files dragged from applications (fileDrop.js) -------------------
    //
    // These drags belong to a Wayland client: the dock's actors get no
    // pointer events while they last, so hover, revealing and scrolling
    // follow the positions the drag reports.

    // The item under a dragged file that could take it, an application or
    // a folder, or null.
    fileDropTarget(actor) {
        if (!actor || !this._dash.contains(actor))
            return null;
        for (const item of this._appItems.values()) {
            if (item.contains(actor)) {
                return {
                    kind: 'app', key: `app:${this.monitorIndex}:${item.child.app.get_id()}`,
                    dock: this, item, icon: item.child,
                };
            }
        }
        for (const item of this._stackItems.values()) {
            if (item.contains(actor)) {
                const stack = item.child.item;
                return {
                    kind: 'stack', key: `stack:${this.monitorIndex}:${stack.id}`,
                    dock: this, item, icon: item.child, file: stack.file, name: stack.name,
                };
            }
        }
        return null;
    }

    // Marks item as the target of a file drag: highlighted like a hovered
    // item when it takes the files, dimmed when it does not, with text
    // telling what a drop does. null clears the mark.
    setFileDropFeedback(item, accepted = true, text = null) {
        const old = this._dropItem;
        if (old && old !== item && old.get_stage()) {
            old.child.remove_style_class_name('deskence-drop-target');
            old.child.opacity = 255;
            old.setDropText(null);
        }
        this._dropItem = item;
        if (!item)
            return;
        if (accepted)
            item.child.add_style_class_name('deskence-drop-target');
        else
            item.child.remove_style_class_name('deskence-drop-target');
        item.child.opacity = accepted ? 255 : REFUSED_OPACITY;
        item.setDropText(text);
    }

    // A file drag at stage point x, y over actor: the dock comes out when
    // the pointer rests at its screen edge and stays while it is over it;
    // a scrolled list scrolls at its ends.
    fileDragAt(x, y, actor) {
        const over = actor !== null && this._dash.contains(actor);
        if (over !== this._fileDragOver) {
            this._fileDragOver = over;
            this._syncVisibility();
        }
        if (over)
            this._updateDragScroll();
        else if (!this._placeholder)
            this._stopDragScroll();

        this._fileAtEdge = actor !== null && actor === this._trigger;
        if (!this._fileAtEdge) {
            if (this._fileRevealId)
                GLib.source_remove(this._fileRevealId);
            this._fileRevealId = 0;
            return;
        }
        this._fileRevealId ||= GLib.timeout_add(GLib.PRIORITY_DEFAULT, REVEAL_DELAY, () => {
            this._fileRevealId = 0;
            if (!this._fileAtEdge)
                return GLib.SOURCE_REMOVE;
            // The dock comes out under the resting pointer; the drag reports
            // no position until it moves, so the target is found again once
            // the dock is in place.
            this._fileDragOver = true;
            this.reveal();
            this._syncVisibility();
            if (this._fileRepickId)
                GLib.source_remove(this._fileRepickId);
            this._fileRepickId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, ANIMATION_TIME, () => {
                this._fileRepickId = 0;
                this.manager.fileDrop.repick();
                return GLib.SOURCE_REMOVE;
            });
            return GLib.SOURCE_REMOVE;
        });
    }

    _clearFileTimeouts() {
        for (const name of ['_fileRevealId', '_fileRepickId']) {
            if (this[name])
                GLib.source_remove(this[name]);
            this[name] = 0;
        }
    }

    endFileDrag() {
        this._fileDragOver = false;
        this._fileAtEdge = false;
        this._clearFileTimeouts();
        if (!this._placeholder)
            this._stopDragScroll();
        this.setFileDropFeedback(null);
        this._syncVisibility();
    }

    destroy() {
        this.manager.previews.closeFor(this);
        this.manager.stackPanel.closeFor(this);
        this._clearHoverTimeout();
        this._stopDragScroll();
        if (this._slideTimeoutId)
            GLib.source_remove(this._slideTimeoutId);
        this._slideTimeoutId = 0;
        if (this._revealTimeoutId)
            GLib.source_remove(this._revealTimeoutId);
        this._revealTimeoutId = 0;
        this._clearFileTimeouts();
        Main.ctrlAltTabManager.removeGroup(this._dash);
        this.magnifier.destroy();
        this._holder.destroy();
        this._trigger.destroy();
        this._appItems.clear();
        this._locationItems.clear();
        this._stackItems.clear();
    }
}

export class DockManager {
    constructor(settings) {
        this._settings = settings;
        this._docks = [];
        this._redisplayId = 0;
        this.dragInProgress = false;
        this.fileDragInProgress = false;
        this._runningOrder = [];
        this._iconCancellable = null;
        this._readSettings();
        this.appsButtonGicon = new Gio.ThemedIcon({name: APPS_ICON_NAME});
        this._updateAppsButtonIcon();
        this.previews = new WindowPreviews(this);

        this.locations = new LocationsModel(settings);
        this.locations.connectObject('changed', () => this._queueRedisplay(), this);
        this.stacks = new StacksModel(settings);
        this.stacks.connectObject('changed', () => this._queueRedisplay(), this);
        this.stackPanel = new StackPanel(this);
        // Counters and progress reported by applications.
        this.launcher = new LauncherEntries();
        this.launcher.connectObject('changed', (_l, appId) =>
            this._docks.forEach(d => d.updateLauncher(appId)), this);
        this.launcher.setListening(this.showAppCounts || this.showAppProgress);
        this.overlapTracker = new WindowOverlapTracker(
            () => this._docks.forEach(d => d.onOverlapChanged()));

        this._settings.connectObject('changed', (_s, key) => this._onSettingChanged(key), this);
        Main.layoutManager.connectObject('monitors-changed', () => this._rebuild(), this);
        AppFavorites.getAppFavorites().connectObject('changed', () => this._queueRedisplay(), this);
        this._appSystem = Shell.AppSystem.get_default();
        this._appSystem.connectObject(
            'app-state-changed', () => this._queueRedisplay(),
            'installed-changed', () => this._queueRedisplay(),
            this);
        Shell.WindowTracker.get_default().connectObject('notify::focus-app',
            () => this._docks.forEach(d => d.syncIcons()), this);
        global.workspace_manager.connectObject(
            'active-workspace-changed', () => this._queueRedisplay(),
            'workspace-added', () => this._trackWorkspaces(),
            'workspace-removed', () => this._trackWorkspaces(),
            this);
        this._trackWorkspaces();

        Main.overview.connectObject(
            'showing', () => this._onOverviewChanged(),
            'shown', () => this._onOverviewChanged(),
            'hiding', () => this._onOverviewChanged(),
            'hidden', () => this._onOverviewChanged(),
            'item-drag-begin', () => this._onDragBegin(),
            'item-drag-end', () => this._onDragEnd(),
            'item-drag-cancelled', () => this._onDragEnd(),
            this);
        Main.overview.dash.showAppsButton.connectObject('notify::checked',
            () => this.syncShowAppsButtons(), this);
        Main.layoutManager.panelBox.connectObject('notify::height',
            () => this._queueRedisplay(), this);

        this._hideOverviewDash();
        this._backdrop = new OverviewBackdrop();
        this._gridTiles = new AppGridTiles();
        this._overviewAdjustment = Main.overview._overview?.controls?._stateAdjustment ?? null;
        this._overviewAdjustment?.connectObject('notify::value',
            () => this._docks.forEach(d => d.setOverviewProgress(this.overviewValue)), this);
        global.display.connectObject('workareas-changed', () => this._updateBackdrop(), this);
        this.fileDrop = new FileDrop(this);
        this._rebuild();
    }

    get docks() {
        return this._docks;
    }

    // --- Overview backdrop (see overviewBackdrop.js) --------------------

    _updateBackdrop() {
        // The band each space-reserving dock takes from the work area.
        const bands = [];
        if (this.hideMode === 'never') {
            for (const dock of this._docks) {
                const monitor = dock.monitor;
                if (!monitor)
                    continue;
                const area = Main.layoutManager.getWorkAreaForMonitor(dock.monitorIndex);
                const size = {
                    bottom: monitor.y + monitor.height - (area.y + area.height),
                    left: area.x - monitor.x,
                    right: monitor.x + monitor.width - (area.x + area.width),
                }[dock.position];
                if (size > 0)
                    bands.push({monitorIndex: dock.monitorIndex, edge: dock.position, size});
            }
        }
        this._backdrop.setDockBands(bands);
        this._backdrop.setAppGridBackground(
            this.appGridCustomTransparency ? this.appGridTransparency / 100 : 0,
            this.appGridCustomColor ? this.appGridColor : null);
        this._gridTiles.set({
            color: this.appGridFolderCustomColor ? this.appGridFolderColor : null,
            transparency: this.appGridFolderCustomTransparency ? this.appGridFolderTransparency : null,
        }, {
            color: this.appGridHoverCustomColor ? this.appGridHoverColor : null,
            transparency: this.appGridHoverCustomTransparency ? this.appGridHoverTransparency : null,
        });
    }

    // The overview state: 0 hidden, 1 window picker, 2 application grid.
    get overviewValue() {
        return this._overviewAdjustment?.value ?? 0;
    }

    // The look of the top bar in the overview: its background over the
    // overview background, from the current style. The bar only takes its
    // overview style once the overview starts showing; until then it is
    // taken as transparent, as in the GNOME styles.
    overviewLook() {
        const color = actor => {
            const c = actor.get_theme_node().get_background_color();
            return {red: c.red, green: c.green, blue: c.blue, alpha: c.alpha};
        };
        const panel = Main.panel.has_style_pseudo_class('overview')
            ? color(Main.panel) : {red: 0, green: 0, blue: 0, alpha: 0};
        return panelLook(panel, color(Main.layoutManager.overviewGroup));
    }

    _readSettings() {
        const s = this._settings;
        this.position = s.get_string('position');
        this.length = s.get_string('length');
        this.iconSize = s.get_int('icon-size');
        this.hideMode = s.get_string('hide-mode');
        this.monitorMode = s.get_string('monitor-mode');
        this.selectedMonitor = s.get_string('selected-monitor');
        this.showAppsButton = s.get_boolean('show-apps-button');
        this.appsButtonPosition = s.get_string('apps-button-position');
        this.appsButtonIcon = s.get_string('apps-button-icon');
        this.appsButtonCustomIcon = s.get_string('apps-button-custom-icon');
        this.magnify = s.get_boolean('magnify');
        this.magnifyStrength = s.get_double('magnify-strength');
        this.appGridCustomTransparency = s.get_boolean('app-grid-custom-transparency');
        this.appGridCustomColor = s.get_boolean('app-grid-custom-color');
        this.appGridColor = s.get_string('app-grid-color');
        this.backgroundCustomColor = s.get_boolean('background-custom-color');
        this.backgroundColor = s.get_string('background-color');
        this.backgroundCustomTransparency = s.get_boolean('background-custom-transparency');
        this.backgroundTransparency = s.get_int('background-transparency');
        this.appGridTransparency = s.get_int('app-grid-transparency');
        this.appGridFolderCustomColor = s.get_boolean('app-grid-folder-custom-color');
        this.appGridFolderColor = s.get_string('app-grid-folder-color');
        this.appGridFolderCustomTransparency = s.get_boolean('app-grid-folder-custom-transparency');
        this.appGridFolderTransparency = s.get_int('app-grid-folder-transparency');
        this.appGridHoverCustomColor = s.get_boolean('app-grid-hover-custom-color');
        this.appGridHoverColor = s.get_string('app-grid-hover-color');
        this.appGridHoverCustomTransparency = s.get_boolean('app-grid-hover-custom-transparency');
        this.appGridHoverTransparency = s.get_int('app-grid-hover-transparency');
        this.clickAction = s.get_string('click-action');
        this.isolateWorkspaces = s.get_boolean('isolate-workspaces');
        this.showAppCounts = s.get_boolean('show-app-counts');
        this.showAppProgress = s.get_boolean('show-app-progress');
        this.windowPreviews = s.get_boolean('window-previews');
        this.windowPeek = s.get_boolean('window-peek');
    }

    _onSettingChanged(key) {
        this._readSettings();
        // These change the dock structure or chrome tracking: recreate.
        if (['position', 'length', 'hide-mode', 'monitor-mode', 'selected-monitor'].includes(key))
            this._rebuild();
        else if (['magnify', 'magnify-strength'].includes(key))
            this._docks.forEach(d => {
                d.magnifier.sync();
                d.updateIconRendering();
            });
        else if (['apps-button-icon', 'apps-button-custom-icon'].includes(key))
            this._updateAppsButtonIcon();
        else if (key.startsWith('app-grid-'))
            this._updateBackdrop();
        else if (key.startsWith('background-'))
            this._docks.forEach(d => d.updateBackground());
        else if (key === 'window-previews')
            this.previews.close();
        else if (key === 'window-peek')
            this.previews.syncPeek();
        else if (key === 'folder-stack-view' || key === 'folder-stack-sorting')
            return; // read by the folder panel when it shows something
        else if (key === 'show-app-counts' || key === 'show-app-progress') {
            this.launcher.setListening(this.showAppCounts || this.showAppProgress);
            this._docks.forEach(d => d.updateLauncher());
        }
        else
            this._queueRedisplay();
    }

    // --- Applications button icon ---------------------------------------

    _setAppsButtonGicon(gicon) {
        this.appsButtonGicon = gicon;
        this._docks.forEach(d => d.updateAppsButtonIcon());
    }

    _updateAppsButtonIcon() {
        this._iconCancellable?.cancel();
        this._iconCancellable = null;
        const fallback = new Gio.ThemedIcon({name: APPS_ICON_NAME});

        if (this.appsButtonIcon === 'distribution') {
            this._setAppsButtonGicon(this._distributionLogo() ?? fallback);
        } else if (this.appsButtonIcon === 'custom' && this.appsButtonCustomIcon) {
            // Show the default icon until the image is known to load, so a
            // missing or broken file never leaves an empty button.
            this._setAppsButtonGicon(fallback);
            this._loadCustomIcon(this.appsButtonCustomIcon);
        } else {
            this._setAppsButtonGicon(fallback);
        }
    }

    // Only icons installed on the system; nothing is downloaded. The logo
    // is shown as a symbolic icon in the dock's foreground color: an
    // installed symbolic variant, or a silhouette derived from the colored
    // logo when that stays readable (logo.js); otherwise in its colors.
    _distributionLogo() {
        const theme = new St.IconTheme();
        const osInfo = {
            LOGO: GLib.get_os_info('LOGO'),
            ID: GLib.get_os_info('ID'),
        };
        const symbolic = symbolicLogoNames(osInfo).find(n => theme.has_icon(n));
        if (symbolic)
            return new Gio.ThemedIcon({name: symbolic});
        const name = distributionLogoNames(osInfo).find(n => theme.has_icon(n));
        if (!name)
            return null;
        return logoSilhouette(theme, name) ?? new Gio.ThemedIcon({name});
    }

    _loadCustomIcon(path) {
        const file = Gio.File.new_for_path(path);
        const cancellable = new Gio.Cancellable();
        this._iconCancellable = cancellable;
        const failed = message => {
            if (!cancellable.is_cancelled())
                console.warn(`Deskence: cannot use the applications button icon ${path}: ${message}`);
        };
        file.query_info_async('standard::size', Gio.FileQueryInfoFlags.NONE,
            GLib.PRIORITY_DEFAULT, cancellable, (_f, infoRes) => {
                try {
                    const info = file.query_info_finish(infoRes);
                    if (info.get_size() > MAX_CUSTOM_ICON_BYTES)
                        throw new Error('the file is too large');
                } catch (e) {
                    failed(e.message);
                    return;
                }
                file.read_async(GLib.PRIORITY_DEFAULT, cancellable, (_f2, readRes) => {
                    let stream;
                    try {
                        stream = file.read_finish(readRes);
                    } catch (e) {
                        failed(e.message);
                        return;
                    }
                    GdkPixbuf.Pixbuf.new_from_stream_at_scale_async(stream, 16, 16, true,
                        cancellable, (_p, pixbufRes) => {
                            stream.close_async(GLib.PRIORITY_DEFAULT, null, null);
                            try {
                                GdkPixbuf.Pixbuf.new_from_stream_finish(pixbufRes);
                            } catch (e) {
                                failed(e.message);
                                return;
                            }
                            if (cancellable !== this._iconCancellable)
                                return;
                            this._iconCancellable = null;
                            this._setAppsButtonGicon(new Gio.FileIcon({file}));
                        });
                });
            });
    }

    _trackWorkspaces() {
        const manager = global.workspace_manager;
        for (let i = 0; i < manager.get_n_workspaces(); i++) {
            const workspace = manager.get_workspace_by_index(i);
            workspace.disconnectObject(this);
            workspace.connectObject(
                'window-added', () => this._queueRedisplay(),
                'window-removed', () => this._queueRedisplay(),
                this);
        }
    }

    _monitorIndices() {
        const layout = Main.layoutManager;
        if (this.monitorMode === 'all')
            return layout.monitors.map(m => m.index);
        if (this.monitorMode === 'selected' && this.selectedMonitor) {
            const monitorManager = global.backend.get_monitor_manager();
            const index = monitorManager.get_monitor_for_connector(this.selectedMonitor);
            if (index >= 0 && index < layout.monitors.length)
                return [index];
        }
        return [layout.primaryIndex];
    }

    _rebuild() {
        this.fileDrop?.cancel();
        this._docks.forEach(d => d.destroy());
        this._docks = [];
        if (Main.layoutManager.monitors.length === 0)
            return;
        for (const index of this._monitorIndices())
            this._docks.push(new Dock(this, index));
        this.updateOverviewSpace();
        this._updateBackdrop();
    }

    // Rebuild at once, dropping a queued rebuild (used after a drop, so the
    // dock never shows an intermediate order).
    redisplayNow() {
        if (this._redisplayId)
            GLib.source_remove(this._redisplayId);
        this._redisplayId = 0;
        this._docks.forEach(d => d.redisplay());
    }

    _queueRedisplay() {
        if (this._redisplayId)
            return;
        this._redisplayId = GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            this._redisplayId = 0;
            this._docks.forEach(d => d.redisplay());
            return GLib.SOURCE_REMOVE;
        });
    }

    windowsForApp(app) {
        const workspace = global.workspace_manager.get_active_workspace();
        return app.get_windows().filter(w => isNormalWindow(w) &&
            (!this.isolateWorkspaces || w.located_on_workspace(workspace)));
    }

    // Favorites first (always shown), then running applications in the
    // order they were started.
    dockApps() {
        const favorites = AppFavorites.getAppFavorites().getFavorites();
        const favoriteIds = new Set(favorites.map(a => a.get_id()));
        const result = favorites.map(app => ({app, pinned: true}));

        const running = this._appSystem.get_running().filter(app =>
            !favoriteIds.has(app.get_id()) && this.windowsForApp(app).length > 0);
        const ids = running.map(a => a.get_id());
        this._runningOrder = this._runningOrder.filter(id => ids.includes(id));
        for (const id of ids) {
            if (!this._runningOrder.includes(id))
                this._runningOrder.push(id);
        }
        running.sort((a, b) =>
            this._runningOrder.indexOf(a.get_id()) - this._runningOrder.indexOf(b.get_id()));
        return result.concat(running.map(app => ({app, pinned: false})));
    }

    syncShowAppsButtons() {
        this._docks.forEach(d => d.syncShowApps());
    }

    _onOverviewChanged() {
        this.previews.close();
        if (Main.overview.visibleTarget)
            this.stackPanel.close();
        this._docks.forEach(d => d.onOverviewChanged());
    }

    _onDragBegin() {
        this.dragInProgress = true;
        this.previews.close();
        this._docks.forEach(d => d.magnifier.relax());
        this._dragMonitor = {
            dragMotion: event => {
                this._docks.forEach(d => d.onDragMotion(event));
                return DND.DragMotionResult.CONTINUE;
            },
        };
        DND.addDragMonitor(this._dragMonitor);
        this._docks.forEach(d => d.onOverviewChanged());
    }

    // Files dragged from an application (fileDrop.js). The icons keep their
    // size, as during GNOME Shell drags, so targets do not move.
    fileDragBegin() {
        this.fileDragInProgress = true;
        this.previews.close();
        this._docks.forEach(d => {
            d.magnifier.relax();
            d.hideLabels();
        });
    }

    fileDragEnd() {
        this.fileDragInProgress = false;
        this.stackPanel.closeForDrag();
        this._docks.forEach(d => d.endFileDrag());
    }

    _onDragEnd() {
        this.dragInProgress = false;
        if (this._dragMonitor)
            DND.removeDragMonitor(this._dragMonitor);
        this._dragMonitor = null;
        this._docks.forEach(d => {
            d.clearPlaceholder();
            d.onOverviewChanged();
        });
    }

    // --- Overview integration -------------------------------------------
    //
    // The overview's own dash is hidden while the dock is enabled. The space
    // it used is kept for the dock: at the bottom through the height of the
    // hidden dash, at the sides through margins of the overview controls.

    _hideOverviewDash() {
        const dash = Main.overview.dash;
        dash.hide();
        this._overviewControls = Main.overview._overview?.controls ?? null;
    }

    updateOverviewSpace() {
        const dash = Main.overview.dash;
        const primary = this._docks.find(d => d.monitorIndex === Main.layoutManager.primaryIndex);
        const extent = primary?.extent ?? 0;
        dash.set_height(this.position === 'bottom' ? extent : 0);
        if (this._overviewControls) {
            this._overviewControls.margin_left = this.position === 'left' ? extent : 0;
            this._overviewControls.margin_right = this.position === 'right' ? extent : 0;
        }
    }

    _restoreOverviewDash() {
        const dash = Main.overview.dash;
        dash.set_height(-1);
        dash.show();
        if (this._overviewControls) {
            this._overviewControls.margin_left = 0;
            this._overviewControls.margin_right = 0;
        }
        this._overviewControls = null;
    }

    destroy() {
        if (this._redisplayId)
            GLib.source_remove(this._redisplayId);
        this._redisplayId = 0;
        this._iconCancellable?.cancel();
        this._iconCancellable = null;
        if (this._dragMonitor)
            DND.removeDragMonitor(this._dragMonitor);
        this._dragMonitor = null;

        this.previews.close();
        this.fileDrop.destroy();
        this.fileDrop = null;
        this.stackPanel.destroy();
        this.launcher.destroy();
        this._docks.forEach(d => d.destroy());
        this._docks = [];

        this._settings.disconnectObject(this);
        Main.layoutManager.disconnectObject(this);
        AppFavorites.getAppFavorites().disconnectObject(this);
        this._appSystem.disconnectObject(this);
        Shell.WindowTracker.get_default().disconnectObject(this);
        global.workspace_manager.disconnectObject(this);
        const manager = global.workspace_manager;
        for (let i = 0; i < manager.get_n_workspaces(); i++)
            manager.get_workspace_by_index(i).disconnectObject(this);
        Main.overview.disconnectObject(this);
        Main.overview.dash.showAppsButton.disconnectObject(this);
        Main.layoutManager.panelBox.disconnectObject(this);

        global.display.disconnectObject(this);
        this._backdrop.destroy();
        this._backdrop = null;
        this._gridTiles.destroy();
        this._gridTiles = null;
        this._overviewAdjustment?.disconnectObject(this);
        this._overviewAdjustment = null;
        this.overlapTracker.destroy();
        this.locations.disconnectObject(this);
        this.locations.destroy();
        this.stacks.disconnectObject(this);
        this.stacks.destroy();
        this._restoreOverviewDash();
        this.previews.destroy();
        this.previews = null;
        this._settings = null;
    }
}
