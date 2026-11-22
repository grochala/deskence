// SPDX-License-Identifier: GPL-3.0-or-later
//
// Application icons in the top bar (StatusNotifierItem). Legacy XEmbed tray
// icons are not supported.

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {StatusNotifierWatcher} from './watcher.js';
import {StatusNotifierItem, TrayButton} from './trayItem.js';

class Tray {
    constructor(settings) {
        this._settings = settings;
        this._entries = new Map();
        this._counter = 0;

        this._watcher = new StatusNotifierWatcher();
        this._watcher.connectObject(
            'item-added', (_w, key, busName, objectPath) => this._addItem(key, busName, objectPath),
            'item-removed', (_w, key) => this._removeItem(key),
            this);
        this._settings.connectObject('changed::show-passive', () => this._syncAll(), this);
        // The extension stays enabled on the lock screen so applications keep
        // their registration; the icons are hidden there.
        Main.sessionMode.connectObject('updated', () => this._syncAll(), this);
    }

    destroy() {
        Main.sessionMode.disconnectObject(this);
        this._settings.disconnectObject(this);
        this._watcher.disconnectObject(this);
        for (const key of [...this._entries.keys()])
            this._removeItem(key);
        this._watcher.destroy();
        this._watcher = null;
        this._settings = null;
    }

    _addItem(key, busName, objectPath) {
        if (this._entries.has(key))
            return;
        const item = new StatusNotifierItem(busName, objectPath);
        const button = new TrayButton(item);
        const role = `deskence-tray-${++this._counter}`;
        Main.panel.addToStatusArea(role, button, 0, 'right');
        this._entries.set(key, {item, button});
        item.connectObject('changed', () => this._sync(key), this);
        this._sync(key);
    }

    _removeItem(key) {
        const entry = this._entries.get(key);
        if (!entry)
            return;
        this._entries.delete(key);
        entry.item.disconnectObject(this);
        entry.button.destroy();
        entry.item.destroy();
    }

    _sync(key) {
        const entry = this._entries.get(key);
        if (!entry)
            return;
        const {item, button} = entry;
        // Wait for the first properties before showing anything.
        const known = item.props.Id !== undefined || item.props.IconName !== undefined ||
            item.props.IconPixmap !== undefined;
        const passive = item.status === 'Passive' && !this._settings.get_boolean('show-passive');
        button.container.visible = known && !passive && !Main.sessionMode.isLocked;
    }

    _syncAll() {
        for (const key of this._entries.keys())
            this._sync(key);
    }
}

// GNOME Shell 48 may create two objects of the same extension and enable
// both when several extensions are enabled in quick succession (fixed in
// GNOME 49). The running state therefore lives in the module, which both
// objects share, so the feature never starts twice and one disable() call
// cleans up everything.
let tray = null;

export default class DeskenceTrayExtension extends Extension {
    enable() {
        tray ??= new Tray(this.getSettings('io.github.deskence.Deskence.Tray'));
    }

    disable() {
        tray?.destroy();
        tray = null;
    }
}
