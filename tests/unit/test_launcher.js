// SPDX-License-Identifier: GPL-3.0-or-later
// Run with: gjs -m tests/unit/test_launcher.js
import System from 'system';

import {LauncherState, appIdFromUri, badgeGeometry, badgeText, parseUpdate}
    from '../../extensions/dock/launcherLogic.js';

let failures = 0;
function check(name, condition) {
    if (!condition) {
        failures++;
        printerr(`FAIL: ${name}`);
    } else {
        print(`ok: ${name}`);
    }
}

// --- Mapping
check('desktop id from the uri', appIdFromUri('application://org.gnome.Fractal.desktop') ===
    'org.gnome.Fractal.desktop');
check('other uris refused', appIdFromUri('file:///x.desktop') === null &&
    appIdFromUri('application://') === null && appIdFromUri('application://x') === null &&
    appIdFromUri('application://../evil.desktop') === null && appIdFromUri(42) === null);

// --- Validation
let v = parseUpdate({'count': 3, 'count-visible': true, 'progress': 0.5,
    'progress-visible': true, 'urgent': true});
check('valid update', v.count === 3 && v.countVisible === true && v.progress === 0.5 &&
    v.progressVisible === true && !('urgent' in v));
v = parseUpdate({'count': -1, 'count-visible': 'yes', 'progress': NaN, 'progress-visible': 1});
check('invalid values ignored', Object.keys(v).length === 0);
check('progress clamped', parseUpdate({progress: 7}).progress === 1 &&
    parseUpdate({progress: -2}).progress === 0);
check('fractional count ignored', !('count' in parseUpdate({count: 2.5})));
check('large int64 counts', parseUpdate({count: 2n ** 62n}).count === Number.MAX_SAFE_INTEGER);
check('not an object', Object.keys(parseUpdate(null)).length === 0);

// --- Display
check('small numbers as they are', badgeText(7) === '7' && badgeText(99) === '99');
check('large numbers shortened', badgeText(100) === '99+' && badgeText(12345) === '99+');

// --- Badge size
const plain = badgeGeometry(48, 1);
check('badge grows with the icon', badgeGeometry(64, 1).diameter > plain.diameter);
check('badge never too small to read', badgeGeometry(16, 1).diameter === 16);
check('one digit fits the circle', plain.fontSize + 2 <= plain.diameter &&
    plain.diameter - 2 * plain.padding >= plain.fontSize * 0.6);
const magnified = badgeGeometry(48, 2);
check('laid out at the magnified size', magnified.diameter === plain.diameter * 2 &&
    magnified.scale === 2);
check('no magnification below 1', badgeGeometry(48, 0.5).scale === 1);

// --- State
const state = new LauncherState();
const app = 'org.example.Chat.desktop';
check('nothing reported, nothing shown', state.get(app).count === null &&
    state.get(app).progress === null);
check('a counter is shown when visible', state.update(':1.10', app,
    {count: 4, countVisible: true}, 1) && state.get(app).count === 4);
check('count without visibility is not shown',
    !state.update(':1.10', 'x.desktop', {count: 5}, 2) && state.get('x.desktop').count === null);
check('zero is no badge', state.update(':1.10', app, {count: 0}, 3) &&
    state.get(app).count === null);
state.update(':1.10', app, {count: 4}, 4);
// A second sender for the same application: not added up.
state.update(':1.11', app, {count: 4, countVisible: true}, 5);
check('the same counter from two senders is not counted twice', state.get(app).count === 4);
state.update(':1.11', app, {count: 9}, 6);
check('the latest sender wins', state.get(app).count === 9);
state.update(':1.11', app, {countVisible: false}, 7);
check('a sender hiding its counter falls back to the other', state.get(app).count === 4);
check('hiding the last counter hides the badge',
    state.update(':1.10', app, {countVisible: false}, 8) && state.get(app).count === null);

state.update(':1.12', app, {progress: 0.25, progressVisible: true}, 9);
check('progress', state.get(app).progress === 0.25);
check('an update that changes nothing shown is not reported',
    !state.update(':1.12', app, {progress: 0.25}, 10));
check('a vanished sender takes its values along',
    JSON.stringify(state.removeSender(':1.12')) === JSON.stringify([app]) &&
    state.get(app).progress === null);
check('an unknown sender changes nothing', state.removeSender(':1.99').length === 0);
state.update(':1.13', 'y.desktop', {count: 2, countVisible: true}, 11);
check('clear lists what was shown', JSON.stringify(state.clear()) === JSON.stringify(['y.desktop']) &&
    state.appIds().length === 0);

if (failures) {
    printerr(`${failures} failed`);
    System.exit(1);
}
