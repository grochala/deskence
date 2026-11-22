// SPDX-License-Identifier: GPL-3.0-or-later
//
// Optional diagnostics of who receives pointer input, for reports of a
// desktop and windows that stop taking clicks. Off unless GNOME Shell runs
// with DESKENCE_DEBUG=input (for example in
// ~/.config/environment.d/deskence-debug.conf, then log in again).
//
// A few snapshots per session, never on pointer motion: when the dock is
// enabled, when the startup animation completes and 3 s later, and the
// first times the overview is shown and hidden again (opening and closing
// the overview was seen to bring input back, so the two snapshots around
// it show what it reset). Each one lists the actor a click would reach at
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

function snapshot() {
    const picks = {};
    for (const monitor of Main.layoutManager.monitors) {
        for (const [fx, fy] of [[0.5, 0.5], [0.25, 0.25], [0.75, 0.25]]) {
            const x = Math.round(monitor.x + monitor.width * fx);
            const y = Math.round(monitor.y + monitor.height * fy);
            picks[`${x},${y}`] = describeActor(
                global.stage.get_actor_at_pos(Clutter.PickMode.REACTIVE, x, y));
        }
    }
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
        this._shows = 0;
        this._hides = 0;
        if (!ENABLED)
            return;
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

    _log(reason) {
        try {
            console.log(`Deskence input (${reason}): ${JSON.stringify(snapshot())}`);
        } catch (e) {
            console.log(`Deskence input (${reason}): snapshot failed: ${e.message}`);
        }
    }

    destroy() {
        if (this._laterId)
            GLib.source_remove(this._laterId);
        this._laterId = 0;
        Main.layoutManager.disconnectObject(this);
        Main.overview.disconnectObject(this);
    }
}
