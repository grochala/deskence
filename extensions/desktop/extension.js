// SPDX-License-Identifier: GPL-3.0-or-later
//
// Desktop icons: GNOME Shell side.
//
// The icons are drawn by a separate GTK 4 process (deskence-desktop-icons)
// so file operations never run inside GNOME Shell. The process is started
// through Meta.WaylandClient, which lets the shell recognise its windows on
// Wayland. Windows titled with DESKTOP_TITLE_TAG are turned into desktop
// windows: below all other windows, on every workspace, hidden from the
// window list and the overview, and covering their whole monitor.
//
// Covering the whole monitor matters: every click on the empty desktop has
// to reach our window, also beside a dock shorter than the screen edge,
// otherwise the shell's background menu opens there instead of ours. The top
// bar and the dock are shell chrome above all windows, so they stay
// clickable. Where icons may go (the monitor minus the top bar, and minus
// the dock's own rectangle) is sent to the process through a pipe on its
// standard input, see
// desktop-icons/deskence_desktop/shellareas.py.
//
// The context menus of the desktop are drawn here, at the clicked point
// (menu.js): the process writes them on its standard output, and gets the
// chosen item back on its standard input. Other lines it writes there are
// passed on to the log.
//
// Other windows of the process (dialogs) are left alone.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {DOCK_EDGES, DOCK_HOLDER_CLASS, desktopGeometry, menuArea} from './areas.js';
import {DesktopMenu} from './menu.js';

// Set by the helper on desktop windows (desktop-icons/.../window.py). From
// the former project name; helper and extension of neighbouring versions
// run together until the next login after an update, so it stays.
const DESKTOP_TITLE_TAG = '@deskence-desktop:';
const MAX_RESTARTS = 5;
const RESTART_WINDOW_US = 60 * GLib.USEC_PER_SEC;
const RESTART_DELAY_MS = 1000;
const AREAS_ENV = 'DESKENCE_DESKTOP_AREAS';

// Mutter 49 replaced the per-client window helpers by MetaWindow methods
// and the two-step spawning by new_subprocess(). Support both.
function spawnClient(argv) {
    const launcher = new Gio.SubprocessLauncher({
        flags: Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE,
    });
    launcher.setenv(AREAS_ENV, '1', true);
    if (Meta.WaylandClient.new_subprocess) {
        const client = Meta.WaylandClient.new_subprocess(global.context, launcher, argv);
        return {client, subprocess: client.get_subprocess()};
    }
    const client = Meta.WaylandClient.new(global.context, launcher);
    const subprocess = client.spawnv(global.display, argv);
    return {client, subprocess};
}

function makeDesktopWindow(client, window) {
    if (window.set_type) {
        window.set_type(Meta.WindowType.DESKTOP);
        window.hide_from_window_list();
    } else {
        client.make_desktop(window);
        client.hide_from_window_list(window);
    }
    window.stick();
    window.lower();
}

class DesktopIcons {
    constructor(metadata) {
        this.metadata = metadata;
        this._windows = new Map();
        this._shown = new WeakSet();
        this._restarts = [];
        this._restartId = 0;
        this._client = null;
        this._subprocess = null;
        this._cancellable = new Gio.Cancellable();
        this._areasId = 0;
        this._lastAreas = null;
        this._writing = false;
        this._outgoing = [];
        this._menu = null;
        this._docks = new Set();

        global.display.connectObject(
            'window-created', (_d, window) => this._onWindowCreated(window),
            'workareas-changed', () => this._queueAreas(),
            this);
        Main.layoutManager.connectObject('monitors-changed', () => {
            this._placeAll();
            this._queueAreas();
        }, this);
        Main.layoutManager.uiGroup.connectObject(
            'child-added', (_g, actor) => this._trackDock(actor),
            'child-removed', (_g, actor) => this._untrackDock(actor),
            this);
        for (const actor of Main.layoutManager.uiGroup.get_children())
            this._trackDock(actor);

        this._start();
    }

    destroy() {
        global.display.disconnectObject(this);
        Main.layoutManager.disconnectObject(this);
        Main.layoutManager.uiGroup.disconnectObject(this);
        for (const dock of this._docks)
            dock.disconnectObject(this);
        this._docks.clear();
        if (this._restartId)
            GLib.source_remove(this._restartId);
        this._restartId = 0;
        if (this._areasId)
            GLib.source_remove(this._areasId);
        this._areasId = 0;

        for (const window of this._windows.keys())
            window.disconnectObject(this);
        this._windows.clear();

        this._menu?.destroy();
        this._menu = null;
        this._cancellable.cancel();
        this._subprocess?.send_signal(15);
        this._subprocess = null;
        this._client = null;
        this._windows = null;
    }

    _helperPath() {
        // Installed next to the extension by the package: the extension
        // directory is <datadir>/gnome-shell/extensions/<uuid>, the helper
        // lives in <libexecdir>. The path is written to metadata at build
        // time; fall back to the usual location.
        return this.metadata['helper-path'] ?? '/usr/libexec/deskence-desktop-icons';
    }

    _start() {
        const argv = [this._helperPath()];
        let spawned;
        try {
            spawned = spawnClient(argv);
        } catch (e) {
            console.error(`Deskence: cannot start ${argv[0]}: ${e.message}`);
            return;
        }
        this._client = spawned.client;
        this._subprocess = spawned.subprocess;
        this._lastAreas = null;
        this._writing = false;
        this._outgoing = [];
        const subprocess = this._subprocess;
        this._readOutput(subprocess);
        subprocess.wait_async(this._cancellable, (_p, res) => {
            try {
                subprocess.wait_finish(res);
            } catch {
                return; // cancelled: the extension is being disabled
            }
            if (subprocess !== this._subprocess)
                return;
            this._onHelperExited(subprocess);
        });
    }

    _onHelperExited(subprocess) {
        const status = subprocess.get_if_exited() ? subprocess.get_exit_status() : -1;
        this._menu?.destroy();
        this._menu = null;
        this._subprocess = null;
        this._client = null;
        for (const window of this._windows.keys())
            window.disconnectObject(this);
        this._windows.clear();

        // Exit status 0 means the helper decided to quit; anything else is
        // a crash. Restart a crashing helper, but give up when it keeps
        // crashing so the shell is not flooded.
        if (status === 0)
            return;
        const now = GLib.get_monotonic_time();
        this._restarts = this._restarts.filter(t => now - t < RESTART_WINDOW_US);
        if (this._restarts.length >= MAX_RESTARTS) {
            console.error('Deskence: desktop icons keep crashing, not restarting');
            return;
        }
        this._restarts.push(now);
        this._restartId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, RESTART_DELAY_MS, () => {
            this._restartId = 0;
            this._start();
            return GLib.SOURCE_REMOVE;
        });
    }

    _onWindowCreated(window) {
        if (!this._client || !this._client.owns_window(window))
            return;
        // GTK may set the title after the window was created.
        window.connectObject(
            'notify::title', () => this._manage(window),
            'shown', () => {
                this._shown.add(window);
                this._place(window);
            },
            'unmanaged', () => {
                window.disconnectObject(this);
                this._windows.delete(window);
            }, this);
        this._manage(window);
    }

    _manage(window) {
        const title = window.get_title() ?? '';
        const index = title.indexOf(DESKTOP_TITLE_TAG);
        if (index < 0) {
            this._windows.delete(window);
            return;
        }
        const connector = title.slice(index + DESKTOP_TITLE_TAG.length);
        const known = this._windows.has(window);
        this._windows.set(window, connector);
        if (!known)
            makeDesktopWindow(this._client, window);
        this._place(window);
        this._queueAreas();
    }

    _monitorIndex(connector) {
        const monitorManager = global.backend.get_monitor_manager();
        const index = monitorManager.get_monitor_for_connector(connector);
        if (index < 0 || index >= Main.layoutManager.monitors.length)
            return Main.layoutManager.primaryIndex;
        return index;
    }

    _place(window) {
        const connector = this._windows.get(window);
        // Mutter refuses to move windows before they are shown.
        if (connector === undefined || !this._shown.has(window))
            return;
        const index = this._monitorIndex(connector);
        const monitor = Main.layoutManager.monitors[index];
        if (!monitor)
            return;
        if (window.get_monitor() !== index)
            window.move_to_monitor(index);
        window.move_resize_frame(false, monitor.x, monitor.y, monitor.width, monitor.height);
    }

    // --- Available areas --------------------------------------------------

    _trackDock(actor) {
        if (!actor.has_style_class_name?.(DOCK_HOLDER_CLASS) || this._docks.has(actor))
            return;
        this._docks.add(actor);
        actor.connectObject('notify::allocation', () => this._queueAreas(), this);
        this._queueAreas();
    }

    _untrackDock(actor) {
        if (!this._docks.delete(actor))
            return;
        actor.disconnectObject(this);
        this._queueAreas();
    }

    _dockRects() {
        const rects = [];
        for (const actor of this._docks) {
            const edge = DOCK_EDGES.find(e => actor.has_style_class_name(`deskence-dock-edge-${e}`));
            if (edge)
                rects.push({edge, x: actor.x, y: actor.y, width: actor.width, height: actor.height});
        }
        return rects;
    }

    _queueAreas() {
        if (this._areasId)
            return;
        this._areasId = GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            this._areasId = 0;
            this._sendAreas();
            return GLib.SOURCE_REMOVE;
        });
    }

    _sendAreas() {
        if (!this._subprocess)
            return;
        const docks = this._dockRects();
        const areas = {}, exclusions = {}, workAreas = {};
        const list = r => [r.x, r.y, r.width, r.height];
        for (const connector of new Set(this._windows.values())) {
            const index = this._monitorIndex(connector);
            const monitor = Main.layoutManager.monitors[index];
            if (!monitor)
                continue;
            const geometry = desktopGeometry(monitor,
                Main.layoutManager.getWorkAreaForMonitor(index), docks);
            areas[connector] = list(geometry.area);
            exclusions[connector] = geometry.exclusions.map(list);
            workAreas[connector] = list(geometry.workArea);
        }
        const line = `${JSON.stringify({areas, exclusions, workareas: workAreas})}\n`;
        if (line === this._lastAreas)
            return;
        this._lastAreas = line;
        this._send(line);
    }

    // Lines to the helper's standard input, written one after the other.
    _send(line) {
        this._outgoing.push(line);
        this._flush();
    }

    _flush() {
        const stdin = this._subprocess?.get_stdin_pipe();
        if (!stdin || this._writing || this._outgoing.length === 0)
            return;
        const line = this._outgoing.shift();
        this._writing = true;
        const subprocess = this._subprocess;
        stdin.write_all_async(new TextEncoder().encode(line), GLib.PRIORITY_DEFAULT,
            this._cancellable, (stream, res) => {
                try {
                    stream.write_all_finish(res);
                } catch {
                    return; // cancelled, or the helper exited
                }
                if (subprocess !== this._subprocess)
                    return;
                this._writing = false;
                this._flush();
            });
    }

    // --- Output of the helper: menus --------------------------------------

    _readOutput(subprocess) {
        const stdout = subprocess.get_stdout_pipe();
        if (!stdout)
            return;
        const stream = new Gio.DataInputStream({base_stream: stdout});
        const readLine = () => {
            stream.read_line_async(GLib.PRIORITY_DEFAULT, this._cancellable, (_s, res) => {
                let line;
                try {
                    [line] = stream.read_line_finish_utf8(res);
                } catch {
                    return; // cancelled, or the helper exited
                }
                if (line === null || subprocess !== this._subprocess)
                    return;
                this._onHelperLine(line);
                readLine();
            });
        };
        readLine();
    }

    _onHelperLine(line) {
        let message = null;
        try {
            message = JSON.parse(line);
        } catch {
        }
        if (message?.menu && typeof message.menu === 'object')
            this._showMenu(message.menu);
        else if (line.trim())
            console.log(line);
    }

    _showMenu(spec) {
        this._menu?.destroy();
        this._menu = null;
        const connector = String(spec.connector ?? '');
        if (![...this._windows.values()].includes(connector))
            return;
        const index = this._monitorIndex(connector);
        const monitor = Main.layoutManager.monitors[index];
        if (!monitor || !Number.isFinite(spec.x) || !Number.isFinite(spec.y))
            return;
        const area = menuArea(monitor, Main.layoutManager.getWorkAreaForMonitor(index));
        const menu = new DesktopMenu(spec, monitor, area, (action, target) => {
            if (typeof action === 'string')
                this._send(`${JSON.stringify({activate: {connector, action, target}})}\n`);
        });
        this._menu = menu;
        menu.menu.connect('destroy', () => {
            if (this._menu === menu)
                this._menu = null;
        });
    }

    _placeAll() {
        for (const window of this._windows.keys())
            this._place(window);
    }
}

// GNOME Shell 48 may create two objects of the same extension and enable
// both when several extensions are enabled in quick succession (fixed in
// GNOME 49). The running state therefore lives in the module, which both
// objects share, so the feature never starts twice and one disable() call
// cleans up everything.
let desktopIcons = null;

export default class DeskenceDesktopExtension extends Extension {
    enable() {
        desktopIcons ??= new DesktopIcons(this.metadata);
    }

    disable() {
        desktopIcons?.destroy();
        desktopIcons = null;
    }
}
