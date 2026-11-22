// SPDX-License-Identifier: GPL-3.0-or-later
// Run with: gjs -m tests/unit/test_clipboard.js
import GLib from 'gi://GLib';
import System from 'system';

import {History, MAX_IMAGE_BYTES, MAX_TEXT_BYTES, MAX_TOTAL_BYTES, isSensitive, matches,
    pickFormat, preview} from '../../extensions/clipboard/history.js';

let failures = 0;
function check(name, condition) {
    if (!condition) {
        failures++;
        printerr(`FAIL: ${name}`);
    } else {
        print(`ok: ${name}`);
    }
}
const texts = h => h.entries.map(e => e.text ?? `[${e.mime}]`).join(',');
const bytes = (size, fill = 1) => new GLib.Bytes(new Uint8Array(size).fill(fill));

// Formats and secrets
check('password managers are not remembered',
    isSensitive(['text/plain', 'x-kde-passwordManagerHint']) &&
    pickFormat(['text/plain', 'x-kde-passwordManagerHint']) === null);
check('text preferred over images', pickFormat(['image/png', 'text/plain;charset=utf-8']).kind === 'text');
check('png preferred among images', pickFormat(['image/jpeg', 'image/png']).mime === 'image/png');
check('unknown formats ignored', pickFormat(['application/x-foo']) === null);

// Duplicates and order
let h = new History(3);
h.addText('a', 1);
h.addText('b', 2);
h.addText('a', 3);
check('copying again moves to the top', texts(h) === 'a,b' && h.entries[0].time === 3);
check('empty text ignored', h.addText('   ') === null && h.entries.length === 2);
h.addText('c');
h.addText('d');
check('count limit drops the oldest', texts(h) === 'd,c,a');

// Pinned entries
h.setPinned(h.entries[2].id, true);
h.addText('e');
h.addText('f');
check('pinned entries stay and do not count', texts(h) === 'f,e,d,a');
h.clear();
check('clearing keeps pinned entries', texts(h) === 'a');
h.remove(h.entries[0].id);
check('removing a pinned entry', h.entries.length === 0);

// Sizes
h = new History(50);
check('too long text is not remembered (not cut)', h.addText('x'.repeat(MAX_TEXT_BYTES + 1)) === null);
check('too large image is not remembered', h.addImage(bytes(MAX_IMAGE_BYTES + 1), 'image/png') === null);
const image = h.addImage(bytes(1000), 'image/png');
check('image remembered', image?.kind === 'image' && image.size === 1000);
check('same image deduplicated', h.addImage(bytes(1000), 'image/png') === image && h.entries.length === 1);
check('different image kept', h.addImage(bytes(1000, 2), 'image/png') !== image && h.entries.length === 2);

// Memory budget
h = new History(200);
const big = Math.floor(MAX_IMAGE_BYTES * 0.9);
const pinned = h.addImage(bytes(big, 9), 'image/png');
h.setPinned(pinned.id, true);
for (let i = 0; i < 12; i++)
    h.addImage(bytes(big, 10 + i), 'image/png');
check('total size stays within the budget', h.totalSize <= MAX_TOTAL_BYTES);
check('pinned survives the budget', h.entries.includes(pinned));
check('newest survives the budget', h.entries[0].bytes.get_data()[0] === 21);

// Stored form
h = new History(10);
h.addText('old');
const kept = h.addText('pinned');
h.setPinned(kept.id, true);
h.addImage(bytes(10, 3), 'image/png');
let stored = h.toStored('nothing');
check('nothing saved by default', stored.index.entries.length === 0 && stored.images.size === 0);
stored = h.toStored('pinned');
check('only pinned saved', stored.index.entries.length === 1 && stored.index.entries[0].text === 'pinned');
stored = h.toStored('all');
check('all saved with image files', stored.index.entries.length === 3 && stored.images.size === 1);
const restored = new History(10);
restored.addText('new');
const count = restored.restore(JSON.parse(JSON.stringify(stored.index)), file => stored.images.get(file));
check('restored after the current entries', count === 3 && restored.entries[0].text === 'new' &&
    restored.entries.length === 4);
check('restored pin state', restored.entries.find(e => e.text === 'pinned').pinned);
check('unknown index ignored', new History(10).restore({version: 99, entries: []}, () => null) === 0);
check('unsafe file names ignored', new History(10).restore({version: 1, entries: [
    {kind: 'image', mime: 'image/png', file: '../../etc/passwd'}]}, () => bytes(5)) === 0);

// Preview and search
check('preview shortened', preview('a'.repeat(500)).length === 401);
check('preview collapses blank lines', preview('a\n\n\n\nb') === 'a\n\nb');
check('search ignores case, also of non-ASCII letters',
    matches({kind: 'text', text: 'Zażółć Gęślą'}, 'gęśl'));
check('images only without a query', !matches({kind: 'image'}, 'x') && matches({kind: 'image'}, ''));

if (failures) {
    printerr(`${failures} failed`);
    System.exit(1);
}
