// SPDX-License-Identifier: GPL-3.0-or-later
//
// Context menus of the desktop, drawn by the shell for the desktop icons
// process (see desktop-icons/deskence_desktop/shellareas.py for the
// format).
//
// The process's own GTK menus would be Wayland popups, and mutter keeps
// popups inside the work area: beside a dock that reserves space a menu
// would open above the dock instead of at the click, or be squeezed. Shell
// menus have no such limit. The menu opens at the clicked point and is only
// moved or flipped when it would not fit on the monitor it was opened on
// (below the top bar); the band along a dock is not treated as excluded.

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {placeMenu} from './areas.js';

export class DesktopMenu {
    // activate(action, target): called with the chosen item.
    constructor(spec, monitor, area, activate) {
        this._source = new St.Widget({opacity: 0, reactive: false, width: 1, height: 1});
        Main.uiGroup.add_child(this._source);
        const point = {x: monitor.x + spec.x, y: monitor.y + spec.y};
        this._source.set_position(point.x, point.y);

        this.menu = new PopupMenu.PopupMenu(this._source, 0, St.Side.TOP);
        this.menu.actor.add_style_class_name('background-menu');
        this._placeAt(point, area);
        Main.uiGroup.add_child(this.menu.actor);
        this.menu.actor.hide();
        this._manager = new PopupMenu.PopupMenuManager(this._source);
        this._manager.addMenu(this.menu);
        this._fill(this.menu, spec.sections ?? [], activate);

        // Closed by a choice, Escape or a click elsewhere: gone for good,
        // after the menu has finished handling the closing.
        this.menu.connect('open-state-changed', (_m, open) => {
            if (!open) {
                GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
                    this.destroy();
                    return GLib.SOURCE_REMOVE;
                });
            }
        });
        this.menu.open();
        if (spec.keyboard)
            this.menu.actor.navigate_focus(null, St.DirectionType.TAB_FORWARD, false);
    }

    // The shell's box pointer keeps menus inside the work area; this one
    // only stays inside `area` (stage coordinates): the clicked monitor
    // below the top bar. placeMenu() in areas.js decides.
    _placeAt(point, area) {
        const boxPointer = this.menu._boxPointer;
        boxPointer._calculateArrowSide = side => side;
        boxPointer._reposition = function (allocationBox) {
            const [, , width, height] = this.get_preferred_size();
            const pos = placeMenu(point, {width, height}, area);
            // Stage coordinates to the parent's; the menu lives in uiGroup.
            const [ok, x, y] = this.get_parent().transform_stage_point(pos.x, pos.y);
            allocationBox.set_origin(Math.floor(ok ? x : pos.x), Math.floor(ok ? y : pos.y));
        };
    }

    _fill(menu, sections, activate) {
        sections.forEach((items, index) => {
            if (index > 0)
                menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
            for (const spec of items)
                menu.addMenuItem(this._item(spec, activate));
        });
    }

    _item(spec, activate) {
        if (spec.submenu) {
            const item = new PopupMenu.PopupSubMenuMenuItem(spec.label);
            this._fill(item.menu, spec.submenu, activate);
            return item;
        }
        const item = new PopupMenu.PopupMenuItem(spec.label);
        if (spec.accel) {
            const accel = new St.Label({
                text: spec.accel,
                x_expand: true,
                x_align: Clutter.ActorAlign.END,
                style: 'padding-left: 24px;',
                opacity: 140,
            });
            item.add_child(accel);
        }
        if (spec.checked !== null && spec.checked !== undefined)
            item.setOrnament(spec.checked ? PopupMenu.Ornament.DOT : PopupMenu.Ornament.NONE);
        item.setSensitive(spec.enabled !== false);
        item.connect('activate', () => activate(spec.action, spec.target ?? null));
        return item;
    }

    close() {
        this.menu.close();
    }

    destroy() {
        if (!this._source)
            return;
        const source = this._source;
        this._source = null;
        this.menu.destroy();
        source.destroy();
    }
}
