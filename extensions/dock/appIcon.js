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

import {badgeGeometry, badgeText} from './launcherLogic.js';
import {DOT_SIZE, DOT_SPACING} from './logic.js';

const MAX_INDICATOR_DOTS = 4;
const ACTIVE_DOTS_CLASS = 'deskence-dock-dots-active';

// Holds a mark of a dock item (window dots, folder marker, counter). The
// mark is drawn at a whole multiple of its size, as large as it is shown
// at full magnification (Dock.markScale), and scaled down, so magnifying
// brings it back to its own size instead of stretching a small texture.
// The holder asks for no room: the mark is laid out larger than it looks,
// and the item must not grow with it, or the dock would think its items
// do not fit. The mark is placed by its size as shown, on whole pixels,
// so it is sharp at rest too.
//   place: the edge of the item it lies at: 'bottom', 'left', 'right'
//     (centered along it) or 'top-right' (the corner)
//   inset: distance from that edge, in logical pixels as shown
export const MarkHolder = GObject.registerClass(
class MarkHolder extends St.Widget {
    _init(place, mark) {
        super._init({x_expand: true, y_expand: true});
        this.place = place;
        this._inset = 0;
        this._scale = 1;
        mark.set_pivot_point(0, 0);
        this.add_child(mark);
    }

    setScale(scale, inset = 0) {
        this._scale = scale;
        this._inset = inset;
        this.get_first_child().set_scale(1 / scale, 1 / scale);
        this.queue_relayout();
    }

    vfunc_get_preferred_width() {
        return [0, 0];
    }

    vfunc_get_preferred_height() {
        return [0, 0];
    }

    vfunc_allocate(box) {
        this.set_allocation(box);
        const mark = this.get_first_child();
        const [,, width, height] = mark.get_preferred_size();
        const shownWidth = width / this._scale;
        const shownHeight = height / this._scale;
        const room = [box.get_width(), box.get_height()];
        const middle = [(room[0] - shownWidth) / 2, (room[1] - shownHeight) / 2];
        const end = [room[0] - shownWidth - this._inset, room[1] - shownHeight - this._inset];
        const [x, y] = {
            'bottom': [middle[0], end[1]],
            'left': [this._inset, middle[1]],
            'right': [end[0], middle[1]],
            'top-right': [end[0], this._inset],
        }[this.place];
        const child = new Clutter.ActorBox();
        child.set_origin(Math.round(x), Math.round(y));
        child.set_size(width, height);
        mark.allocate(child);
    }
});

// The edge of an item its window dots or folder marker lie at: under it in
// a bottom dock, on the side facing the inside of the screen in a side dock.
export function markPlace(dockPosition) {
    return {bottom: 'bottom', left: 'right', right: 'left'}[dockPosition];
}

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
        this._dots = new St.BoxLayout({style_class: 'deskence-dock-dots'});
        this._dotsHolder = new MarkHolder(markPlace(dock.position), this._dots);
        setVertical(this._dots, dock.position !== 'bottom');
        this._iconContainer.add_child(this._dotsHolder);

        this.app.connectObject('windows-changed', () => this.sync(), this);
        this.sync();

        // What the application reports (launcherEntry.js): a counter at
        // the corner of the icon and progress along its lower edge, above
        // the window dots. Both lie over the icon, so the tile keeps its
        // size and they scale with a magnified icon. The counter is a bin,
        // which centers the digits in the circle.
        this._badgeLabel = new St.Label({
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._badge = new St.Bin({
            style_class: 'deskence-dock-badge',
            child: this._badgeLabel,
            visible: false,
        });
        this._badgeHolder = new MarkHolder('top-right', this._badge);
        this.styleMarks();
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
        this._iconContainer.add_child(this._badgeHolder);
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
            this._badgeLabel.text = badgeText(count);
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

    // The window dots sit under the icon in a bottom dock and on the side
    // facing the inside of the screen in a side dock (markPlace). They lie
    // in the padding of the tile, next to the icon, so they never cover the
    // icon and scale together with a magnified icon: the magnifier grows a
    // tile from its edge at the screen border, so dots at that edge stay
    // inside the dock.

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
        if (count > current)
            this._styleDots();

        // The focused application is told apart by the color of its dots
        // only; the tile itself stays transparent.
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
        this.styleMarks();
    }

    // The dots and the counter at the scale they are drawn at (MarkHolder),
    // for the current icon size and magnification.
    styleMarks() {
        if (!this._badge)
            return;
        this._styleDots();
        // St's min-width leaves out the padding: one digit gives a circle
        // of the diameter, more digits a wider pill.
        const g = badgeGeometry(this._dock.iconSize, this._dock.markScale);
        this._badge.style = `min-width: ${g.diameter - 2 * g.padding}px; ` +
            `min-height: ${g.diameter}px; border-radius: ${Math.ceil(g.diameter / 2)}px; ` +
            `padding: 0 ${g.padding}px; font-size: ${g.fontSize}px;`;
        this._badgeHolder.setScale(g.scale, g.margin);
    }

    // Every dot the same round size (DOT_SIZE, DOT_SPACING in
    // logic.js), whether the application has focus or not.
    _styleDots() {
        const scale = this._dock.markScale;
        const size = DOT_SIZE * scale;
        this._dots.style = `spacing: ${DOT_SPACING * scale}px;`;
        for (const dot of this._dots.get_children())
            dot.style = `width: ${size}px; height: ${size}px; border-radius: ${size / 2}px;`;
        this._dotsHolder.setScale(scale);
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
