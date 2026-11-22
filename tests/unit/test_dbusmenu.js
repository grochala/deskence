// SPDX-License-Identifier: GPL-3.0-or-later
// Run with: gjs -m tests/unit/test_dbusmenu.js
import GLib from 'gi://GLib';
import System from 'system';

import {choosePixmap, parseItemService, parseNode, stripMnemonic, visibleChildren}
    from '../../extensions/tray/dbusMenuModel.js';

let failures = 0;
function check(name, condition) {
    if (!condition) {
        failures++;
        printerr(`FAIL: ${name}`);
    } else {
        print(`ok: ${name}`);
    }
}

check('mnemonic stripped', stripMnemonic('_Open') === 'Open');
check('double underscore kept', stripMnemonic('Save __as') === 'Save _as');
check('non-string label', stripMnemonic(undefined) === '');

const v = (t, x) => new GLib.Variant(t, x);
const layout = new GLib.Variant('(ia{sv}av)', [0, {}, [
    v('(ia{sv}av)', [1, {label: v('s', '_Show')}, []]),
    v('(ia{sv}av)', [2, {type: v('s', 'separator')}, []]),
    v('(ia{sv}av)', [3, {type: v('s', 'separator')}, []]),
    v('(ia{sv}av)', [4, {label: v('s', 'Hidden'), visible: v('b', false)}, []]),
    v('(ia{sv}av)', [5, {'toggle-type': v('s', 'checkmark'), 'toggle-state': v('i', 1), label: v('s', 'DND')}, []]),
    v('(ia{sv}av)', [6, {'children-display': v('s', 'submenu'), label: v('s', 'More')},
        [v('(ia{sv}av)', [7, {label: v('s', 'Nested')}, []])]]),
    v('(ia{sv}av)', [8, {type: v('s', 'separator')}, []]),
]]).deepUnpack();

const root = parseNode(layout);
check('root parsed', root && root.id === 0 && root.children.length === 7);
const shown = visibleChildren(root);
check('hidden removed, separators collapsed and trimmed',
    shown.map(c => c.id).join(',') === '1,2,5,6');
check('checkmark state', shown[2].toggleType === 'checkmark' && shown[2].toggleState === 1);
check('submenu children', shown[3].isSubmenu && shown[3].children[0].label === 'Nested');
check('garbage node rejected', parseNode(['x', {}, []]) === null && parseNode(null) === null);

const pixel = new Uint8Array([255, 10, 20, 30]);
const big = new Uint8Array(4 * 4 * 4);
const chosen = choosePixmap([[1, 1, pixel], [4, 4, big]], 1);
check('closest pixmap chosen', chosen.width === 1);
check('ARGB converted to RGBA', chosen.rgba.join(',') === '10,20,30,255');
check('wrong pixmap size rejected', choosePixmap([[2, 2, pixel]], 2) === null);
check('no pixmaps', choosePixmap([], 16) === null && choosePixmap(undefined, 16) === null);

const byName = parseItemService('org.kde.StatusNotifierItem-1-1', ':1.5');
check('bus name service', byName.busName === 'org.kde.StatusNotifierItem-1-1' &&
    byName.objectPath === '/StatusNotifierItem');
const byPath = parseItemService('/org/ayatana/NotificationItem/x', ':1.7');
check('object path service uses sender', byPath.busName === ':1.7' &&
    byPath.objectPath === '/org/ayatana/NotificationItem/x');
const combined = parseItemService(':1.9/StatusNotifierItem', null);
check('combined form', combined.busName === ':1.9' && combined.objectPath === '/StatusNotifierItem');
check('empty service rejected', parseItemService('', ':1.1') === null);

System.exit(failures ? 1 : 0);
