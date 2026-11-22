// SPDX-License-Identifier: GPL-3.0-or-later
//
// Pure helpers for com.canonical.dbusmenu layouts and StatusNotifierItem
// pixmaps. No GNOME Shell imports, so they are unit tested with plain gjs.

const MAX_DEPTH = 8;
const MAX_ITEMS = 500;
const MAX_PIXMAP_SIDE = 1024;

// "_Open" -> "Open", "Save __as" -> "Save _as".
export function stripMnemonic(label) {
    return String(label ?? '').replace(/__|_/g, m => (m === '__' ? '_' : ''));
}

function unpack(value) {
    if (value && typeof value.deepUnpack === 'function')
        return value.deepUnpack();
    return value;
}

// Converts an unpacked GetLayout node [id, props, children] into a plain
// object tree, ignoring malformed entries. Applications send all kinds of
// data, so every field is validated.
export function parseNode(node, depth = 0, counter = {count: 0}) {
    if (!Array.isArray(node) || node.length < 3)
        return null;
    if (++counter.count > MAX_ITEMS)
        return null;
    const [id, rawProps, rawChildren] = node;
    if (!Number.isInteger(id))
        return null;
    const props = {};
    for (const [key, value] of Object.entries(rawProps ?? {}))
        props[key] = unpack(value);

    const type = props['type'] === 'separator' ? 'separator' : 'standard';
    const toggleType = ['checkmark', 'radio'].includes(props['toggle-type'])
        ? props['toggle-type'] : '';
    const result = {
        id,
        type,
        label: stripMnemonic(props['label']),
        enabled: props['enabled'] !== false,
        visible: props['visible'] !== false,
        iconName: typeof props['icon-name'] === 'string' ? props['icon-name'] : '',
        iconData: props['icon-data'] instanceof Uint8Array ? props['icon-data'] : null,
        toggleType,
        toggleState: Number.isInteger(props['toggle-state']) ? props['toggle-state'] : -1,
        isSubmenu: props['children-display'] === 'submenu',
        children: [],
    };

    if (depth < MAX_DEPTH && Array.isArray(rawChildren)) {
        for (const child of rawChildren) {
            const parsed = parseNode(unpack(child), depth + 1, counter);
            if (parsed)
                result.children.push(parsed);
        }
    }
    if (result.children.length > 0)
        result.isSubmenu = true;
    return result;
}

// Drops invisible items and collapses separators at the start, the end and
// next to each other, as menus in GNOME do not show those.
export function visibleChildren(node) {
    const items = node.children.filter(c => c.visible);
    const result = [];
    for (const item of items) {
        if (item.type === 'separator' &&
            (result.length === 0 || result[result.length - 1].type === 'separator'))
            continue;
        result.push(item);
    }
    while (result.length && result[result.length - 1].type === 'separator')
        result.pop();
    return result;
}

// Picks the pixmap closest to the wanted size (preferring larger ones) and
// converts it from ARGB32 in network byte order to RGBA bytes.
// pixmaps: array of [width, height, Uint8Array]. Returns null when no
// pixmap is usable.
export function choosePixmap(pixmaps, wanted) {
    if (!Array.isArray(pixmaps))
        return null;
    const valid = pixmaps.filter(p => Array.isArray(p) && p.length === 3 &&
        Number.isInteger(p[0]) && Number.isInteger(p[1]) &&
        p[0] > 0 && p[1] > 0 && p[0] <= MAX_PIXMAP_SIDE && p[1] <= MAX_PIXMAP_SIDE &&
        p[2] && p[2].length === p[0] * p[1] * 4);
    if (valid.length === 0)
        return null;
    valid.sort((a, b) => {
        const da = a[0] >= wanted ? a[0] - wanted : (wanted - a[0]) * 4;
        const db = b[0] >= wanted ? b[0] - wanted : (wanted - b[0]) * 4;
        return da - db;
    });
    const [width, height, argb] = valid[0];
    const rgba = new Uint8Array(argb.length);
    for (let i = 0; i < argb.length; i += 4) {
        rgba[i] = argb[i + 1];
        rgba[i + 1] = argb[i + 2];
        rgba[i + 2] = argb[i + 3];
        rgba[i + 3] = argb[i];
    }
    return {width, height, rgba};
}

// Splits what applications pass to RegisterStatusNotifierItem into the bus
// name and object path of the item. Some pass a bus name, others (for
// example libappindicator) an object path on their own connection.
export function parseItemService(service, sender) {
    if (typeof service !== 'string' || service.length === 0)
        return null;
    if (service.startsWith('/'))
        return {busName: sender, objectPath: service};
    const slash = service.indexOf('/');
    if (slash > 0)
        return {busName: service.slice(0, slash), objectPath: service.slice(slash)};
    return {busName: service, objectPath: '/StatusNotifierItem'};
}
