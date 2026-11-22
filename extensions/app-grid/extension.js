// SPDX-License-Identifier: GPL-3.0-or-later

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {AppGridSorter} from './sorter.js';

// Module state, see extensions/dock/extension.js (GNOME 48 may enable two
// objects of the same extension).
let sorter = null;

export default class DeskenceAppGridExtension extends Extension {
    enable() {
        sorter ??= new AppGridSorter(this.getSettings('io.github.deskence.Deskence.AppGrid'));
    }

    disable() {
        sorter?.destroy();
        sorter = null;
    }
}
