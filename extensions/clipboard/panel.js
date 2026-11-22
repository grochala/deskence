// SPDX-License-Identifier: GPL-3.0-or-later
//
// The clipboard history panel: tiles of texts and images, a search, pins,
// removing, clearing and pausing.
//
// It opens in the middle of the monitor of the focused window and holds a
// grab like a menu: a click outside or Escape closes it. The search has the
// keyboard first; Down or Tab moves to the tiles, arrows move between
// them, Enter chooses one (Shift+Enter: as plain text), Delete removes
// it, Ctrl+P pins it. Long texts are cut to a few lines in their tile; the
// whole text is what gets pasted.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Pango from 'gi://Pango';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as GrabHelper from 'resource:///org/gnome/shell/ui/grabHelper.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {gettext as _, ngettext} from 'resource:///org/gnome/shell/extensions/extension.js';

import {matches, preview} from './history.js';

const PANEL_WIDTH = 660;
const TILE_WIDTH = 196;
const TILE_HEIGHT = 132;
const IMAGE_SIZE = 84;
const MAX_HEIGHT_SHARE = 0.7;

function setVertical(box, vertical) {
    if ('orientation' in box)
        box.orientation = vertical ? Clutter.Orientation.VERTICAL : Clutter.Orientation.HORIZONTAL;
    else
        box.vertical = vertical;
}

function age(time) {
    const minutes = Math.floor((Date.now() - time) / 60000);
    if (minutes < 1)
        return _('Just now');
    if (minutes < 60)
        return ngettext('%d minute ago', '%d minutes ago', minutes).replace('%d', minutes);
    const hours = Math.floor(minutes / 60);
    if (hours < 24)
        return ngettext('%d hour ago', '%d hours ago', hours).replace('%d', hours);
    return GLib.DateTime.new_from_unix_local(Math.floor(time / 1000))?.format('%x') ?? '';
}

function smallButton(iconName, label) {
    return new St.Button({
        style_class: 'deskence-clipboard-tile-button',
        child: new St.Icon({icon_name: iconName, icon_size: 14}),
        accessible_name: label,
        can_focus: false,
        track_hover: true,
    });
}

export class ClipboardPanel {
    // controller: the extension (history, settings and actions).
    constructor(controller) {
        this._controller = controller;
        this._actor = null;
        this._grabHelper = null;
        this._confirmClear = false;
    }

    get isOpen() {
        return this._actor !== null;
    }

    open() {
        if (this._actor)
            return;
        this._actor = new St.BoxLayout({
            style_class: 'popup-menu-content deskence-clipboard-panel',
            reactive: true,
            accessible_name: _('Clipboard History'),
            width: PANEL_WIDTH,
        });
        setVertical(this._actor, true);

        const header = new St.BoxLayout({style_class: 'deskence-clipboard-header'});
        this._search = new St.Entry({
            style_class: 'search-entry deskence-clipboard-search',
            hint_text: _('Search the history'),
            can_focus: true,
            x_expand: true,
        });
        this._search.clutter_text.connect('text-changed', () => this._fill());
        this._search.clutter_text.connect('key-press-event', (_a, event) => this._onSearchKey(event));
        header.add_child(this._search);
        this._pause = new St.Button({
            style_class: 'deskence-clipboard-header-button',
            toggle_mode: true,
            can_focus: true,
            child: new St.Icon({icon_name: 'media-playback-pause-symbolic', icon_size: 16}),
        });
        this._pause.connect('clicked', () => {
            this._controller.setPaused(this._pause.checked);
            this._syncHeader();
        });
        header.add_child(this._pause);
        this._clear = new St.Button({
            style_class: 'deskence-clipboard-header-button',
            can_focus: true,
            accessible_name: _('Clear History'),
            child: new St.Icon({icon_name: 'edit-clear-all-symbolic', icon_size: 16}),
        });
        this._clear.connect('clicked', () => this._onClear());
        header.add_child(this._clear);
        this._actor.add_child(header);

        this._notice = new St.Label({style_class: 'deskence-clipboard-notice', visible: false});
        this._notice.clutter_text.line_wrap = true;
        this._actor.add_child(this._notice);

        this._scroll = new St.ScrollView({
            style_class: 'deskence-clipboard-scroll',
            hscrollbar_policy: St.PolicyType.NEVER,
            vscrollbar_policy: St.PolicyType.AUTOMATIC,
            overlay_scrollbars: true,
        });
        this._grid = new St.Viewport({
            style_class: 'deskence-clipboard-grid',
            layout_manager: new Clutter.FlowLayout({
                orientation: Clutter.Orientation.HORIZONTAL,
                homogeneous: true,
                column_spacing: 8,
                row_spacing: 8,
            }),
        });
        this._scroll.set_child(this._grid);
        this._actor.add_child(this._scroll);

        this._hint = new St.Label({
            style_class: 'deskence-clipboard-hint',
            text: _('Enter: paste · Shift+Enter: paste as plain text · Delete: remove · ' +
                'Ctrl+P: pin'),
        });
        this._hint.clutter_text.ellipsize = Pango.EllipsizeMode.END;
        this._actor.add_child(this._hint);

        Main.layoutManager.addTopChrome(this._actor);
        this._syncHeader();
        this._fill();
        this._place();

        const actor = this._actor;
        this._grabHelper = new GrabHelper.GrabHelper(actor, {actionMode: Shell.ActionMode.POPUP});
        this._grabHelper.grab({actor, focus: this._search, onUngrab: () => this._onUngrab(actor)});
    }

    _syncHeader() {
        const paused = this._controller.paused;
        this._pause.checked = paused;
        this._pause.accessible_name = paused ? _('Resume Remembering') : _('Pause Remembering');
        this._pause.child.icon_name = paused ? 'media-playback-start-symbolic'
            : 'media-playback-pause-symbolic';
        this._confirmClear = false;
        this._clear.accessible_name = _('Clear History');
    }

    _onClear() {
        // The second click confirms; pinned items stay.
        if (!this._confirmClear) {
            this._confirmClear = true;
            this._clear.add_style_pseudo_class('checked');
            this._clear.accessible_name = _('Click Again to Clear');
            this._setNotice(_('Click again to remove all items except pinned ones.'));
            return;
        }
        this._clear.remove_style_pseudo_class('checked');
        this._controller.clear();
    }

    _setNotice(text) {
        this._notice.text = text ?? '';
        this._notice.visible = Boolean(text);
    }

    // The history changed while open.
    refresh() {
        if (!this._actor)
            return;
        this._syncHeader();
        this._fill();
    }

    _fill() {
        if (!this._actor)
            return;
        const focusedId = global.stage.key_focus?._deskenceEntryId;
        this._grid.destroy_all_children();
        const query = this._search.text.trim();
        const entries = this._controller.history.entries.filter(e => matches(e, query));
        for (const entry of entries)
            this._grid.add_child(this._tile(entry));

        const all = this._controller.history.entries.length;
        if (this._confirmClear)
            this._setNotice(_('Click again to remove all items except pinned ones.'));
        else if (this._controller.paused)
            this._setNotice(_('New items are not remembered until you resume.'));
        else if (all === 0)
            this._setNotice(_('Nothing copied yet. Items you copy appear here.'));
        else if (entries.length === 0)
            this._setNotice(_('No items match the search.'));
        else
            this._setNotice(null);
        this._scroll.visible = entries.length > 0;
        if (focusedId !== undefined) {
            const tile = this._grid.get_children().find(t => t._deskenceEntryId === focusedId);
            (tile ?? this._grid.get_first_child() ?? this._search).grab_key_focus();
        }
        this._place();
    }

    _tile(entry) {
        const tile = new St.Button({
            style_class: 'popup-menu-item deskence-clipboard-tile',
            can_focus: true,
            track_hover: true,
            width: TILE_WIDTH,
            height: TILE_HEIGHT,
            accessible_name: entry.kind === 'text' ? preview(entry.text, 120)
                : _('Image, %s').replace('%s', GLib.format_size(entry.size)),
        });
        tile._deskenceEntryId = entry.id;
        if (entry.pinned)
            tile.add_style_class_name('deskence-clipboard-pinned');
        const box = new St.BoxLayout({x_expand: true, y_expand: true});
        setVertical(box, true);

        const top = new St.BoxLayout({style_class: 'deskence-clipboard-tile-top'});
        const info = new St.Label({
            style_class: 'deskence-clipboard-tile-info',
            text: entry.kind === 'image'
                ? `${age(entry.time)} · ${GLib.format_size(entry.size)}`
                : age(entry.time),
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        info.clutter_text.ellipsize = Pango.EllipsizeMode.END;
        top.add_child(info);
        const pin = smallButton('view-pin-symbolic', entry.pinned ? _('Unpin') : _('Pin'));
        pin.toggle_mode = true;
        pin.checked = entry.pinned;
        pin.connect('clicked', () => this._controller.setPinned(entry.id, !entry.pinned));
        const remove = smallButton('window-close-symbolic', _('Remove'));
        remove.connect('clicked', () => this._controller.remove(entry.id));
        top.add_child(pin);
        top.add_child(remove);
        box.add_child(top);

        if (entry.kind === 'image') {
            box.add_child(new St.Icon({
                gicon: new Gio.BytesIcon({bytes: entry.bytes}),
                fallback_icon_name: 'image-x-generic-symbolic',
                icon_size: IMAGE_SIZE,
                x_align: Clutter.ActorAlign.CENTER,
                y_align: Clutter.ActorAlign.CENTER,
                y_expand: true,
            }));
        } else {
            const text = new St.Label({
                style_class: 'deskence-clipboard-tile-text',
                text: preview(entry.text),
                x_expand: true,
                y_expand: true,
            });
            text.clutter_text.line_wrap = true;
            text.clutter_text.line_wrap_mode = Pango.WrapMode.WORD_CHAR;
            text.clutter_text.ellipsize = Pango.EllipsizeMode.END;
            box.add_child(text);
        }
        tile.set_child(box);
        tile.connect('clicked', () => {
            const event = Clutter.get_current_event();
            const shift = event && (event.get_state() & Clutter.ModifierType.SHIFT_MASK) !== 0;
            this._controller.choose(entry, shift);
        });
        tile.connect('key-press-event', (_a, event) => this._onTileKey(tile, entry, event));
        return tile;
    }

    _onSearchKey(event) {
        const key = event.get_key_symbol();
        const first = this._grid.get_first_child();
        if ((key === Clutter.KEY_Down || key === Clutter.KEY_Tab) && first && this._scroll.visible) {
            first.grab_key_focus();
            return Clutter.EVENT_STOP;
        }
        if ((key === Clutter.KEY_Return || key === Clutter.KEY_KP_Enter) && first && this._scroll.visible) {
            const shift = (event.get_state() & Clutter.ModifierType.SHIFT_MASK) !== 0;
            const entry = this._controller.history.find(first._deskenceEntryId);
            if (entry)
                this._controller.choose(entry, shift);
            return Clutter.EVENT_STOP;
        }
        return Clutter.EVENT_PROPAGATE;
    }

    _onTileKey(tile, entry, event) {
        const key = event.get_key_symbol();
        const state = event.get_state();
        const shift = (state & Clutter.ModifierType.SHIFT_MASK) !== 0;
        const ctrl = (state & Clutter.ModifierType.CONTROL_MASK) !== 0;
        if (key === Clutter.KEY_Return || key === Clutter.KEY_KP_Enter || key === Clutter.KEY_space) {
            this._controller.choose(entry, shift);
            return Clutter.EVENT_STOP;
        }
        if (key === Clutter.KEY_Delete) {
            const next = tile.get_next_sibling() ?? tile.get_previous_sibling();
            this._controller.remove(entry.id);
            (this._grid.get_children().find(t => t._deskenceEntryId === next?._deskenceEntryId) ??
                this._search).grab_key_focus();
            return Clutter.EVENT_STOP;
        }
        if (ctrl && (key === Clutter.KEY_p || key === Clutter.KEY_P)) {
            this._controller.setPinned(entry.id, !entry.pinned);
            return Clutter.EVENT_STOP;
        }
        const directions = {
            [Clutter.KEY_Left]: St.DirectionType.LEFT,
            [Clutter.KEY_Right]: St.DirectionType.RIGHT,
            [Clutter.KEY_Up]: St.DirectionType.UP,
            [Clutter.KEY_Down]: St.DirectionType.DOWN,
        };
        if (key in directions) {
            if (!this._grid.navigate_focus(tile, directions[key], false) && key === Clutter.KEY_Up)
                this._search.grab_key_focus();
            this._scrollTo(global.stage.key_focus);
            return Clutter.EVENT_STOP;
        }
        // Typing goes to the search.
        const unicode = Clutter.keysym_to_unicode(key);
        if (unicode && !ctrl && GLib.unichar_isprint(String.fromCodePoint(unicode))) {
            this._search.grab_key_focus();
            this._search.clutter_text.insert_unichar(String.fromCodePoint(unicode));
            return Clutter.EVENT_STOP;
        }
        return Clutter.EVENT_PROPAGATE;
    }

    _scrollTo(actor) {
        if (!actor || !this._grid.contains(actor))
            return;
        const adjustment = this._scroll.vadjustment;
        const box = actor.get_allocation_box();
        if (box.y1 < adjustment.value)
            adjustment.value = box.y1;
        else if (box.y2 > adjustment.value + adjustment.page_size)
            adjustment.value = box.y2 - adjustment.page_size;
    }

    // In the middle of the monitor of the focused window (or the pointer).
    _place() {
        const window = global.display.focus_window;
        const index = window?.get_monitor() ?? global.display.get_current_monitor();
        const area = Main.layoutManager.getWorkAreaForMonitor(index);
        const width = Math.min(PANEL_WIDTH, area.width - 32);
        this._actor.width = width;
        this._scroll.height = -1;
        const [, natural] = this._actor.get_preferred_height(width);
        const [, scrollNatural] = this._scroll.get_preferred_height(width);
        const [, gridNatural] = this._grid.get_preferred_height(width - 16);
        const limit = Math.round(area.height * MAX_HEIGHT_SHARE) - (natural - scrollNatural);
        if (this._scroll.visible)
            this._scroll.height = Math.max(TILE_HEIGHT, Math.min(gridNatural, limit));
        const [, height] = this._actor.get_preferred_height(width);
        this._actor.set_position(Math.round(area.x + (area.width - width) / 2),
            Math.round(area.y + (area.height - height) / 3));
    }

    // A click outside or Escape: GrabHelper still holds the grab while it
    // calls this (see extensions/dock/stacks.js).
    _onUngrab(actor) {
        if (this._actor !== actor)
            return;
        this._grabHelper = null;
        actor.hide();
        GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            if (this._actor === actor)
                this.close();
            return GLib.SOURCE_REMOVE;
        });
    }

    close() {
        if (!this._actor)
            return;
        const actor = this._actor;
        this._actor = null;
        const grabHelper = this._grabHelper;
        this._grabHelper = null;
        if (grabHelper?.grabbed)
            grabHelper.ungrab({actor});
        actor.destroy();
        this._controller.panelClosed?.();
    }

    destroy() {
        this.close();
        this._controller = null;
    }
}
