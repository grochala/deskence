// SPDX-License-Identifier: GPL-3.0-or-later
//
// Magnification of dock icons near the pointer; the math is in logic.js.
//
// Nothing runs while the effect is off: the event handler is connected only
// when it is enabled, the icons are only updated on pointer motion and while
// growing or shrinking back, and GNOME's "Animations" setting turned off
// disables the effect.
//
// The dock is split into zones that magnify independently (see
// Dock.magnifyZones()): the item list and, when it is not part of the list's
// row (whole-edge dock, scrolled list), the applications button. Only the
// zone under the pointer grows; the other one shrinks back. Hovering the
// button therefore never moves, resizes or scrolls the list, and hovering
// the list never moves the button. No room is kept between them: the
// button grows only as far as the first icon of the list. Everything is
// done with transforms: the layout of the dock never changes.

import Clutter from 'gi://Clutter';
import St from 'gi://St';

import {amountForRoom, fitInView, limitScale, magnify, maxMagnifyShift} from './logic.js';

const FADE_TIME = 160;
// Icons up to this many item lengths from the pointer grow.
const RADIUS_ITEMS = 2.25;

// Growing or shrinking back of one zone.
class Zone {
    constructor(magnifier, name) {
        this._magnifier = magnifier;
        this.name = name;
        this.progress = 0;
        this.target = 0;
        this.pointer = null;
        this._timeline = null;
    }

    get animating() {
        return this._timeline !== null;
    }

    stop() {
        if (!this._timeline)
            return;
        this._timeline.stop();
        this._timeline = null;
    }

    reset() {
        this.stop();
        this.progress = 0;
        this.target = 0;
        this.pointer = null;
    }

    fadeTo(target, actor) {
        if (this.target === target && (this._timeline || this.progress === target))
            return;
        this.stop();
        this.target = target;
        const from = this.progress;
        const timeline = new Clutter.Timeline({
            actor,
            duration: Math.max(1, Math.round(FADE_TIME * Math.abs(target - from))),
        });
        timeline.connect('new-frame', () => {
            const t = timeline.get_progress();
            this.progress = from + (target - from) * (1 - (1 - t) * (1 - t));
            this._magnifier.apply();
        });
        timeline.connect('completed', () => {
            if (this._timeline !== timeline)
                return;
            this._timeline = null;
            this.progress = target;
            if (target === 0)
                this.pointer = null;
            this._magnifier.apply();
        });
        this._timeline = timeline;
        timeline.start();
    }
}

export class Magnifier {
    // dock: the Dock, providing dash (the reactive dock actor), box (the
    // items), background (stretched to cover moved icons),
    // magnifyZones(), visibleSpan(), itemExtent() and updateClip().
    constructor(dock) {
        this._dock = dock;
        this._zones = new Map();
        this._frozen = false;
        this._eventId = 0;
        // Actors given a transform, so they are reset when they leave a zone.
        this._touched = new Set();
        this._settings = St.Settings.get();
        this._settings.connectObject('notify::enable-animations', () => {
            this.sync();
            this._dock.updateIconRendering();
        }, this);
    }

    get enabled() {
        const manager = this._dock.manager;
        return manager.magnify && this._settings.enable_animations;
    }

    // The largest scale icons are shown at.
    get maxScale() {
        return this.enabled ? this._dock.manager.magnifyStrength : 1;
    }

    get _amount() {
        return this._dock.manager.magnifyStrength - 1;
    }

    _vertical() {
        return this._dock.position !== 'bottom';
    }

    _radius() {
        const item = this._dock.itemExtent();
        return Math.max(item, 1) * RADIUS_ITEMS;
    }

    _zone(name) {
        let zone = this._zones.get(name);
        if (!zone) {
            zone = new Zone(this, name);
            this._zones.set(name, zone);
        }
        return zone;
    }

    // How far magnified icons can reach beyond the dock, for the clip of
    // the dock holder: [across the dock (inwards), along it (each end)].
    overflow() {
        if (!this.enabled)
            return [0, 0];
        return [
            Math.ceil(this._dock.itemExtent() * this._amount) + 4,
            Math.ceil(maxMagnifyShift(this._amount, this._radius())) + 4,
        ];
    }

    // Called when the settings or the dock change.
    sync() {
        const dash = this._dock.dash;
        if (this.enabled && !this._eventId) {
            this._eventId = dash.connect('captured-event', (_a, event) => this._onEvent(event));
            dash.connectObject('notify::hover', () => {
                if (!dash.hover)
                    this.relax();
            }, this);
            // Items added, removed or resized while magnified.
            this._dock.box.connectObject('notify::allocation', () => {
                if (this._active())
                    this.apply();
            }, this);
        } else if (!this.enabled && this._eventId) {
            dash.disconnect(this._eventId);
            this._eventId = 0;
            dash.disconnectObject(this);
            this._dock.box.disconnectObject(this);
            this.reset();
        }
        this._dock.updateClip();
    }

    _active() {
        return [...this._zones.values()].some(z => z.progress > 0);
    }

    // While a menu is open the icons stay as they are, so the menu keeps
    // pointing at its icon.
    setFrozen(frozen) {
        this._frozen = frozen;
        if (!frozen && !this._dock.dash.hover)
            this.relax();
    }

    _onEvent(event) {
        const type = event.type();
        if (type !== Clutter.EventType.MOTION && type !== Clutter.EventType.ENTER)
            return Clutter.EVENT_PROPAGATE;
        if (this._frozen || this._dock.manager.dragInProgress || this._dock.manager.fileDragInProgress ||
            !this._dock.shown)
            return Clutter.EVENT_PROPAGATE;
        const [x, y] = event.get_coords();
        const zones = this._dock.magnifyZones();
        const hit = zones.find(z => z.contains(x, y)) ?? null;
        for (const info of zones) {
            const zone = this._zone(info.name);
            if (info === hit) {
                const position = info.locate(x, y);
                if (position === null)
                    continue;
                zone.pointer = position;
                if (zone.target !== 1)
                    zone.fadeTo(1, this._dock.dash);
            } else if (zone.progress > 0 || zone.target > 0) {
                zone.fadeTo(0, this._dock.dash);
            }
        }
        if (![...this._zones.values()].some(z => z.animating))
            this.apply();
        return Clutter.EVENT_PROPAGATE;
    }

    // Back to normal size, smoothly.
    relax() {
        if (this._frozen)
            return;
        for (const zone of this._zones.values()) {
            if (zone.progress > 0 || zone.target > 0)
                zone.fadeTo(0, this._dock.dash);
        }
    }

    // Back to normal size at once.
    reset() {
        this._zones.forEach(z => z.reset());
        this.apply();
    }

    apply() {
        const dock = this._dock;
        const vertical = this._vertical();
        const pivot = {
            bottom: [0.5, 1],
            left: [0, 0.5],
            right: [1, 0.5],
        }[dock.position];
        const placed = new Set();
        let stretch = null;

        for (const info of dock.magnifyZones()) {
            const zone = this._zone(info.name);
            const targets = info.targets;
            const active = zone.progress > 0 && zone.pointer !== null;
            // A list with limited spare room grows only as much as fits.
            const amount = info.room !== undefined
                ? amountForRoom(this._amount, info.room, this._radius())
                : this._amount;
            const results = active
                ? magnify(targets.map(t => t.span), zone.pointer, amount, this._radius(),
                    zone.progress)
                : null;
            if (results && info.keepInView)
                this._fitInView(targets, results, zone.pointer);
            // Grows in place from its pivot, at most to info.maxScale.
            if (results && info.scaleOnly) {
                const strength = this._dock.manager.magnifyStrength;
                results.forEach(r => {
                    r.shift = 0;
                    if (info.maxScale !== undefined)
                        r.scale = limitScale(r.scale, strength, info.maxScale);
                });
            }

            targets.forEach(({actor, button}, i) => {
                const {scale, shift} = results ? results[i] : {scale: 1, shift: 0};
                // Buttons scale; separators only move.
                if (button) {
                    button.set_pivot_point(...(info.pivot ?? pivot));
                    button.set_scale(scale, scale);
                    placed.add(button);
                }
                actor.translation_x = vertical ? 0 : shift;
                actor.translation_y = vertical ? shift : 0;
                placed.add(actor);
            });
            if (info.stretchBackground && results)
                stretch = {pointer: zone.pointer, progress: zone.progress, targets};
        }

        for (const actor of this._touched) {
            if (placed.has(actor))
                continue;
            actor.disconnectObject(this);
            actor.set_scale(1, 1);
            actor.translation_x = 0;
            actor.translation_y = 0;
        }
        // Items destroyed while transformed (the dock was rebuilt) are
        // forgotten, never touched again.
        for (const actor of placed) {
            if (!this._touched.has(actor))
                actor.connectObject('destroy', () => this._touched.delete(actor), this);
        }
        this._touched = placed;
        this._stretchBackground(stretch);
    }

    // A list that is clipped along the dock (scrolling, whole-edge dock):
    // magnified icons that are entirely in view at normal size are moved
    // back inside instead of being cut by the edge of the view (next to
    // the applications button, or the screen edge). Icons already cut by
    // scrolling stay cut, so hovering never scrolls the list. When both
    // ends cannot be kept (a scrolled list), the end near the pointer is.
    _fitInView(targets, results, pointer) {
        const view = this._dock.visibleSpan();
        if (!view)
            return;
        const correction = fitInView(targets.map(t => t.span), results, view, pointer);
        if (correction !== 0)
            results.forEach(r => (r.shift += correction));
    }

    // In a short dock the icons at the ends move outwards; the background
    // follows them so they stay on the dock.
    _stretchBackground(stretch) {
        const background = this._dock.background;
        if (!stretch || stretch.targets.length === 0) {
            background.set_scale(1, 1);
            background.translation_x = 0;
            background.translation_y = 0;
            return;
        }
        const {pointer, progress, targets} = stretch;
        const vertical = this._vertical();
        const total = vertical ? background.height : background.width;
        const low = targets[0].span[0];
        const high = targets.at(-1).span[1];
        if (high <= low || total <= 0)
            return;
        const [first, last] = magnify([[low, low], [high, high]], pointer, this._amount,
            this._radius(), progress);
        const before = Math.max(0, -first.shift);
        const after = Math.max(0, last.shift);
        const scale = (total + before + after) / total;
        background.set_pivot_point(0.5, 0.5);
        if (vertical) {
            background.set_scale(1, scale);
            background.translation_y = (after - before) / 2;
        } else {
            background.set_scale(scale, 1);
            background.translation_x = (after - before) / 2;
        }
    }

    destroy() {
        this._zones.forEach(z => z.stop());
        this._touched.forEach(actor => actor.disconnectObject(this));
        this._touched.clear();
        if (this._eventId)
            this._dock.dash.disconnect(this._eventId);
        this._eventId = 0;
        this._dock.dash.disconnectObject(this);
        this._dock.box.disconnectObject(this);
        this._settings.disconnectObject(this);
    }
}
