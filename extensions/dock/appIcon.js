// SPDX-License-Identifier: GPL-3.0-or-later
//
// Dock application icon. Builds on the stock GNOME Shell AppIcon so the icon,
// focus ring, application menu (desktop file actions, windows, pin/unpin,
// quit) and drag source behave exactly like in the overview dash.

import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as AppDisplay from 'resource:///org/gnome/shell/ui/appDisplay.js';
import * as DND from 'resource:///org/gnome/shell/ui/dnd.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {ngettext} from 'resource:///org/gnome/shell/extensions/extension.js';

import {badgeText} from './launcherLogic.js';

const MAX_INDICATOR_DOTS = 4;
const ACTIVE_DOTS_CLASS = 'deskence-dock-dots-active';

export const DockAppIcon = GObject.registerClass({
    GTypeName: 'DeskenceDockAppIcon',
}, class DockAppIcon extends AppDisplay.AppIcon {
    _init(app, dock) {
        super._init(app, {
            setSizeManually: true,
            showLabel: false,
        });
        this._dock = dock;
        // GNOME 49+ reads the menu side from this field, GNOME 48 takes it
        // as an argument of popupMenu(); see popupMenu() below.
        this._popupMenuSide = dock.menuSide;
        this.accessible_name = app.get_name();

        // Replace the single "running" dot by one dot per window.
        this._dot.hide();
        this._dots = new St.BoxLayout({
            style_class: 'deskence-dock-dots',
            x_expand: true,
            y_expand: true,
        });
        this._iconContainer.add_child(this._dots);
        this._alignDots();

        this.app.connectObject('windows-changed', () => this.sync(), this);
        this.sync();

        // What the application reports (launcherEntry.js): a counter at
        // the corner of the icon and progress along its lower edge, above
        // the window dots. Both lie over the icon, so the tile keeps its
        // size and they scale with a magnified icon.
        this._badge = new St.Label({
            style_class: 'deskence-dock-badge',
            x_align: Clutter.ActorAlign.END,
            y_align: Clutter.ActorAlign.START,
            x_expand: true,
            y_expand: true,
            visible: false,
        });
        this._badge.clutter_text.x_align = Clutter.ActorAlign.CENTER;
        // The fill is placed by hand from the start of the track.
        this._progressTrack = new St.Widget({
            style_class: 'deskence-dock-progress',
            x_align: Clutter.ActorAlign.FILL,
            y_align: Clutter.ActorAlign.END,
            x_expand: true,
            y_expand: true,
            visible: false,
        });
        this._progressFill = new St.Widget({style_class: 'deskence-dock-progress-fill'});
        this._progressTrack.add_child(this._progressFill);
        this._progressTrack.connect('notify::size', () => this._layoutProgress());
        this._progress = null;
        this._iconContainer.add_child(this._progressTrack);
        this._iconContainer.add_child(this._badge);
        this.updateLauncher();
    }

    // The counter and progress of the application, as far as the dock
    // settings show them.
    updateLauncher() {
        if (!this._badge)
            return;
        const manager = this._dock.manager;
        const state = manager.launcher.get(this.app.get_id());
        const count = manager.showAppCounts ? state.count : null;
        this._badge.visible = count !== null;
        if (count !== null)
            this._badge.text = badgeText(count);
        // Screen readers hear the counter with the name, not every change
        // of the progress.
        this.accessible_name = count === null ? this.app.get_name()
            : ngettext('%s, %d new item', '%s, %d new items', count)
                .replace('%s', this.app.get_name()).replace('%d', count);
        this._progress = manager.showAppProgress ? state.progress : null;
        this._progressTrack.visible = this._progress !== null;
        this._layoutProgress();
    }

    _layoutProgress() {
        if (this._progress === null)
            return;
        this._progressFill.set_position(0, 0);
        this._progressFill.set_size(Math.round(this._progressTrack.width * this._progress),
            this._progressTrack.height);
    }

    // The indicators sit under the icon in a bottom dock and on the side
    // facing the inside of the screen in a side dock (right of the icon on
    // the left, left of it on the right). They lie in the padding of the
    // tile, next to the icon, so they take no room of their own, never
    // cover the icon and scale together with a magnified icon: the
    // magnifier grows a tile from its edge at the screen border, so dots
    // at that edge stay inside the dock.
    _alignDots() {
        const side = this._dock.position;
        setVertical(this._dots, side !== 'bottom');
        if (side === 'bottom') {
            this._dots.x_align = Clutter.ActorAlign.CENTER;
            this._dots.y_align = Clutter.ActorAlign.END;
        } else {
            this._dots.x_align = side === 'left' ? Clutter.ActorAlign.END : Clutter.ActorAlign.START;
            this._dots.y_align = Clutter.ActorAlign.CENTER;
        }
    }

    // Icons are rendered at the largest size they are shown at (see
    // Dock.iconRenderSize) and drawn into the normal icon size, so the
    // layout does not change and magnified icons stay sharp.
    _createIcon(iconSize) {
        if (!this._dock)
            return super._createIcon(iconSize);
        const icon = this.app.create_icon_texture(this._dock.iconRenderSize(iconSize));
        icon.set_size(iconSize, iconSize);
        return icon;
    }

    _updateRunningStyle() {
        // Called by the parent constructor before our fields exist.
        if (!this._dots) {
            this._dot?.hide();
            return;
        }
        this.sync();
    }

    sync() {
        if (!this._dots)
            return;
        const windows = this._dock.manager.windowsForApp(this.app);
        let count = windows.length;
        if (count === 0 && this.app.state !== Shell.AppState.STOPPED &&
            !this._dock.manager.isolateWorkspaces)
            count = 1;
        count = Math.min(count, MAX_INDICATOR_DOTS);

        const current = this._dots.get_n_children();
        for (let i = current; i < count; i++)
            this._dots.add_child(new St.Widget({style_class: 'app-grid-running-dot'}));
        for (let i = current - 1; i >= count; i--)
            this._dots.get_child_at_index(i).destroy();

        // The focused application is told apart by its indicators only;
        // the tile itself stays transparent.
        const focused = Shell.WindowTracker.get_default().focus_app === this.app;
        if (focused && count > 0)
            this._dots.add_style_class_name(ACTIVE_DOTS_CLASS);
        else
            this._dots.remove_style_class_name(ACTIVE_DOTS_CLASS);
    }

    // The dock handles drops itself (reordering), not single icons.
    scaleAndFade() {
    }

    undoScaleAndFade() {
    }

    handleDragOver() {
        return DND.DragMotionResult.CONTINUE;
    }

    acceptDrop() {
        return false;
    }

    getDragActor() {
        return this.app.create_icon_texture(this._dock.iconSize);
    }

    // A new rendering size (magnification turned on or off).
    updateIconRendering() {
        this.icon.update();
    }

    popupMenu() {
        super.popupMenu(this._dock.menuSide);
        return false;
    }

    // Click behavior, see the "click-action" key in the GSettings schema:
    //  - stopped application: launch it;
    //  - middle click or Ctrl+click: open a new window;
    //  - not focused: focus its most recently used window;
    //  - focused with several windows: switch to the next window in a
    //    stable order (so repeated clicks visit every window);
    //  - focused with one window: nothing, or minimize it with
    //    "minimize-or-cycle".
    activate(button) {
        const event = Clutter.get_current_event();
        const modifiers = event ? event.get_state() : 0;
        const isMiddle = button === Clutter.BUTTON_MIDDLE;
        const isCtrl = (modifiers & Clutter.ModifierType.CONTROL_MASK) !== 0;
        const manager = this._dock.manager;
        const windows = manager.windowsForApp(this.app);

        if (this.app.state === Shell.AppState.STOPPED) {
            this.animateLaunch();
            this.app.activate();
        } else if ((isMiddle || isCtrl) && this.app.can_open_new_window()) {
            this.animateLaunch();
            this.app.open_new_window(-1);
        } else if (windows.length === 0) {
            // Running only on other workspaces while workspaces are
            // isolated: open a window here, as the user asked for the app.
            if (this.app.can_open_new_window())
                this.app.open_new_window(-1);
            else
                this.app.activate();
        } else {
            const focusApp = Shell.WindowTracker.get_default().focus_app;
            if (focusApp !== this.app) {
                Main.activateWindow(windows[0]);
            } else if (windows.length > 1) {
                const ordered = [...windows].sort(
                    (a, b) => a.get_stable_sequence() - b.get_stable_sequence());
                const focusWindow = global.display.focus_window;
                const index = ordered.indexOf(focusWindow);
                Main.activateWindow(ordered[(index + 1) % ordered.length]);
            } else if (manager.clickAction === 'minimize-or-cycle' &&
                       windows[0].can_minimize()) {
                windows[0].minimize();
            } else {
                Main.activateWindow(windows[0]);
            }
        }

        Main.overview.hide();
    }
});

// St.BoxLayout:vertical is deprecated since GNOME 48 in favour of
// orientation; support both.
export function setVertical(box, vertical) {
    if ('orientation' in box)
        box.orientation = vertical ? Clutter.Orientation.VERTICAL : Clutter.Orientation.HORIZONTAL;
    else
        box.vertical = vertical;
}

export function isNormalWindow(window) {
    const type = window.get_window_type();
    return !window.skip_taskbar &&
        (type === Meta.WindowType.NORMAL ||
         type === Meta.WindowType.DIALOG ||
         type === Meta.WindowType.MODAL_DIALOG ||
         type === Meta.WindowType.UTILITY);
}
