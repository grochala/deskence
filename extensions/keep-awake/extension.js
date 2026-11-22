// SPDX-License-Identifier: GPL-3.0-or-later
//
// "Keep Awake" in the quick settings.
//
// Clicking the button turns it on with the duration chosen last; the menu
// offers: no limit, 15, 30 or 60 minutes, a custom duration and "until" a
// time of day, the time left (or the end time), ending early, and
// keeping the screen on as a separate choice.
//
// It asks GNOME's session manager (org.gnome.SessionManager.Inhibit), the
// same way video players and installers do:
//  - always "suspend": automatic suspend after inactivity does not happen.
//    The session manager passes it on to logind in the "block-weak" mode,
//    which a suspend the user asks for (the system menu, the power
//    button, closing the lid by policy) is not stopped by;
//  - "idle" only with "Keep the screen on": the session is then never
//    idle, so the screen neither blanks nor locks automatically. Without
//    it the screen turns off and locks as usual.
// Nothing simulates input, and an already locked screen stays locked.
//
// The session ends when its time is over (checked against the monotonic
// clock for durations and the wall clock for "until", see timing.js),
// when it is ended from the menu, and when the extension is turned off:
// the inhibitor is released every time. It is never stored, so presets
// and logging in again start without it.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {QuickMenuToggle, SystemIndicator} from 'resource:///org/gnome/shell/ui/quickSettings.js';
import {Extension, gettext as _, ngettext} from 'resource:///org/gnome/shell/extensions/extension.js';

import {formatTime, minutesLeft, plan, remaining, stepMinutes} from './timing.js';

const APP_ID = 'io.github.deskence.Deskence';
const ICON = 'weather-clear-symbolic';
// org.gnome.SessionManager inhibit flags.
const INHIBIT_SUSPEND = 4;
const INHIBIT_IDLE = 8;
// The time left is shown in minutes; checked this often, and once more
// right at the end.
const TICK_SECONDS = 20;

function sessionManager(method, parameters, callback) {
    Gio.DBus.session.call('org.gnome.SessionManager', '/org/gnome/SessionManager',
        'org.gnome.SessionManager', method, parameters, null, Gio.DBusCallFlags.NONE, -1, null,
        (bus, res) => {
            try {
                callback?.(bus.call_finish(res));
            } catch (e) {
                console.warn(`Deskence: ${method} failed: ${e.message}`);
                callback?.(null);
            }
        });
}

// The session manager's inhibitor; the cookie is released when replaced
// or when the session ends.
class Inhibitor {
    constructor() {
        this._cookie = 0;
        this._flags = 0;
        this._serial = 0;
    }

    set(flags) {
        if (flags === this._flags)
            return;
        const serial = ++this._serial;
        const old = this._cookie;
        this._flags = flags;
        this._cookie = 0;
        if (!flags) {
            this._release(old);
            return;
        }
        const reason = flags & INHIBIT_IDLE
            ? _('Keep Awake is on: the screen stays on')
            : _('Keep Awake is on');
        // The new one first, so there is no gap.
        sessionManager('Inhibit', new GLib.Variant('(susu)', [APP_ID, 0, reason, flags]),
            result => {
                const cookie = result?.deepUnpack()[0] ?? 0;
                if (serial !== this._serial) {
                    this._release(cookie);
                    return;
                }
                this._cookie = cookie;
                this._release(old);
            });
    }

    _release(cookie) {
        if (cookie)
            sessionManager('Uninhibit', new GLib.Variant('(u)', [cookie]));
    }

    destroy() {
        this.set(0);
    }
}

const ChoiceItem = GObject.registerClass(
class ChoiceItem extends PopupMenu.PopupBaseMenuItem {
    _init(label, onActivate) {
        super._init();
        this.label = new St.Label({text: label, x_expand: true});
        this.add_child(this.label);
        this.label_actor = this.label;
        this.connect('activate', onActivate);
    }
});

// A menu item with "−" and "+" buttons adjusting a value.
const AdjustItem = GObject.registerClass(
class AdjustItem extends PopupMenu.PopupBaseMenuItem {
    _init(onActivate, onAdjust) {
        super._init();
        this.label = new St.Label({x_expand: true, y_align: Clutter.ActorAlign.CENTER});
        this.add_child(this.label);
        this.label_actor = this.label;
        for (const [icon, delta, name] of [['list-remove-symbolic', -1, _('Less')],
            ['list-add-symbolic', 1, _('More')]]) {
            const button = new St.Button({
                style_class: 'button deskence-keep-awake-adjust',
                child: new St.Icon({icon_name: icon, icon_size: 14}),
                accessible_name: name,
                can_focus: true,
            });
            button.connect('clicked', () => onAdjust(delta));
            this.add_child(button);
        }
        this.connect('activate', onActivate);
    }
});

const KeepAwakeToggle = GObject.registerClass(
class KeepAwakeToggle extends QuickMenuToggle {
    _init(controller) {
        super._init({title: _('Keep Awake'), iconName: ICON, toggleMode: false});
        this._controller = controller;
        this.menu.setHeader(ICON, _('Keep Awake'), _('Prevents automatic suspend'));
        const settings = controller.settings;

        this._items = {};
        const choice = (key, label) => {
            this._items[key] = new ChoiceItem(label, () => controller.start(key));
            this.menu.addMenuItem(this._items[key]);
        };
        choice('indefinite', _('Until Turned Off'));
        choice('15', ngettext('%d Minute', '%d Minutes', 15).replace('%d', 15));
        choice('30', ngettext('%d Minute', '%d Minutes', 30).replace('%d', 30));
        choice('60', ngettext('%d Hour', '%d Hours', 1).replace('%d', 1));
        this._items.custom = new AdjustItem(() => controller.start('custom'), delta =>
            settings.set_int('custom-duration',
                stepMinutes(settings.get_int('custom-duration'), delta * 15, 5, 720)));
        this.menu.addMenuItem(this._items.custom);
        this._items.until = new AdjustItem(() => controller.start('until'), delta =>
            settings.set_int('until-time',
                stepMinutes(settings.get_int('until-time'), delta * 15, 0, 1439, true)));
        this.menu.addMenuItem(this._items.until);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._screen = new PopupMenu.PopupSwitchMenuItem(_('Keep the Screen On'),
            settings.get_boolean('keep-screen-on'));
        this._screen.connect('toggled', (_i, state) => settings.set_boolean('keep-screen-on', state));
        this.menu.addMenuItem(this._screen);
        this._screenHint = new PopupMenu.PopupMenuItem(
            _('The screen then does not turn off or lock automatically'), {reactive: false});
        this._screenHint.label.add_style_class_name('deskence-keep-awake-hint');
        this._screenHint.label.clutter_text.line_wrap = true;
        this._screenHint.label.clutter_text.ellipsize = 0;
        this.menu.addMenuItem(this._screenHint);
        this._stop = this.menu.addAction(_('End Now'), () => controller.stop());

        this.connect('clicked', () => {
            if (controller.active)
                controller.stop();
            else
                controller.start(settings.get_string('last-choice'));
        });
        settings.connectObject('changed', () => this.sync(), this);
        this.sync();
    }

    sync() {
        const controller = this._controller;
        const settings = controller.settings;
        const custom = settings.get_int('custom-duration');
        this._items.custom.label.text = custom % 60 === 0
            ? ngettext('%d Hour', '%d Hours', custom / 60).replace('%d', custom / 60)
            : ngettext('%d Minute', '%d Minutes', custom).replace('%d', custom);
        this._items.until.label.text = _('Until %s').replace('%s', formatTime(settings.get_int('until-time')));
        this._screen.setToggleState(settings.get_boolean('keep-screen-on'));
        const active = controller.active;
        for (const [key, item] of Object.entries(this._items))
            item.setOrnament(active && controller.choice === key
                ? PopupMenu.Ornament.CHECK : PopupMenu.Ornament.NONE);
        this._stop.visible = active;
        this.checked = active;
        const status = controller.status();
        this.subtitle = status;
        this.menu.setHeader(ICON, _('Keep Awake'), status ?? _('Prevents automatic suspend'));
    }
});

const Indicator = GObject.registerClass(
class Indicator extends SystemIndicator {
    _init(controller) {
        super._init();
        this._indicator = this._addIndicator();
        this._indicator.icon_name = ICON;
        this.toggle = new KeepAwakeToggle(controller);
        this.quickSettingsItems.push(this.toggle);
    }

    sync(active) {
        this._indicator.visible = active;
        this.toggle.sync();
    }
});

class KeepAwakeController {
    constructor(settings) {
        this.settings = settings;
        this.session = null;
        this.choice = null;
        this._inhibitor = new Inhibitor();
        this._tickId = 0;
        this._endId = 0;
        this._indicator = new Indicator(this);
        Main.panel.statusArea.quickSettings.addExternalIndicator(this._indicator);
        settings.connectObject('changed::keep-screen-on', () => this._apply(), this);
        this._indicator.sync(false);
    }

    get active() {
        return this.session !== null;
    }

    _clock() {
        return {now: new Date(), monotonic: GLib.get_monotonic_time()};
    }

    start(choice) {
        this.settings.set_string('last-choice', choice);
        this.choice = choice;
        this.session = plan(choice, {
            ...this._clock(),
            customMinutes: this.settings.get_int('custom-duration'),
            untilMinutes: this.settings.get_int('until-time'),
        });
        this._apply();
        this._schedule();
    }

    stop() {
        this.session = null;
        this.choice = null;
        this._clearTimers();
        this._apply();
    }

    _apply() {
        const flags = this.session
            ? INHIBIT_SUSPEND | (this.settings.get_boolean('keep-screen-on') ? INHIBIT_IDLE : 0)
            : 0;
        this._inhibitor.set(flags);
        this._indicator.sync(this.active);
    }

    // A tick refreshes the time left and notices clock changes; a timeout
    // ends the session on time.
    _schedule() {
        this._clearTimers();
        if (!this.session || this.session.kind === 'indefinite')
            return;
        this._tickId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, TICK_SECONDS, () => {
            this._check();
            return GLib.SOURCE_CONTINUE;
        });
        this._rescheduleEnd();
    }

    _rescheduleEnd() {
        if (this._endId)
            GLib.source_remove(this._endId);
        const left = remaining(this.session, this._clock());
        this._endId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, Math.max(0, left) * 1000 + 50, () => {
            this._endId = 0;
            this._check();
            return GLib.SOURCE_REMOVE;
        });
    }

    _check() {
        if (!this.session)
            return;
        const left = remaining(this.session, this._clock());
        if (left !== null && left <= 0) {
            this.stop();
            return;
        }
        // The wall clock may have moved ("until").
        if (this.session.kind === 'until')
            this._rescheduleEnd();
        this._indicator.sync(true);
    }

    status() {
        if (!this.session)
            return null;
        if (this.session.kind === 'indefinite')
            return _('Until turned off');
        if (this.session.kind === 'until') {
            const end = GLib.DateTime.new_from_unix_local(Math.floor(this.session.end / 1000));
            return _('Until %s').replace('%s', end?.format('%k:%M').trim() ?? '');
        }
        const minutes = minutesLeft(remaining(this.session, this._clock()));
        return ngettext('%d minute left', '%d minutes left', minutes).replace('%d', minutes);
    }

    _clearTimers() {
        if (this._tickId)
            GLib.source_remove(this._tickId);
        if (this._endId)
            GLib.source_remove(this._endId);
        this._tickId = this._endId = 0;
    }

    destroy() {
        this._clearTimers();
        this.session = null;
        this._inhibitor.destroy();
        this.settings.disconnectObject(this);
        this.settings.disconnectObject(this._indicator.toggle);
        this._indicator.quickSettingsItems.forEach(item => item.destroy());
        this._indicator.destroy();
        this.settings = null;
    }
}

// Module state, see extensions/dock/extension.js.
let controller = null;

export default class DeskenceKeepAwakeExtension extends Extension {
    enable() {
        controller ??= new KeepAwakeController(this.getSettings('io.github.deskence.Deskence.KeepAwake'));
    }

    disable() {
        controller?.destroy();
        controller = null;
    }
}
