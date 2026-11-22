// SPDX-License-Identifier: GPL-3.0-or-later
//
// Trash, drives and network locations shown in the dock. All file system
// access is asynchronous; emptying the trash is delegated to the file
// manager (org.gnome.Nautilus.FileOperations2), which asks for confirmation.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as IconGrid from 'resource:///org/gnome/shell/ui/iconGrid.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as ShellMountOperation from 'resource:///org/gnome/shell/ui/shellMountOperation.js';
import {EventEmitter} from 'resource:///org/gnome/shell/misc/signals.js';
import {gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

const TRASH_URI = 'trash:///';

function launchUri(uri) {
    const context = global.create_app_launch_context(0, -1);
    Gio.AppInfo.launch_default_for_uri_async(uri, context, null, (_o, res) => {
        try {
            Gio.AppInfo.launch_default_for_uri_finish(res);
        } catch (e) {
            Main.notifyError(_('Could not open location'), e.message);
        }
    });
}

function emptyTrash() {
    Gio.DBus.session.call(
        'org.gnome.Nautilus', '/org/gnome/Nautilus/FileOperations2',
        'org.gnome.Nautilus.FileOperations2', 'EmptyTrash',
        new GLib.Variant('(ba{sv})', [true, {}]),
        null, Gio.DBusCallFlags.NONE, -1, null, (conn, res) => {
            try {
                conn.call_finish(res);
            } catch {
                // No file manager service: let the user empty it there.
                launchUri(TRASH_URI);
            }
        });
}

// Keeps the list of locations up to date and emits "changed".
export class LocationsModel extends EventEmitter {
    constructor(settings) {
        super();
        this._settings = settings;
        this._trashFull = false;
        this._cancellable = new Gio.Cancellable();

        this._trash = Gio.File.new_for_uri(TRASH_URI);
        try {
            this._trashMonitor = this._trash.monitor_directory(
                Gio.FileMonitorFlags.NONE, null);
            this._trashMonitor.connect('changed', () => this._queryTrash());
        } catch (e) {
            console.warn(`Deskence Dock: cannot monitor the trash: ${e.message}`);
        }
        this._queryTrash();

        this._volumeMonitor = Gio.VolumeMonitor.get();
        this._volumeMonitor.connectObject(
            'mount-added', () => this.emit('changed'),
            'mount-removed', () => this.emit('changed'),
            'mount-changed', () => this.emit('changed'),
            this);
    }

    _queryTrash() {
        this._trash.query_info_async('trash::item-count',
            Gio.FileQueryInfoFlags.NONE, GLib.PRIORITY_DEFAULT,
            this._cancellable, (file, res) => {
                try {
                    const info = file.query_info_finish(res);
                    const full = info.get_attribute_uint32('trash::item-count') > 0;
                    if (full !== this._trashFull) {
                        this._trashFull = full;
                        this.emit('changed');
                    }
                } catch (e) {
                    if (!e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                        console.warn(`Deskence Dock: trash query failed: ${e.message}`);
                }
            });
    }

    static classify(mount) {
        if (mount.is_shadowed())
            return null;
        if (!mount.get_root().is_native())
            return 'network';
        if (mount.can_eject() || mount.can_unmount())
            return 'drive';
        return null;
    }

    getItems() {
        const items = [];
        const showDrives = this._settings.get_boolean('show-mounts');
        const showNetwork = this._settings.get_boolean('show-network-mounts');

        for (const mount of this._volumeMonitor.get_mounts()) {
            const kind = LocationsModel.classify(mount);
            if ((kind === 'drive' && showDrives) || (kind === 'network' && showNetwork)) {
                items.push({
                    id: `mount:${mount.get_root().get_uri()}`,
                    kind,
                    name: mount.get_name(),
                    gicon: mount.get_symbolic_icon() ?? mount.get_icon(),
                    uri: mount.get_default_location().get_uri(),
                    mount,
                });
            }
        }

        if (this._settings.get_boolean('show-trash')) {
            items.push({
                id: 'trash',
                kind: 'trash',
                name: _('Trash'),
                gicon: new Gio.ThemedIcon({
                    name: this._trashFull ? 'user-trash-full' : 'user-trash',
                }),
                uri: TRASH_URI,
                trashFull: this._trashFull,
            });
        }
        return items;
    }

    destroy() {
        this._cancellable.cancel();
        this._trashMonitor?.cancel();
        this._trashMonitor = null;
        this._volumeMonitor.disconnectObject(this);
        this.disconnectAll();
    }
}

export const LocationIcon = GObject.registerClass({
    GTypeName: 'DeskenceDockLocationIcon',
}, class LocationIcon extends St.Button {
    _init(item, dock) {
        super._init({
            style_class: 'overview-tile',
            reactive: true,
            can_focus: true,
            track_hover: true,
            button_mask: (St.ButtonMask.PRIMARY ?? St.ButtonMask.ONE) |
                (St.ButtonMask.SECONDARY ?? St.ButtonMask.THREE),
            accessible_name: item.name,
        });
        this._dock = dock;
        this.icon = new IconGrid.BaseIcon(item.name, {
            setSizeManually: true,
            showLabel: false,
            // Rendered for the magnified size, drawn at the normal one.
            createIcon: size => new St.Icon({
                gicon: this._item.gicon,
                icon_size: this._dock.iconRenderSize(size),
                width: size,
                height: size,
            }),
        });
        this.set_child(this.icon);
        this._menu = null;
        this._menuManager = new PopupMenu.PopupMenuManager(this);
        this.update(item);
        this.connect('popup-menu', () => this.popupMenu());
        this.connect('destroy', () => this._menu?.destroy());
    }

    update(item) {
        this._item = item;
        this.accessible_name = item.name;
        this.icon.label?.set_text(item.name);
        this.icon.setIconSize(this._dock.iconSize);
        // BaseIcon only recreates its icon on size changes.
        this.icon._createIconTexture?.(this._dock.iconSize);
    }

    get item() {
        return this._item;
    }

    updateIconRendering() {
        this.icon.update();
    }

    vfunc_clicked(button) {
        if (button === 3) {
            this.popupMenu();
            return;
        }
        launchUri(this._item.uri);
        Main.overview.hide();
    }

    popupMenu() {
        this._menu?.destroy();
        this._menu = new PopupMenu.PopupMenu(this, 0.5, this._dock.menuSide);
        Main.uiGroup.add_child(this._menu.actor);
        this._menuManager.addMenu(this._menu);

        const item = this._item;
        this._menu.addAction(_('Open'), () => launchUri(item.uri));
        if (item.kind === 'trash') {
            const empty = this._menu.addAction(_('Empty Trash…'), () => emptyTrash());
            empty.setSensitive(item.trashFull);
        } else if (item.mount) {
            this._menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
            if (item.mount.can_eject())
                this._menu.addAction(_('Eject'), () => this._unmount(true));
            else if (item.mount.can_unmount())
                this._menu.addAction(_('Unmount'), () => this._unmount(false));
        }

        this._menu.connect('open-state-changed', (_m, open) => {
            this._dock.setMenuOpen(this, open);
            if (open)
                this.add_style_pseudo_class('active');
            else
                this.remove_style_pseudo_class('active');
        });
        this._menu.open();
        this._menu.actor.navigate_focus(null, St.DirectionType.TAB_FORWARD, false);
    }

    _unmount(eject) {
        const mount = this._item.mount;
        const operation = new ShellMountOperation.ShellMountOperation(mount);
        const finish = (_m, res) => {
            try {
                if (eject)
                    mount.eject_with_operation_finish(res);
                else
                    mount.unmount_with_operation_finish(res);
            } catch (e) {
                if (!e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.FAILED_HANDLED)) {
                    Main.notifyError(
                        eject ? _('Could not eject the drive') : _('Could not unmount the drive'),
                        e.message);
                }
            }
            operation.close();
        };
        if (eject) {
            mount.eject_with_operation(Gio.MountUnmountFlags.NONE,
                operation.mountOp, null, finish);
        } else {
            mount.unmount_with_operation(Gio.MountUnmountFlags.NONE,
                operation.mountOp, null, finish);
        }
    }
});
