// SPDX-License-Identifier: GPL-3.0-or-later
//
// One StatusNotifierItem in the top bar.
//
// Clicks follow the StatusNotifierItem specification: primary click calls
// Activate (or opens the menu for ItemIsMenu items and items that do not
// implement Activate), middle click calls SecondaryActivate, secondary click
// opens the DBusMenu, scrolling calls Scroll. All D-Bus calls are
// asynchronous; a misbehaving application cannot block the shell.

import Clutter from 'gi://Clutter';
import GdkPixbuf from 'gi://GdkPixbuf';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {EventEmitter} from 'resource:///org/gnome/shell/misc/signals.js';

import {choosePixmap, parseNode, visibleChildren} from './dbusMenuModel.js';

const ITEM_IFACE = 'org.kde.StatusNotifierItem';
const MENU_IFACE = 'com.canonical.dbusmenu';
const PROPS_IFACE = 'org.freedesktop.DBus.Properties';
const CALL_TIMEOUT = 5000;

const SIGNAL_PROPERTIES = {
    NewIcon: ['IconName', 'IconPixmap', 'IconThemePath'],
    NewAttentionIcon: ['AttentionIconName', 'AttentionIconPixmap'],
    NewOverlayIcon: ['OverlayIconName', 'OverlayIconPixmap'],
    NewTitle: ['Title'],
    NewToolTip: ['ToolTip'],
    NewStatus: ['Status'],
    NewIconThemePath: ['IconThemePath'],
    NewMenu: ['Menu'],
};

function isCancelled(e) {
    return e instanceof GLib.Error && e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED);
}

// Reads and follows the properties of an item. Emits "changed".
export class StatusNotifierItem extends EventEmitter {
    constructor(busName, objectPath) {
        super();
        this.busName = busName;
        this.objectPath = objectPath;
        this.props = {};
        this._bus = Gio.DBus.session;
        this._cancellable = new Gio.Cancellable();
        this._signalId = this._bus.signal_subscribe(busName, ITEM_IFACE, null, objectPath,
            null, Gio.DBusSignalFlags.NONE, (_c, _s, _p, _i, signal, params) =>
                this._onSignal(signal, params));
        this._refresh(null);
    }

    _onSignal(signal, params) {
        if (signal === 'NewStatus') {
            const [status] = params.deepUnpack();
            this.props.Status = status;
            this.emit('changed');
            return;
        }
        const names = SIGNAL_PROPERTIES[signal];
        if (names)
            this._refresh(names);
    }

    // null refreshes everything with GetAll.
    _refresh(names) {
        const done = values => {
            Object.assign(this.props, values);
            this.emit('changed');
        };
        if (names === null) {
            this._call(PROPS_IFACE, 'GetAll', new GLib.Variant('(s)', [ITEM_IFACE]), result => {
                const [all] = result.deepUnpack();
                const values = {};
                for (const [key, value] of Object.entries(all))
                    values[key] = value.deepUnpack();
                done(values);
            });
            return;
        }
        for (const name of names) {
            this._call(PROPS_IFACE, 'Get', new GLib.Variant('(ss)', [ITEM_IFACE, name]),
                result => {
                    const [value] = result.deepUnpack();
                    done({[name]: value.deepUnpack()});
                }, () => done({[name]: undefined}));
        }
    }

    _call(iface, method, params, onResult, onError) {
        this._bus.call(this.busName, this.objectPath, iface, method, params, null,
            Gio.DBusCallFlags.NO_AUTO_START, CALL_TIMEOUT, this._cancellable, (bus, res) => {
                let result;
                try {
                    result = bus.call_finish(res);
                } catch (e) {
                    if (!isCancelled(e))
                        onError?.(e);
                    return;
                }
                try {
                    onResult?.(result);
                } catch (e) {
                    console.warn(`Deskence Tray: bad data from ${this.busName}: ${e.message}`);
                }
            });
    }

    // Item methods. onError lets callers fall back, e.g. to the menu.
    activate(method, x, y, onError) {
        this._call(ITEM_IFACE, method, new GLib.Variant('(ii)', [x, y]), null, onError);
    }

    scroll(delta, orientation) {
        this._call(ITEM_IFACE, 'Scroll', new GLib.Variant('(is)', [delta, orientation]));
    }

    get title() {
        const title = this.props.Title || this.props.Id || '';
        return typeof title === 'string' ? title : '';
    }

    get status() {
        return this.props.Status ?? 'Active';
    }

    get menuPath() {
        const path = this.props.Menu;
        return typeof path === 'string' && path !== '/' && path.length > 1 ? path : null;
    }

    get itemIsMenu() {
        return this.props.ItemIsMenu === true;
    }

    destroy() {
        this._cancellable.cancel();
        this._bus.signal_unsubscribe(this._signalId);
        this.disconnectAll();
    }
}

// Client for the com.canonical.dbusmenu interface of an item.
class DBusMenuClient extends EventEmitter {
    constructor(busName, objectPath) {
        super();
        this.busName = busName;
        this.objectPath = objectPath;
        this._bus = Gio.DBus.session;
        this._cancellable = new Gio.Cancellable();
        this.root = null;
        this._signalIds = ['LayoutUpdated', 'ItemsPropertiesUpdated'].map(signal =>
            this._bus.signal_subscribe(busName, MENU_IFACE, signal, objectPath, null,
                Gio.DBusSignalFlags.NONE, () => this.update()));
    }

    _call(method, params, onResult) {
        this._bus.call(this.busName, this.objectPath, MENU_IFACE, method, params, null,
            Gio.DBusCallFlags.NO_AUTO_START, CALL_TIMEOUT, this._cancellable, (bus, res) => {
                try {
                    const result = bus.call_finish(res);
                    onResult?.(result);
                } catch (e) {
                    if (!isCancelled(e) && onResult)
                        console.warn(`Deskence Tray: menu ${method} failed: ${e.message}`);
                }
            });
    }

    update() {
        this._call('GetLayout', new GLib.Variant('(iias)', [0, -1, []]), result => {
            const [, layout] = result.deepUnpack();
            this.root = parseNode(layout);
            this.emit('updated');
        });
    }

    aboutToShow() {
        // Applications may update the menu in response.
        this._call('AboutToShow', new GLib.Variant('(i)', [0]), null);
    }

    event(id, eventId) {
        this._call('Event', new GLib.Variant('(isvu)',
            [id, eventId, new GLib.Variant('i', 0), global.get_current_time()]), null);
    }

    destroy() {
        this._cancellable.cancel();
        this._signalIds.forEach(id => this._bus.signal_unsubscribe(id));
        this.disconnectAll();
    }
}

function iconForMenuItem(node) {
    if (node.iconName)
        return new Gio.ThemedIcon({name: node.iconName});
    if (node.iconData)
        return Gio.BytesIcon.new(GLib.Bytes.new(node.iconData));
    return null;
}

export const TrayButton = GObject.registerClass({
    GTypeName: 'DeskenceTrayButton',
}, class TrayButton extends PanelMenu.Button {
    _init(item) {
        // The PanelMenu.Button menu toggles on any click; we need per-button
        // behaviour, so the button gets no built-in menu and owns one.
        super._init(0.5, item.title, true);
        this.add_style_class_name('deskence-tray-item');
        this._item = item;
        this._menuClient = null;
        this._iconTheme = null;

        this._icon = new St.Icon({
            style_class: 'system-status-icon',
            fallback_icon_name: 'application-x-executable-symbolic',
        });
        this.add_child(this._icon);

        this._popup = new PopupMenu.PopupMenu(this, 0.5, St.Side.TOP);
        this._popup.actor.add_style_class_name('panel-menu');
        Main.uiGroup.add_child(this._popup.actor);
        this._popup.actor.hide();
        Main.panel.menuManager.addMenu(this._popup);
        this._popup.connect('open-state-changed', (_m, open) => {
            if (open)
                this.add_style_pseudo_class('active');
            else
                this.remove_style_pseudo_class('active');
            if (!open && this._menuClient)
                this._menuClient.event(0, 'closed');
        });

        this.connect('button-press-event', (_a, event) => this._onButtonPress(event));
        this.connect('scroll-event', (_a, event) => this._onScroll(event));
        this.connect('key-press-event', (_a, event) => this._onKeyPress(event));
        this.connect('destroy', () => this._onDestroy());

        item.connectObject('changed', () => this._sync(), this);
        this._sync();
    }

    _sync() {
        const item = this._item;
        this.accessible_name = item.title;
        this._updateIcon();

        const menuPath = item.menuPath;
        if (menuPath !== this._menuClient?.objectPath) {
            this._menuClient?.destroy();
            this._menuClient = null;
            if (menuPath) {
                this._menuClient = new DBusMenuClient(item.busName, menuPath);
                this._menuClient.connectObject('updated', () => this._rebuildMenu(), this);
                this._menuClient.update();
            }
        }
    }

    _updateIcon() {
        const props = this._item.props;
        const attention = this._item.status === 'NeedsAttention';
        const name = attention && props.AttentionIconName ? props.AttentionIconName : props.IconName;
        const pixmaps = attention && props.AttentionIconPixmap?.length
            ? props.AttentionIconPixmap : props.IconPixmap;

        const gicon = this._iconFromName(name, props.IconThemePath) ??
            this._iconFromPixmaps(pixmaps);
        this._icon.gicon = gicon;
    }

    _iconFromName(name, themePath) {
        if (typeof name !== 'string' || name === '')
            return null;
        if (name.startsWith('/'))
            return Gio.FileIcon.new(Gio.File.new_for_path(name));
        if (typeof themePath === 'string' && themePath !== '') {
            // Applications may ship icons in their own directory.
            if (!this._iconTheme || this._iconThemePath !== themePath) {
                this._iconTheme = new St.IconTheme();
                this._iconTheme.append_search_path(themePath);
                this._iconThemePath = themePath;
            }
            const info = this._iconTheme.lookup_icon(name, 16, 0);
            const filename = info?.get_filename();
            if (filename)
                return Gio.FileIcon.new(Gio.File.new_for_path(filename));
        }
        return new Gio.ThemedIcon({name});
    }

    _iconFromPixmaps(pixmaps) {
        const scale = St.ThemeContext.get_for_stage(global.stage).scale_factor;
        const chosen = choosePixmap(pixmaps, 16 * scale);
        if (!chosen)
            return null;
        try {
            const pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(chosen.rgba),
                GdkPixbuf.Colorspace.RGB, true, 8, chosen.width, chosen.height,
                chosen.width * 4);
            const [, png] = pixbuf.save_to_bufferv('png', [], []);
            return Gio.BytesIcon.new(GLib.Bytes.new(png));
        } catch (e) {
            console.warn(`Deskence Tray: unusable icon from ${this._item.busName}: ${e.message}`);
            return null;
        }
    }

    // --- Menu -----------------------------------------------------------

    _rebuildMenu() {
        this._popup.removeAll();
        const root = this._menuClient?.root;
        if (root)
            this._fillMenu(this._popup, root);
    }

    _fillMenu(menu, node) {
        for (const child of visibleChildren(node)) {
            if (child.type === 'separator') {
                menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
                continue;
            }
            let item;
            if (child.isSubmenu) {
                item = new PopupMenu.PopupSubMenuMenuItem(child.label);
                this._fillMenu(item.menu, child);
                item.menu.connect('open-state-changed', (_m, open) =>
                    this._menuClient?.event(child.id, open ? 'opened' : 'closed'));
            } else {
                const gicon = iconForMenuItem(child);
                item = gicon ? new PopupMenu.PopupImageMenuItem(child.label, gicon)
                    : new PopupMenu.PopupMenuItem(child.label);
                item.connect('activate', () => this._menuClient?.event(child.id, 'clicked'));
                if (child.toggleType === 'checkmark') {
                    item.setOrnament(child.toggleState === 1
                        ? PopupMenu.Ornament.CHECK : PopupMenu.Ornament.NONE);
                } else if (child.toggleType === 'radio') {
                    item.setOrnament(child.toggleState === 1
                        ? PopupMenu.Ornament.DOT : PopupMenu.Ornament.NO_DOT);
                }
            }
            item.setSensitive(child.enabled);
            menu.addMenuItem(item);
        }
    }

    _openMenu() {
        if (!this._menuClient)
            return false;
        this._menuClient.aboutToShow();
        this._menuClient.event(0, 'opened');
        this._menuClient.update();
        if (this._popup.isEmpty())
            this._rebuildMenu();
        if (this._popup.isEmpty())
            return false;
        this._popup.toggle();
        return true;
    }

    _contextMenu(x, y) {
        if (!this._openMenu())
            this._item.activate('ContextMenu', x, y);
    }

    // --- Input ----------------------------------------------------------

    _eventPosition(event) {
        const [x, y] = event.get_coords();
        return [Math.round(x), Math.round(y)];
    }

    _onButtonPress(event) {
        const button = event.get_button();
        const [x, y] = this._eventPosition(event);
        if (this._popup.isOpen) {
            this._popup.close();
            return Clutter.EVENT_STOP;
        }
        if (button === Clutter.BUTTON_PRIMARY) {
            if (this._item.itemIsMenu && this._openMenu())
                return Clutter.EVENT_STOP;
            this._item.activate('Activate', x, y, () => this._contextMenu(x, y));
        } else if (button === Clutter.BUTTON_MIDDLE) {
            this._item.activate('SecondaryActivate', x, y);
        } else if (button === Clutter.BUTTON_SECONDARY) {
            this._contextMenu(x, y);
        }
        return Clutter.EVENT_STOP;
    }

    _onScroll(event) {
        const direction = event.get_scroll_direction();
        const steps = {
            [Clutter.ScrollDirection.UP]: [-1, 'vertical'],
            [Clutter.ScrollDirection.DOWN]: [1, 'vertical'],
            [Clutter.ScrollDirection.LEFT]: [-1, 'horizontal'],
            [Clutter.ScrollDirection.RIGHT]: [1, 'horizontal'],
        }[direction];
        if (steps)
            this._item.scroll(steps[0] * 120, steps[1]);
        return Clutter.EVENT_STOP;
    }

    _onKeyPress(event) {
        const symbol = event.get_key_symbol();
        if (symbol === Clutter.KEY_Return || symbol === Clutter.KEY_KP_Enter ||
            symbol === Clutter.KEY_space) {
            const [x, y] = this.get_transformed_position();
            this._item.activate('Activate', Math.round(x), Math.round(y),
                () => this._contextMenu(x, y));
            return Clutter.EVENT_STOP;
        }
        if (symbol === Clutter.KEY_Menu ||
            (symbol === Clutter.KEY_F10 && event.get_state() & Clutter.ModifierType.SHIFT_MASK)) {
            const [x, y] = this.get_transformed_position();
            this._contextMenu(Math.round(x), Math.round(y));
            return Clutter.EVENT_STOP;
        }
        return Clutter.EVENT_PROPAGATE;
    }

    _onDestroy() {
        this._menuClient?.destroy();
        this._menuClient = null;
        this._item.disconnectObject(this);
        this._popup.destroy();
    }
});
