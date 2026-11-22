// SPDX-License-Identifier: GPL-3.0-or-later
//
// Listening for LauncherEntry updates on the session bus (see
// launcherLogic.js for the protocol and how senders are merged).
//
// Only a signal subscription: no D-Bus name is owned, so nothing is taken
// from another dock or component listening for the same signals. Each
// sender's connection is watched; when it closes (the application quit or
// restarted, getting a new connection) everything it reported is
// forgotten. Updates are only received while listening is on (one of the
// dock settings show-app-counts and show-app-progress); turning it off or
// disabling the dock drops the subscription, the watches and all values.
// Applications do not repeat their state, so a counter set before the
// dock started listening shows up with the next update.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';

import {EventEmitter} from 'resource:///org/gnome/shell/misc/signals.js';

import {LauncherState, appIdFromUri, parseUpdate} from './launcherLogic.js';

const INTERFACE = 'com.canonical.Unity.LauncherEntry';

export class LauncherEntries extends EventEmitter {
    constructor() {
        super();
        this._state = new LauncherState();
        this._subscription = 0;
        this._watches = new Map();
        this._appSystem = Shell.AppSystem.get_default();
    }

    get listening() {
        return this._subscription !== 0;
    }

    setListening(on) {
        if (on && !this._subscription) {
            this._subscription = Gio.DBus.session.signal_subscribe(null, INTERFACE, 'Update',
                null, null, Gio.DBusSignalFlags.NONE,
                (_c, sender, _path, _iface, _signal, params) => this._onUpdate(sender, params));
        } else if (!on && this._subscription) {
            Gio.DBus.session.signal_unsubscribe(this._subscription);
            this._subscription = 0;
            this._unwatchAll();
            for (const appId of this._state.clear())
                this.emit('changed', appId);
        }
    }

    // {count, progress} for a desktop id, null where nothing is shown.
    get(appId) {
        return this._state.get(appId);
    }

    // The id of the installed application, also when the sender wrote it
    // differently ("Firefox.desktop" for "firefox.desktop").
    _resolve(appId) {
        if (!appId)
            return null;
        const app = this._appSystem.lookup_app(appId) ??
            this._appSystem.lookup_heuristic_basename(appId);
        return app ? app.get_id() : appId;
    }

    _onUpdate(sender, params) {
        if (!sender || params?.get_type_string() !== '(sa{sv})')
            return;
        let uri, properties;
        try {
            [uri, properties] = params.recursiveUnpack();
        } catch {
            return;
        }
        const appId = this._resolve(appIdFromUri(uri));
        if (!appId)
            return;
        this._watch(sender);
        if (this._state.update(sender, appId, parseUpdate(properties), GLib.get_monotonic_time()))
            this.emit('changed', appId);
    }

    _watch(sender) {
        if (this._watches.has(sender))
            return;
        // A unique name that is already gone calls vanished at once.
        const id = Gio.bus_watch_name_on_connection(Gio.DBus.session, sender,
            Gio.BusNameWatcherFlags.NONE, null, () => this._vanished(sender));
        this._watches.set(sender, id);
    }

    _vanished(sender) {
        const id = this._watches.get(sender);
        if (id === undefined)
            return;
        Gio.bus_unwatch_name(id);
        this._watches.delete(sender);
        for (const appId of this._state.removeSender(sender))
            this.emit('changed', appId);
    }

    _unwatchAll() {
        for (const id of this._watches.values())
            Gio.bus_unwatch_name(id);
        this._watches.clear();
    }

    destroy() {
        this.setListening(false);
        this.disconnectAll();
    }
}
