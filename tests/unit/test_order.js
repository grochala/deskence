// SPDX-License-Identifier: GPL-3.0-or-later
// Run with: gjs -m tests/unit/test_order.js
import System from 'system';

import {pageLayout, sameLayout, sameList, sortIds} from '../../extensions/app-grid/order.js';

let failures = 0;
function check(name, condition) {
    if (!condition) {
        failures++;
        printerr(`FAIL: ${name}`);
    } else {
        print(`ok: ${name}`);
    }
}

const names = {
    'zoom.desktop': 'Zoom',
    'a.desktop': 'archive',
    'b.desktop': 'Błękit',
    'c.desktop': 'Calc',
    'l.desktop': 'Łódź',
    'e.desktop': 'Editor 10',
    'f.desktop': 'Editor 2',
    'g.desktop': 'calc',
};
const name = id => names[id] ?? null;

const sorted = sortIds(Object.keys(names), name);
const position = id => sorted.indexOf(id);
check('case is ignored', position('a.desktop') < position('b.desktop') &&
    position('b.desktop') < position('c.desktop'));
check('numbers by value', position('f.desktop') < position('e.desktop'));
check('equal names keep a stable order', position('c.desktop') < position('g.desktop'));
check('nothing lost', sorted.length === Object.keys(names).length);
check('stable on repeat', sameList(sortIds(sorted, name), sorted));
check('missing applications kept at the end',
    sameList(sortIds(['gone.desktop', 'zoom.desktop', 'a.desktop'], name),
        ['a.desktop', 'zoom.desktop', 'gone.desktop']));
check('duplicates removed', sameList(sortIds(['a.desktop', 'a.desktop'], name), ['a.desktop']));
// Polish letters in the user's language: "Ł" after "L" in a Polish
// locale; at least it never comes before "A".
check('accented names are not first', position('l.desktop') > position('a.desktop'));

const pages = pageLayout(['a', 'b', 'c', 'd', 'e'], 2);
check('pages of the grid size', pages.length === 3 && pages[0].a === 0 && pages[0].b === 1 &&
    pages[1].c === 0 && pages[2].e === 0);
check('same layout', sameLayout(pages, pageLayout(['a', 'b', 'c', 'd', 'e'], 2)));
check('different order', !sameLayout(pages, pageLayout(['b', 'a', 'c', 'd', 'e'], 2)));
check('different pages', !sameLayout(pages, pageLayout(['a', 'b', 'c', 'd', 'e'], 3)));
check('empty layout', sameLayout([], pageLayout([], 24)));

if (failures) {
    printerr(`${failures} failed`);
    System.exit(1);
}
