// SPDX-License-Identifier: GPL-3.0-or-later
//
// Keeps the applications view in alphabetical order while sort-mode is
// "alphabetical".
//
// GNOME orders the main view by org.gnome.shell app-picker-layout (pages
// of IDs with positions) and moves icons when it changes; icons without a
// position are never moved (newly installed ones go to the end of the
// second page). The view is therefore kept in order by writing the whole
// layout sorted by display name, split into pages of the grid's size,
// whenever applications or folders are added, removed or renamed. Inside a
// folder, the order is the folder's "apps" list; applications the folder
// holds through its categories follow it. Each list is written sorted, with
// those members included, so the whole folder is in order.
//
// Nothing is written while the order is already right, so opening the view
// never rebuilds it. GNOME saves the layout after every drag in the view
// (even when an icon is dragged to the dock); it is then already sorted or
// corrected once. Rearranging by dragging is turned off on the
// view while sorting (no room is made, a drop in the main view is refused
// with a notification); dragging into or out of folders and to the dock
// still works. Folders are never split and nothing else is changed.
//
// The custom arrangement from before is saved and restored by the
// settings application (src/deskence/appgrid.py) when the mode changes;
// turning the extension off (also while the screen is locked) changes
// nothing in GNOME's settings.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

import {compareNames, pageLayout, sameLayout, sameList, sortIds} from './order.js';

const FOLDERS_SCHEMA = 'org.gnome.desktop.app-folders';
const FOLDER_SCHEMA = 'org.gnome.desktop.app-folders.folder';
// Changes come in bursts (a drop writes several keys); one pass after them.
const SETTLE_DELAY = 250;

export class AppGridSorter {
    constructor(settings) {
        this._settings = settings;
        this._folders = new Gio.Settings({schema_id: FOLDERS_SCHEMA});
        this._folderSettings = new Map();
        this._appSystem = Shell.AppSystem.get_default();
        this._applyId = 0;
        this._patched = null;
        this._notified = false;

        settings.connectObject('changed::sort-mode', () => this._sync(), this);
        global.settings.connectObject('changed::app-picker-layout', () => this._queue(), this);
        this._folders.connectObject('changed::folder-children', () => {
            this._trackFolders();
            this._queue();
        }, this);
        this._appSystem.connectObject('installed-changed', () => this._queue(), this);
        this._trackFolders();
        this._sync();
    }

    get _alphabetical() {
        return this._settings.get_string('sort-mode') === 'alphabetical';
    }

    _sync() {
        if (this._alphabetical) {
            this._patchView();
            this._queue();
        } else {
            this._cancel();
            this._unpatchView();
        }
    }

    _trackFolders() {
        const ids = new Set(this._folders.get_strv('folder-children'));
        for (const [id, settings] of this._folderSettings) {
            if (!ids.has(id)) {
                settings.disconnectObject(this);
                this._folderSettings.delete(id);
            }
        }
        for (const id of ids) {
            if (this._folderSettings.has(id))
                continue;
            const settings = new Gio.Settings({
                schema_id: FOLDER_SCHEMA,
                path: `${this._folders.path}folders/${id}/`,
            });
            settings.connectObject('changed::apps', () => this._queue(), this);
            this._folderSettings.set(id, settings);
        }
    }

    _queue(delay = SETTLE_DELAY) {
        if (!this._alphabetical || this._applyId)
            return;
        this._applyId = GLib.timeout_add(GLib.PRIORITY_LOW, delay, () => {
            this._applyId = 0;
            this._apply();
            return GLib.SOURCE_REMOVE;
        });
    }

    _cancel() {
        if (this._applyId)
            GLib.source_remove(this._applyId);
        this._applyId = 0;
    }

    // Writes only what differs from the sorted state, so the passes end.
    _apply() {
        if (!this._alphabetical)
            return;
        const view = this._view();
        // Not in the middle of a drag: GNOME saves the layout when it ends.
        if (view?._dragMonitor || view?._placeholder) {
            this._queue();
            return;
        }
        const name = id => this._appSystem.lookup_app(id)?.get_name() ?? null;
        const members = this._folderMembers();
        for (const [id, settings] of this._folderSettings) {
            const apps = settings.get_strv('apps');
            const sorted = sortIds([...apps, ...(members.get(id) ?? [])], name);
            if (!sameList(apps, sorted))
                settings.set_strv('apps', sorted);
        }
        if (!view || !global.settings.is_writable('app-picker-layout'))
            return;
        if (this._refreshRenamed(view))
            return;
        const ids = view.getAllItems()
            .map(item => ({id: item.id, name: item.name ?? ''}))
            .sort(compareNames)
            .map(item => item.id);
        const wanted = pageLayout(ids, view._grid?.itemsPerPage ?? ids.length);
        const current = global.settings.get_value('app-picker-layout').recursiveUnpack()
            .map(page => Object.fromEntries(Object.entries(page).map(
                ([id, properties]) => [id, properties.position])));
        if (sameLayout(current, wanted))
            return;
        global.settings.set_value('app-picker-layout', new GLib.Variant('aa{sv}',
            wanted.map(page => Object.fromEntries(Object.entries(page).map(
                ([id, position]) => [id, new GLib.Variant('a{sv}',
                    {position: GLib.Variant.new_int32(position)})])))));
    }

    // GNOME keeps the icon of an application whose name changed (it only
    // compares IDs), so the view would show and sort it under the former
    // name until the next login. Such icons are recreated; the view then
    // reports "view-loaded" and the order follows. Returns whether any was.
    _refreshRenamed(view) {
        const stale = view.getAllItems().filter(item => item.app &&
            this._appSystem.lookup_app(item.id) !== item.app &&
            this._appSystem.lookup_app(item.id) !== null);
        for (const item of stale) {
            view._removeItem(item);
            item.destroy();
        }
        if (stale.length)
            view._redisplay();
        return stale.length > 0;
    }

    // Members of each folder as GNOME shows them (including the ones of
    // its categories), when the view exists.
    _folderMembers() {
        const result = new Map();
        for (const icon of this._view()?._folderIcons ?? []) {
            try {
                result.set(icon.id, icon.getAppIds());
            } catch (e) {
                console.warn(`Deskence: cannot read the folder ${icon.id}: ${e.message}`);
            }
        }
        return result;
    }

    _view() {
        return Main.overview._overview?.controls?._appDisplay ?? null;
    }

    // --- Rearranging by dragging ----------------------------------------

    _patchView() {
        const view = this._view();
        if (!view || this._patched === view)
            return;
        this._unpatchView();
        const sorter = this;
        // GNOME adds installed applications to the view only when it is
        // shown (deferred work); they are put in order right after.
        view.connectObject('view-loaded', () => this._queue(0), this);
        // No room is made for a dragged icon in the main view.
        view._maybeMoveItem = function () {};
        // A drop of an icon of the main view would only reorder it.
        view.acceptDrop = function (source) {
            if (this._orderedItems?.includes(source)) {
                sorter._explain();
                return false;
            }
            return Object.getPrototypeOf(this).acceptDrop.call(this, source);
        };
        this._patched = view;
    }

    _unpatchView() {
        const view = this._patched;
        if (!view)
            return;
        view.disconnectObject(this);
        delete view._maybeMoveItem;
        delete view.acceptDrop;
        this._patched = null;
    }

    _explain() {
        if (this._notified)
            return;
        this._notified = true;
        Main.notify(_('Applications are sorted alphabetically'),
            _('To arrange them yourself, choose “Custom Order” in Deskence.'));
    }

    destroy() {
        this._cancel();
        this._unpatchView();
        this._settings.disconnectObject(this);
        global.settings.disconnectObject(this);
        this._folders.disconnectObject(this);
        this._appSystem.disconnectObject(this);
        for (const settings of this._folderSettings.values())
            settings.disconnectObject(this);
        this._folderSettings.clear();
        this._settings = null;
    }
}
