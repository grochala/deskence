// SPDX-License-Identifier: GPL-3.0-or-later
//
// Peeking at a window from its preview in the dock.
//
// The other windows are dimmed by a veil laid over the window layer (below
// the top bar, the dock and the previews panel), and a live clone of the
// window is drawn over the veil where the window is. Windows themselves are
// never touched: no focus, raising, restacking, unminimizing, opacity or
// workspace change, so ending the peek - leaving the preview, Escape,
// closing the panel, a window appearing, turning the extension off - only
// removes the veil and the clone.
//
// A window that is minimized or on another workspace is not where the
// clone would be drawn; it is shown enlarged in the free part of the dock's
// work area (beside the previews panel) instead (its content when there is some, otherwise the
// application icon with the title), so nothing about it changes either.

import Clutter from 'gi://Clutter';
import Pango from 'gi://Pango';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {setVertical} from './appIcon.js';

const FADE_TIME = 150;
const VEIL_OPACITY = 150;
// Largest share of the work area an enlarged window takes.
const ENLARGED_SHARE = 0.7;
const ICON_SIZE = 128;

export function hasContent(window) {
    if (window.minimized)
        return false;
    const actor = window.get_compositor_private();
    if (!actor)
        return false;
    const texture = actor.get_texture?.();
    if (!texture)
        return actor.width > 0 && actor.height > 0;
    const [ok, width, height] = texture.get_preferred_size?.() ?? [true, actor.width, actor.height];
    return ok && width > 0 && height > 0;
}

// Where a window is drawn when peeking: at its place when it is visible on
// the active workspace, otherwise enlarged in the work area.
export function shownInPlace(window) {
    return !window.minimized && hasContent(window) &&
        window.located_on_workspace(global.workspace_manager.get_active_workspace());
}

export class WindowPeek {
    constructor() {
        this._veil = null;
        this._content = null;
        this._window = null;
    }

    get window() {
        return this._window;
    }

    get active() {
        return this._veil !== null;
    }

    // Shows a window over the dimmed others; another window while peeking
    // replaces the clone only, so moving between previews does not flicker.
    // room: the free rectangle for an enlarged window ({x, y, width,
    // height}).
    show(window, app, room) {
        if (this._window === window)
            return;
        if (!this._veil) {
            this._veil = new St.Widget({
                style_class: 'deskence-window-peek-veil',
                reactive: false,
                opacity: 0,
                x: 0,
                y: 0,
                width: global.stage.width,
                height: global.stage.height,
            });
            Main.layoutManager.uiGroup.insert_child_above(this._veil, global.window_group);
            this._veil.ease({opacity: VEIL_OPACITY, duration: FADE_TIME,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD});
        }
        this._content?.destroy();
        this._window = window;
        this._content = shownInPlace(window)
            ? this._inPlace(window)
            : this._enlarged(window, app, room);
        Main.layoutManager.uiGroup.insert_child_above(this._content, this._veil);
        window.connectObject('unmanaged', () => this.hide(true), this._content);
    }

    _inPlace(window) {
        const actor = window.get_compositor_private();
        return new Clutter.Clone({
            source: actor,
            x: actor.x,
            y: actor.y,
            width: actor.width,
            height: actor.height,
            reactive: false,
        });
    }

    _enlarged(window, app, area) {
        const card = new St.BoxLayout({
            style_class: 'deskence-window-peek-card',
            reactive: false,
        });
        setVertical(card, true);
        const maxWidth = area.width * ENLARGED_SHARE;
        const maxHeight = area.height * ENLARGED_SHARE;
        if (hasContent(window)) {
            const actor = window.get_compositor_private();
            const frame = window.get_frame_rect();
            const scale = Math.min(1, maxWidth / Math.max(1, frame.width),
                maxHeight / Math.max(1, frame.height));
            const box = new St.Widget({
                width: Math.round(frame.width * scale),
                height: Math.round(frame.height * scale),
                clip_to_allocation: true,
                layout_manager: new Clutter.FixedLayout(),
            });
            box.add_child(new Clutter.Clone({
                source: actor,
                width: actor.width * scale,
                height: actor.height * scale,
                x: (actor.x - frame.x) * scale,
                y: (actor.y - frame.y) * scale,
            }));
            card.add_child(box);
        } else {
            const icon = app.create_icon_texture(ICON_SIZE);
            icon.x_align = Clutter.ActorAlign.CENTER;
            card.add_child(icon);
            const title = new St.Label({
                style_class: 'deskence-window-peek-title',
                text: window.get_title() ?? app.get_name(),
                x_align: Clutter.ActorAlign.CENTER,
            });
            title.clutter_text.ellipsize = Pango.EllipsizeMode.END;
            title.style = `max-width: ${Math.round(maxWidth)}px;`;
            card.add_child(title);
        }
        const [, width] = card.get_preferred_width(-1);
        const [, height] = card.get_preferred_height(width);
        card.set_position(Math.round(area.x + (area.width - width) / 2),
            Math.round(area.y + (area.height - height) / 2));
        return card;
    }

    // immediate: without fading out (the window went away, the extension
    // is turned off).
    hide(immediate = false) {
        if (!this._veil)
            return;
        const veil = this._veil;
        this._veil = null;
        this._window = null;
        this._content?.destroy();
        this._content = null;
        veil.remove_all_transitions();
        if (immediate) {
            veil.destroy();
            return;
        }
        veil.ease({
            opacity: 0,
            duration: FADE_TIME,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onStopped: () => veil.destroy(),
        });
    }

    destroy() {
        this.hide(true);
    }
}
