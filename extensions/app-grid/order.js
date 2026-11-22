// SPDX-License-Identifier: GPL-3.0-or-later
//
// Alphabetical order, without GNOME Shell imports so it can be tested
// (tests/unit/test_order.js).

// Display names in the user's language, ignoring case; numbers in names
// are compared by value ("Item 2" before "Item 10"). Equal names keep a
// stable order by ID.
const collator = new Intl.Collator(undefined, {sensitivity: 'accent', numeric: true});

export function compareNames(a, b) {
    return collator.compare(a.name, b.name) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
}

// IDs sorted by their display names; name(id) gives the name, or null for
// an ID that is not installed (kept at the end, in its order, so nothing
// is lost while an application is being reinstalled).
export function sortIds(ids, name) {
    const unique = [...new Set(ids)];
    const known = unique.filter(id => name(id) !== null)
        .map(id => ({id, name: name(id)}))
        .sort(compareNames)
        .map(item => item.id);
    return known.concat(unique.filter(id => name(id) === null));
}

export function sameList(a, b) {
    return a.length === b.length && a.every((item, i) => item === b[i]);
}

// Pages of app-picker-layout for IDs in order: perPage items on each page,
// as [{id: position}].
export function pageLayout(ids, perPage) {
    const size = Math.max(1, perPage);
    const pages = [];
    ids.forEach((id, index) => {
        const page = Math.floor(index / size);
        pages[page] ??= {};
        pages[page][id] = index % size;
    });
    return pages;
}

export function sameLayout(a, b) {
    return a.length === b.length && a.every((page, i) => {
        const keys = Object.keys(page);
        return keys.length === Object.keys(b[i]).length &&
            keys.every(id => b[i][id] === page[id]);
    });
}
