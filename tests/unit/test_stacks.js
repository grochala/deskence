// SPDX-License-Identifier: GPL-3.0-or-later
// Run with: gjs -m tests/unit/test_stacks.js
import System from 'system';

import {COPIED_FILES, MAX_COLUMNS, MIN_COLUMNS, canThumbnailDirectly, columnsThatFit, copiedFiles,
    gridColumns, gridFit,
    isLauncher,
    moveEntry, needsMore, panelHeights, parseEntry, sortItems, sortModeFor}
    from '../../extensions/dock/stackLogic.js';

let failures = 0;
function check(name, condition) {
    if (!condition) {
        failures++;
        printerr(`FAIL: ${name}`);
    } else {
        print(`ok: ${name}`);
    }
}

check('standard folder', parseEntry('xdg:DOWNLOAD')?.kind === 'xdg');
check('unknown standard folder', parseEntry('xdg:NOPE') === null);
check('home folder', parseEntry('home:Projects/site')?.value === 'Projects/site');
check('home cannot be left', parseEntry('home:../etc') === null && parseEntry('home:/etc') === null &&
    parseEntry('home:a/../../etc') === null);
check('file uri', parseEntry('file:///srv/x')?.kind === 'uri');
check('other schemes refused', parseEntry('http://example.com') === null &&
    parseEntry('ftp:///x') === null && parseEntry(5) === null);

check('downloads newest first by default', sortModeFor('xdg:DOWNLOAD', {}) === 'modified');
check('other folders by name', sortModeFor('xdg:DOCUMENTS', {}) === 'name');
check('chosen order wins', sortModeFor('xdg:DOWNLOAD', {'xdg:DOWNLOAD': 'name'}) === 'name');
check('invalid order ignored', sortModeFor('home:x', {'home:x': 'size'}) === 'name');

const items = [
    {name: 'b.txt', isDir: false, modified: 30, type: 'text/plain'},
    {name: 'Photos', isDir: true, modified: 10, type: 'inode/directory'},
    {name: 'a10.png', isDir: false, modified: 50, type: 'image/png'},
    {name: 'A2.png', isDir: false, modified: 20, type: 'image/png'},
];
const names = list => list.map(i => i.name).join(',');
check('name: folders first, numbers by value, case ignored',
    names(sortItems(items, 'name')) === 'Photos,A2.png,a10.png,b.txt');
check('modified: newest first', names(sortItems(items, 'modified')) === 'a10.png,b.txt,A2.png,Photos');
check('type: folders first, then by type', names(sortItems(items, 'type')) ===
    'Photos,A2.png,a10.png,b.txt');
check('input not changed', items[0].name === 'b.txt');

check('desktop entries are launchers', isLauncher('evil.desktop', 'text/plain') &&
    isLauncher('x', 'application/x-desktop') && !isLauncher('notes.txt', 'text/plain'));
check('small images thumbnailed', canThumbnailDirectly('image/png', 1000));
check('large images not', !canThumbnailDirectly('image/png', 50 * 1024 * 1024));
check('other types not', !canThumbnailDirectly('application/pdf', 1000));

const entries = ['a', 'b', 'c'];
check('move down', moveEntry(entries, 'a', 1).join() === 'b,a,c');
check('move up at the start does nothing', moveEntry(entries, 'a', -1).join() === 'a,b,c');
check('move missing does nothing', moveEntry(entries, 'x', 1).join() === 'a,b,c');

// Panel size: 800 px high work area -> at most 400 px for the whole panel.
let h = panelHeights({workHeight: 800, room: 700, chrome: 150, content: 3000});
check('large folder: whole panel at half the work area', h.height === 400 && h.scroll === 250 &&
    h.limit === 400);
h = panelHeights({workHeight: 800, room: 700, chrome: 150, content: 90});
check('small folder: natural size', h.height === 240 && h.scroll === 90);
h = panelHeights({workHeight: 1000, room: 300, chrome: 150, content: 3000});
check('less room beside the dock: smaller still', h.height === 300 && h.limit === 300);
h = panelHeights({workHeight: 568, room: 520, chrome: 150, content: 3000});
check('low resolution: still half the work area', h.height === 284);
h = panelHeights({workHeight: 200, room: 180, chrome: 150, content: 3000});
check('header alone over the limit: contents not negative', h.scroll === 0 && h.height === 150);
check('limit of odd heights rounds down', panelHeights({workHeight: 765, room: 900, chrome: 0,
    content: 9999}).height === 382);

check('columns fitting', columnsThatFit(320, 100, 4) === 3 && columnsThatFit(308, 100, 4) === 3 &&
    columnsThatFit(307, 100, 4) === 2 && columnsThatFit(50, 100, 4) === 1 &&
    columnsThatFit(500, 0, 4) === 1);
check('few items: minimum columns, not a narrow strip', gridColumns(1, 10) === MIN_COLUMNS &&
    gridColumns(0, 10) === MIN_COLUMNS);
check('columns grow with the folder', gridColumns(9, 10) === 4 && gridColumns(16, 10) === 5 &&
    gridColumns(24, 10) === 6);
check('at most MAX_COLUMNS', gridColumns(5000, 20) === MAX_COLUMNS);
check('never more than fit', gridColumns(5000, 2) === 2 && gridColumns(1, 0) === 1);

// Cells of 104 px, 4 px apart, 20 px of padding.
const fit = (roomWidth, limit) => gridFit({roomWidth, limit, frame: 20, cell: 104, spacing: 4});
check('wide room, tall limit: up to the room', fit(1200, 600) === 8);
check('low limit keeps the panel from being a wide strip', fit(1200, 243) === 3);
check('medium limit', fit(1200, 343) === 4 && fit(1200, 500) === 7);
check('narrow room wins', fit(250, 600) === 2);
check('minimum columns even under a very low limit', fit(1200, 50) === MIN_COLUMNS);

check('more items near the end', needsMore({value: 500, pageSize: 300, upper: 1000, shown: 120,
    total: 400}));
check('no more items far from the end', !needsMore({value: 0, pageSize: 300, upper: 2000,
    shown: 120, total: 400}));
check('no more items when all shown', !needsMore({value: 1700, pageSize: 300, upper: 2000,
    shown: 400, total: 400}));

check('clipboard format of Files', COPIED_FILES === 'x-special/gnome-copied-files');
check('copied files', copiedFiles(['file:///a/b%20c', 'file:///d'], false) ===
    'copy\nfile:///a/b%20c\nfile:///d');
check('cut file', copiedFiles(['file:///a'], true) === 'cut\nfile:///a');

if (failures) {
    printerr(`${failures} failed`);
    System.exit(1);
}
