// SPDX-License-Identifier: GPL-3.0-or-later
//
// StatusNotifierWatcher and host.
//
// Applications register their StatusNotifierItems with the watcher
// (org.kde.StatusNotifierWatcher). If no other program owns that name, we
// provide the watcher ourselves. If another program already does (another
// desktop component, a bridge such as snixembed), we do not take the name
// away: we register as a host with it and show the items it knows about,
// and queue for the name in case it goes away.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {EventEmitter} from 'resource:///org/gnome/shell/misc/signals.js';

import {parseItemService} from './dbusMenuModel.js';

const WATCHER_NAME = 'org.kde.StatusNotifierWatcher';
const WATCHER_PATH = '/StatusNotifierWatcher';

const WATCHER_XML = `
<node>
  <interface name="org.kde.StatusNotifierWatcher">
    <method name="RegisterStatusNotifierItem">
      <arg name="service" type="s" direction="in"/>
    </method>
    <method name="RegisterStatusNotifierHost">
      <arg name="service" type="s" direction="in"/>
    </method>
    <property name="RegisteredStatusNotifierItems" type="as" access="read"/>
    <property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
    <property name="ProtocolVersion" type="i" access="read"/>
    <signal name="StatusNotifierItemRegistered"><arg type="s"/></signal>
    <signal name="StatusNotifierItemUnregistered"><arg type="s"/></signal>
    <signal name="StatusNotifierHostRegistered"/>
    <signal name="StatusNotifierHostUnregistered"/>
  </interface>
</node>`;

// Emits "item-added" (key, busName, objectPath), "item-removed" (key) and
// "mode-changed" ('watcher' | 'host').
export class StatusNotifierWatcher extends EventEmitter {
    constructor() {
        super();
        this._items = new Map(); // key -> {busName, objectPath, watchId}
        this._hosts = new Map(); // bus name -> watch id
        this._mode = null;
        this._bus = Gio.DBus.session;
        this._cancellable = new Gio.Cancellable();

        this._exported = Gio.DBusExportedObject.wrapJSObject(WATCHER_XML, this);
        this._exported.export(this._bus, WATCHER_PATH);

        // Our own host name, used when registering with a foreign watcher.
        this._hostName = `org.kde.StatusNotifierHost-${new Gio.Credentials().get_unix_pid()}-deskence`;
        this._hostOwnerId = Gio.bus_own_name_on_connection(this._bus, this._hostName,
            Gio.BusNameOwnerFlags.NONE, null, null);

        this._ownerId = Gio.bus_own_name_on_connection(this._bus, WATCHER_NAME,
            Gio.BusNameOwnerFlags.NONE,
            () => this._becomeWatcher(),
            () => this._becomeHost());
    }

    get mode() {
        return this._mode;
    }

    // --- org.kde.StatusNotifierWatcher (when we own the name) -----------

    RegisterStatusNotifierItemAsync([service], invocation) {
        const sender = invocation.get_sender();
        const parsed = parseItemService(service, sender);
        if (!parsed) {
            invocation.return_dbus_error('org.freedesktop.DBus.Error.InvalidArgs',
                'Invalid StatusNotifierItem service');
            return;
        }
        this._addItem(parsed.busName, parsed.objectPath);
        invocation.return_value(null);
    }

    RegisterStatusNotifierHostAsync([service], invocation) {
        const name = service.startsWith('/') ? invocation.get_sender() : service;
        if (!this._hosts.has(name)) {
            const watchId = Gio.bus_watch_name_on_connection(this._bus, name,
                Gio.BusNameWatcherFlags.NONE, null, () => {
                    Gio.bus_unwatch_name(this._hosts.get(name));
                    this._hosts.delete(name);
                    if (this._hosts.size === 0)
                        this._emitSignal('StatusNotifierHostUnregistered', null);
                });
            this._hosts.set(name, watchId);
            this._emitSignal('StatusNotifierHostRegistered', null);
        }
        invocation.return_value(null);
    }

    get RegisteredStatusNotifierItems() {
        return [...this._items.keys()];
    }

    get IsStatusNotifierHostRegistered() {
        return true;
    }

    get ProtocolVersion() {
        return 0;
    }

    _emitSignal(name, params) {
        if (this._mode === 'watcher')
            this._exported.emit_signal(name, params);
    }

    // --- Items ----------------------------------------------------------

    _addItem(busName, objectPath) {
        const key = `${busName}${objectPath}`;
        if (this._items.has(key))
            return;
        // Forget the item as soon as its owner leaves the bus.
        const watchId = Gio.bus_watch_name_on_connection(this._bus, busName,
            Gio.BusNameWatcherFlags.NONE, null, () => this._removeItem(key));
        this._items.set(key, {busName, objectPath, watchId});
        this.emit('item-added', key, busName, objectPath);
        this._emitSignal('StatusNotifierItemRegistered', new GLib.Variant('(s)', [key]));
        if (this._mode === 'watcher') {
            this._exported.emit_property_changed('RegisteredStatusNotifierItems',
                new GLib.Variant('as', this.RegisteredStatusNotifierItems));
        }
    }

    _removeItem(key) {
        const item = this._items.get(key);
        if (!item)
            return;
        Gio.bus_unwatch_name(item.watchId);
        this._items.delete(key);
        this.emit('item-removed', key);
        this._emitSignal('StatusNotifierItemUnregistered', new GLib.Variant('(s)', [key]));
        if (this._mode === 'watcher') {
            this._exported.emit_property_changed('RegisteredStatusNotifierItems',
                new GLib.Variant('as', this.RegisteredStatusNotifierItems));
        }
    }

    _clearItems() {
        for (const key of [...this._items.keys()])
            this._removeItem(key);
    }

    // --- Mode switching -------------------------------------------------

    _becomeWatcher() {
        this._leaveHostMode();
        this._mode = 'watcher';
        this.emit('mode-changed', this._mode);
        // Items registered with the previous watcher re-register when they
        // see the name owner change, as the specification requires.
        this._emitSignal('StatusNotifierHostRegistered', null);
    }

    _becomeHost() {
        if (this._mode === 'host')
            return;
        this._clearItems();
        this._mode = 'host';
        this.emit('mode-changed', this._mode);

        // Follow the foreign watcher's items.
        this._signalIds = [
            this._bus.signal_subscribe(WATCHER_NAME, WATCHER_NAME,
                'StatusNotifierItemRegistered', WATCHER_PATH, null,
                Gio.DBusSignalFlags.NONE, (_c, sender, _p, _i, _s, params) => {
                    const [service] = params.deepUnpack();
                    const parsed = parseItemService(service, sender);
                    if (parsed)
                        this._addItem(parsed.busName, parsed.objectPath);
                }),
            this._bus.signal_subscribe(WATCHER_NAME, WATCHER_NAME,
                'StatusNotifierItemUnregistered', WATCHER_PATH, null,
                Gio.DBusSignalFlags.NONE, (_c, sender, _p, _i, _s, params) => {
                    const [service] = params.deepUnpack();
                    const parsed = parseItemService(service, sender);
                    if (parsed)
                        this._removeItem(`${parsed.busName}${parsed.objectPath}`);
                }),
        ];

        this._bus.call(WATCHER_NAME, WATCHER_PATH, WATCHER_NAME, 'RegisterStatusNotifierHost',
            new GLib.Variant('(s)', [this._hostName]), null, Gio.DBusCallFlags.NONE, -1,
            this._cancellable, (bus, res) => {
                try {
                    bus.call_finish(res);
                } catch (e) {
                    if (!e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                        console.warn(`Deskence Tray: host registration failed: ${e.message}`);
                }
            });

        this._bus.call(WATCHER_NAME, WATCHER_PATH, 'org.freedesktop.DBus.Properties', 'Get',
            new GLib.Variant('(ss)', [WATCHER_NAME, 'RegisteredStatusNotifierItems']),
            null, Gio.DBusCallFlags.NONE, -1, this._cancellable, (bus, res) => {
                let services = [];
                let owner = null;
                try {
                    const [value] = bus.call_finish(res).deepUnpack();
                    services = value.deepUnpack();
                } catch (e) {
                    if (e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                        return;
                }
                for (const service of services) {
                    const parsed = parseItemService(service, owner);
                    if (parsed?.busName)
                        this._addItem(parsed.busName, parsed.objectPath);
                }
            });
    }

    _leaveHostMode() {
        for (const id of this._signalIds ?? [])
            this._bus.signal_unsubscribe(id);
        this._signalIds = [];
        this._clearItems();
    }

    destroy() {
        this._cancellable.cancel();
        this._leaveHostMode();
        for (const watchId of this._hosts.values())
            Gio.bus_unwatch_name(watchId);
        this._hosts.clear();
        Gio.bus_unown_name(this._ownerId);
        Gio.bus_unown_name(this._hostOwnerId);
        this._exported.unexport();
        this._mode = null;
        this.disconnectAll();
    }
}
