// SPDX-License-Identifier: GPL-3.0-or-later

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {DockManager} from './dock.js';
import {InputDiagnostics} from './inputDiagnostics.js';
import {StartOnDesktop} from './startup.js';

// GNOME Shell 48 may create two objects of the same extension and enable
// both when several extensions are enabled in quick succession (fixed in
// GNOME 49). The running state therefore lives in the module, which both
// objects share, so the feature never starts twice and one disable() call
// cleans up everything.
let manager = null;
let startup = null;
let diagnostics = null;

export default class DeskenceDockExtension extends Extension {
    enable() {
        diagnostics ??= new InputDiagnostics();
        startup ??= new StartOnDesktop(this.getSettings('io.github.deskence.Deskence'));
        manager ??= new DockManager(this.getSettings('io.github.deskence.Deskence.Dock'));
    }

    disable() {
        manager?.destroy();
        manager = null;
        startup?.destroy();
        startup = null;
        diagnostics?.destroy();
        diagnostics = null;
    }
}
