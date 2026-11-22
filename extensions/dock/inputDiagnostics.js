// SPDX-License-Identifier: GPL-3.0-or-later
//
// Optional diagnostics of who receives pointer input, for reports of a
// desktop and windows that stop taking clicks. Off unless GNOME Shell runs
// with DESKENCE_DEBUG=input (for example in
// ~/.config/environment.d/deskence-debug.conf, then log in again).
//
// A few snapshots per session, never on pointer motion: when the dock is
// enabled, when the startup animation completes and 3 s later, the first
// times the overview is shown and hidden again (opening and closing the
// overview was seen to bring input back), and whenever, with the overview
// closed, a click at one of the probed points would reach a Shell actor
// instead of a window or the background, and when that ends. The probe
// runs every 2 s, only reads, and logs at most MAX_PROBE_SNAPSHOTS times. Each one lists the actor a click would reach at
// a few points of every monitor, the Shell's grabs and modal count, the
// overview's and the layout's state, and the windows' types, layers and
// geometry. No window titles, file names or text are logged.

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Meta from 'gi://Meta';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const ENABLED = (GLib.getenv('DESKENCE_DEBUG') ?? '').split(/[\s,]+/).includes('input');
const LATER_DELAY = 3000;
const MAX_OVERVIEW_SNAPSHOTS = 2;
const PROBE_INTERVAL = 2000;
const MAX_PROBE_SNAPSHOTS = 20;
const DESKTOP_TITLE_TAG = '@deskence-desktop:';

function describeActor(actor) {
    const parts = [];
    for (let a = actor; a && parts.length < 6; a = a.get_parent()) {
        let text = GObject.type_name_from_instance(a);
        if (a.name)
            text += `#${a.name}`;
        const style = a.style_class?.split(' ')[0];
        if (style)
            text += `.${style}`;
        if (a instanceof Meta.WindowActor) {
            const window = a.get_meta_window();
            text += `(${window.get_wm_class() ?? '?'} type ${window.get_window_type()})`;
        }
        text += `[${Math.round(a.width)}x${Math.round(a.height)}]`;
        parts.push(text);
    }
    return parts.join(' < ');
}

function probePoints() {
    const points = [];
    for (const monitor of Main.layoutManager.monitors) {
        for (const [fx, fy] of [[0.5, 0.5], [0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]])
            points.push([Math.round(monitor.x + monitor.width * fx), Math.round(monitor.y + monitor.height * fy)]);
    }
    return points;
}

function pick([x, y]) {
    return global.stage.get_actor_at_pos(Clutter.PickMode.REACTIVE, x, y);
}

// Probed points where a click would reach neither a window nor the
// background: the description of what is there, or an empty list.
export function blockedPoints() {
    if (Main.overview.visible)
        return [];
    const blocked = [];
    for (const point of probePoints()) {
        const actor = pick(point);
        // The stage itself: nothing there takes the click (no window yet).
        if (!actor || actor === global.stage || global.window_group.contains(actor) ||
            Main.layoutManager._backgroundGroup?.contains(actor))
            continue;
        blocked.push(`${point.join(',')}: ${describeActor(actor)}`);
    }
    return blocked;
}

function snapshot() {
    const picks = {};
    for (const point of probePoints())
        picks[point.join(',')] = describeActor(pick(point));
    const overview = Main.overview;
    const layout = Main.layoutManager;
    const grab = global.stage.get_grab_actor();
    return {
        picks,
        modal: Main.modalCount,
        actionMode: Main.actionMode,
        grab: grab ? describeActor(grab) : null,
        overview: {
            shown: overview._shown, visible: overview._visible,
            animating: overview._animationInProgress, state: overview._shownState,
            cover: overview._coverPane?.visible ?? null,
        },
        layout: {
            startingUp: layout._startingUp, inOverview: layout._inOverview,
            overviewGroup: layout.overviewGroup.visible, startupCover: Boolean(layout._coverPane),
            uiGroup: [layout.uiGroup.scale_x, layout.uiGroup.opacity],
            windowGroup: global.window_group.visible,
            hasOverview: Main.sessionMode.hasOverview, mode: Main.sessionMode.currentMode,
            fullscreen: layout.monitors.map(m => m.inFullscreen),
        },
        windows: global.get_window_actors().map(a => {
            const w = a.get_meta_window();
            const r = w.get_frame_rect();
            return {
                class: w.get_wm_class(), type: w.get_window_type(), layer: w.get_layer?.(),
                rect: [r.x, r.y, r.width, r.height], above: w.is_above(), minimized: w.minimized,
                actorVisible: a.visible, deskenceDesktop: (w.get_title() ?? '').includes(DESKTOP_TITLE_TAG),
            };
        }),
    };
}

export class InputDiagnostics {
    constructor() {
        this._laterId = 0;
        this._probeId = 0;
        this._shows = 0;
        this._hides = 0;
        this._probes = 0;
        this._blocked = '';
        if (!ENABLED)
            return;
        this._probeId = GLib.timeout_add(GLib.PRIORITY_LOW, PROBE_INTERVAL, () => {
            this._probe();
            return GLib.SOURCE_CONTINUE;
        });
        this._log('dock enabled');
        if (Main.layoutManager._startingUp) {
            Main.layoutManager.connectObject('startup-complete', () => {
                this._log('startup complete');
                this._laterId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, LATER_DELAY, () => {
                    this._laterId = 0;
                    this._log('3 s after startup');
                    return GLib.SOURCE_REMOVE;
                });
            }, this);
        }
        Main.overview.connectObject(
            'showing', () => {
                if (this._shows++ < MAX_OVERVIEW_SNAPSHOTS)
                    this._log('overview showing');
            },
            'hidden', () => {
                if (this._hides++ < MAX_OVERVIEW_SNAPSHOTS)
                    this._log('overview hidden');
            }, this);
    }

    _probe() {
        let blocked;
        try {
            blocked = blockedPoints().join(' | ');
        } catch (e) {
            blocked = `probe failed: ${e.message}`;
        }
        if (blocked === this._blocked || this._probes >= MAX_PROBE_SNAPSHOTS)
            return;
        this._blocked = blocked;
        this._probes++;
        this._log(blocked ? `clicks over windows reach the Shell: ${blocked}`
            : 'clicks over windows reach windows again');
    }

    _log(reason) {
        try {
            console.log(`Deskence input (${reason}): ${JSON.stringify(snapshot())}`);
        } catch (e) {
            console.log(`Deskence input (${reason}): snapshot failed: ${e.message}`);
        }
    }

    destroy() {
        for (const name of ['_laterId', '_probeId']) {
            if (this[name])
                GLib.source_remove(this[name]);
            this[name] = 0;
        }
        Main.layoutManager.disconnectObject(this);
        Main.overview.disconnectObject(this);
    }
}
