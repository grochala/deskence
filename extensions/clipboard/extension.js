// SPDX-License-Identifier: GPL-3.0-or-later
//
// Clipboard history of Deskence.
//
// Ctrl+C and Ctrl+V keep working as always; this only watches what is
// copied (Meta.Selection "owner-changed") and remembers texts and images
// in memory (history.js). Its own shortcut opens a panel (panel.js);
// choosing an item puts it on the clipboard, closes the panel and pastes it
// into the window that was focused, with Ctrl+V (Ctrl+Shift+V in
// terminals) sent from GNOME Shell's own virtual keyboard - the mechanism
// of the on-screen keyboard, no extra process and nothing X11-specific.
// Without such a window, or with pasting turned off, the item is only put
// on the clipboard and "Ready to Paste" is shown.
//
// Not remembered: content marked as secret by the application
// (x-kde-passwordManagerHint, used by password managers; other secrets
// cannot be recognised), anything while remembering is paused or the
// screen is locked, the primary selection (text selected with the mouse)
// unless turned on, texts and images over the size limits. Nothing is
// written to disk unless "remember" asks for it (storage.js), and contents
// never appear in the log.
//
// The extension also runs in the unlock dialog session mode so the history
// in memory survives locking the screen; while locked, nothing is watched
// and the panel cannot open (its shortcut only works in the normal mode).
// Turning the extension off stops watching, drops the history from memory
// and removes the shortcut.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension, gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

import {History, MAX_IMAGE_BYTES, pickFormat} from './history.js';
import {ClipboardPanel} from './panel.js';
import {HistoryStorage} from './storage.js';

// Reading starts once the new owner settled (some applications offer
// several times in a row).
const READ_DELAY = 60;
// After the panel closed, the focus is back in the window before pasting.
const PASTE_DELAY = 120;

class ClipboardController {
    constructor(settings) {
        this._settings = settings;
        this.history = new History(settings.get_int('max-entries'));
        this._storage = new HistoryStorage();
        this._panel = new ClipboardPanel(this);
        this._clipboard = St.Clipboard.get_default();
        this._readIds = {};
        this._serials = {};
        this._ownChangeUntil = 0;
        this._currentId = null;
        this._target = null;
        this._keyboard = null;
        this._pasteId = 0;

        if (settings.get_string('remember') !== 'nothing') {
            this._storage.load((index, loadImage) => {
                if (!this._settings)
                    return;
                if (this.history.restore(index, loadImage) > 0)
                    this._panel.refresh();
            });
        }

        global.display.get_selection().connectObject('owner-changed',
            (_s, type, source) => this._onOwnerChanged(type, source), this);
        Main.sessionMode.connectObject('updated', () => {
            if (Main.sessionMode.isLocked)
                this._panel.close();
        }, this);
        settings.connectObject(
            'changed::max-entries', () => {
                this.history.setMaxEntries(settings.get_int('max-entries'));
                this._changed();
            },
            'changed::remember', () => {
                if (settings.get_string('remember') === 'nothing')
                    this._storage.erase();
                else
                    this._changed();
            },
            'changed::paused', () => this._panel.refresh(),
            this);
        // mutter follows later changes of the key by itself (the previous
        // combination is released) and drops the binding in disable().
        const action = Main.wm.addKeybinding('shortcut', settings,
            Meta.KeyBindingFlags.IGNORE_AUTOREPEAT,
            Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW, () => this.toggle());
        if (action === Meta.KeyBindingAction.NONE) {
            console.warn('Deskence Clipboard: the shortcut could not be registered; another ' +
                'program may use it');
        }
    }

    get paused() {
        return this._settings.get_boolean('paused');
    }

    setPaused(paused) {
        this._settings.set_boolean('paused', paused);
    }

    // --- Watching -------------------------------------------------------

    _onOwnerChanged(type, source) {
        let stType;
        if (type === Meta.SelectionType.SELECTION_CLIPBOARD)
            stType = St.ClipboardType.CLIPBOARD;
        else if (type === Meta.SelectionType.SELECTION_PRIMARY &&
                 this._settings.get_boolean('include-primary'))
            stType = St.ClipboardType.PRIMARY;
        else
            return;
        if (stType === St.ClipboardType.CLIPBOARD) {
            // What we put there ourselves is already in the history.
            if (GLib.get_monotonic_time() < this._ownChangeUntil) {
                this._ownChangeUntil = 0;
                return;
            }
            this._currentId = null;
        }
        if (!source || this.paused || Main.sessionMode.isLocked)
            return;
        const serial = (this._serials[stType] ?? 0) + 1;
        this._serials[stType] = serial;
        if (this._readIds[stType])
            GLib.source_remove(this._readIds[stType]);
        this._readIds[stType] = GLib.timeout_add(GLib.PRIORITY_DEFAULT, READ_DELAY, () => {
            this._readIds[stType] = 0;
            this._read(stType, serial);
            return GLib.SOURCE_REMOVE;
        });
    }

    _read(stType, serial) {
        const format = pickFormat(this._clipboard.get_mimetypes(stType));
        if (!format)
            return;
        const current = () => this._settings && this._serials[stType] === serial &&
            !this.paused && !Main.sessionMode.isLocked;
        if (format.kind === 'text') {
            this._clipboard.get_text(stType, (_c, text) => {
                if (current() && text)
                    this._added(this.history.addText(text), stType);
            });
        } else {
            this._clipboard.get_content(stType, format.mime, (_c, bytes) => {
                if (!current() || !bytes || bytes.get_size() > MAX_IMAGE_BYTES)
                    return;
                // The callback's buffer is not ours to keep: icons are loaded
                // from it in other threads later, so it is copied.
                const copy = new GLib.Bytes(bytes.toArray());
                this._added(this.history.addImage(copy, format.mime), stType);
            });
        }
    }

    _added(entry, stType) {
        if (!entry)
            return;
        if (stType === St.ClipboardType.CLIPBOARD)
            this._currentId = entry.id;
        this._changed();
    }

    _changed() {
        const remember = this._settings.get_string('remember');
        if (remember !== 'nothing')
            this._storage.queueSave(this.history.toStored(remember));
        this._panel.refresh();
    }

    // --- Panel actions --------------------------------------------------

    toggle() {
        if (this._panel.isOpen) {
            this._panel.close();
            return;
        }
        if (Main.sessionMode.isLocked)
            return;
        this._target = global.display.focus_window;
        this._panel.open();
    }

    panelClosed() {
    }

    setPinned(id, pinned) {
        this.history.setPinned(id, pinned);
        this._changed();
    }

    remove(id) {
        this.history.remove(id);
        this._changed();
    }

    clear() {
        this.history.clear();
        this._changed();
    }

    // Puts an entry on the clipboard and pastes it. The newest entry, while
    // its application still offers it, is left as it is so it keeps its
    // formatting, unless plain text was asked for.
    choose(entry, plain) {
        const target = this._target;
        this._target = null;
        const keep = entry.kind === 'text' && entry.id === this._currentId && !plain &&
            !this._settings.get_boolean('paste-plain-text');
        if (!keep) {
            this._ownChangeUntil = GLib.get_monotonic_time() + 500 * 1000;
            if (entry.kind === 'text')
                this._clipboard.set_text(St.ClipboardType.CLIPBOARD, entry.text);
            else
                this._clipboard.set_content(St.ClipboardType.CLIPBOARD, entry.mime, entry.bytes);
            this._currentId = entry.id;
        }
        // The chosen item becomes the newest.
        if (entry.kind === 'text')
            this.history.addText(entry.text);
        else
            this.history.addImage(entry.bytes, entry.mime);
        this._changed();
        this._panel.close();

        if (!this._settings.get_boolean('paste-on-select') || !target?.get_compositor_private()) {
            this._showReady();
            return;
        }
        if (this._pasteId)
            GLib.source_remove(this._pasteId);
        this._pasteId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, PASTE_DELAY, () => {
            this._pasteId = 0;
            if (global.display.focus_window === target && !Main.sessionMode.isLocked)
                this._paste(target);
            else
                this._showReady();
            return GLib.SOURCE_REMOVE;
        });
    }

    // Ctrl+V, or Ctrl+Shift+V in terminals, from the shell's own virtual
    // keyboard.
    _paste(window) {
        const app = Shell.WindowTracker.get_default().get_window_app(window);
        const categories = app?.get_app_info()?.get_categories() ?? '';
        const terminal = categories.split(';').includes('TerminalEmulator');
        this._keyboard ??= global.stage.context.get_backend().get_default_seat()
            .create_virtual_device(Clutter.InputDeviceType.KEYBOARD_DEVICE);
        const keys = terminal
            ? [Clutter.KEY_Control_L, Clutter.KEY_Shift_L, Clutter.KEY_v]
            : [Clutter.KEY_Control_L, Clutter.KEY_v];
        const time = () => GLib.get_monotonic_time();
        for (const key of keys)
            this._keyboard.notify_keyval(time(), key, Clutter.KeyState.PRESSED);
        for (const key of [...keys].reverse())
            this._keyboard.notify_keyval(time(), key, Clutter.KeyState.RELEASED);
    }

    _showReady() {
        const icon = new Gio.ThemedIcon({name: 'edit-paste-symbolic'});
        const label = _('Ready to Paste');
        const monitor = global.display.get_current_monitor();
        const osd = Main.osdWindowManager;
        if (osd.showOne)
            osd.showOne(monitor, icon, label);
        else
            osd.show(monitor, icon, label);
    }

    destroy() {
        for (const id of Object.values(this._readIds)) {
            if (id)
                GLib.source_remove(id);
        }
        this._readIds = {};
        if (this._pasteId)
            GLib.source_remove(this._pasteId);
        this._pasteId = 0;
        Main.wm.removeKeybinding('shortcut');
        global.display.get_selection().disconnectObject(this);
        Main.sessionMode.disconnectObject(this);
        this._settings.disconnectObject(this);
        this._panel.destroy();
        this._storage.destroy();
        this.history.entries = [];
        this._keyboard = null;
        this._target = null;
        this._settings = null;
    }
}

// Module state, see extensions/dock/extension.js.
let controller = null;

export default class DeskenceClipboardExtension extends Extension {
    enable() {
        controller ??= new ClipboardController(this.getSettings('io.github.deskence.Deskence.Clipboard'));
    }

    disable() {
        controller?.destroy();
        controller = null;
    }
}
