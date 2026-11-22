// SPDX-License-Identifier: GPL-3.0-or-later
//
// Folders in the dock ("stacks"): entries, sorting and limits, without
// GNOME Shell imports so they can be tested (tests/unit/test_stacks.js).
//
// An entry of the folder-stacks setting names a folder by identity, the
// same way presets store it (src/deskence/presets.py):
//   "xdg:DOWNLOAD"          a standard folder (GLib.UserDirectory name)
//   "home:Projects/site"    a folder inside the home folder
//   "file:///srv/shared"    any other folder

// Standard folders that can be added from the settings, in the order
// they are offered.
export const XDG_NAMES = ['DOWNLOAD', 'DOCUMENTS', 'PICTURES', 'MUSIC', 'VIDEOS', 'DESKTOP',
    'PUBLIC_SHARE', 'TEMPLATES'];

// Icons of the standard folders (Adwaita names).
const XDG_ICONS = {
    DOWNLOAD: 'folder-download',
    DOCUMENTS: 'folder-documents',
    PICTURES: 'folder-pictures',
    MUSIC: 'folder-music',
    VIDEOS: 'folder-videos',
    DESKTOP: 'user-desktop',
    PUBLIC_SHARE: 'folder-publicshare',
    TEMPLATES: 'folder-templates',
};

// Folders are read up to MAX_SCANNED entries (in batches of BATCH), so
// sorting by date still finds the newest files in large ones; the rest is
// one click away in Files. The panel builds CHUNK items at a time and adds
// the next ones while it is scrolled towards the end, so a large folder
// neither takes long to open nor fills the Shell with thousands of actors
// nobody scrolls to.
export const MAX_SCANNED = 5000;
export const BATCH = 100;
export const CHUNK = 120;

export const SORT_MODES = ['name', 'modified', 'type'];

// {kind: 'xdg'|'home'|'uri', value} or null for an entry that is not
// valid (including one leaving the home folder).
export function parseEntry(entry) {
    if (typeof entry !== 'string')
        return null;
    if (entry.startsWith('xdg:')) {
        const name = entry.slice(4);
        return XDG_NAMES.includes(name) ? {kind: 'xdg', value: name} : null;
    }
    if (entry.startsWith('home:')) {
        const relative = entry.slice(5);
        if (relative.startsWith('/') || relative.split('/').includes('..'))
            return null;
        return {kind: 'home', value: relative};
    }
    if (entry.startsWith('file:///'))
        return {kind: 'uri', value: entry};
    return null;
}

export function xdgIconName(entry) {
    const parsed = parseEntry(entry);
    return parsed?.kind === 'xdg' ? XDG_ICONS[parsed.value] : null;
}

// Downloads show the newest files first; other folders sort by name.
export function sortModeFor(entry, sorting) {
    const mode = sorting?.[entry];
    if (SORT_MODES.includes(mode))
        return mode;
    return entry === 'xdg:DOWNLOAD' ? 'modified' : 'name';
}

const collator = new Intl.Collator(undefined, {sensitivity: 'accent', numeric: true});

// Items: {name, isDir, modified (seconds), type (content type or
// extension)}. "name" and "type" keep folders first; "modified" puts the
// newest first, folders among the files.
export function sortItems(items, mode) {
    const byName = (a, b) => collator.compare(a.name, b.name);
    const dirsFirst = (a, b) => Number(b.isDir) - Number(a.isDir);
    const sorted = [...items];
    switch (mode) {
    case 'modified':
        sorted.sort((a, b) => (b.modified - a.modified) || byName(a, b));
        break;
    case 'type':
        sorted.sort((a, b) => dirsFirst(a, b) ||
            collator.compare(a.type ?? '', b.type ?? '') || byName(a, b));
        break;
    default:
        sorted.sort((a, b) => dirsFirst(a, b) || byName(a, b));
    }
    return sorted;
}

// Files a click must not run: desktop entries (launchers) are shown in
// Files instead, whatever their permissions.
export function isLauncher(name, contentType) {
    return contentType === 'application/x-desktop' || name.endsWith('.desktop');
}

// Images small enough to be shown as their own thumbnail when the
// thumbnail cache has none (loaded in a thread by St).
export const MAX_IMAGE_THUMBNAIL_BYTES = 8 * 1024 * 1024;
const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp',
    'image/svg+xml'];

export function canThumbnailDirectly(contentType, size) {
    return IMAGE_TYPES.includes(contentType) && size > 0 && size <= MAX_IMAGE_THUMBNAIL_BYTES;
}

// Moves an entry within the list (reordering in the settings).
export function moveEntry(entries, entry, delta) {
    const index = entries.indexOf(entry);
    const target = index + delta;
    if (index < 0 || target < 0 || target >= entries.length)
        return entries;
    const result = [...entries];
    result.splice(index, 1);
    result.splice(target, 0, entry);
    return result;
}

// --- Panel size ---------------------------------------------------------

// The whole panel (header, contents, "Open in Files", padding) takes at
// most this share of the height of the work area of its monitor, and never
// more than the room beside the dock.
export const MAX_HEIGHT_SHARE = 0.5;

// Columns of the grid view: enough for a compact panel, not a narrow tall
// strip, and never more than fit beside the dock.
export const MIN_COLUMNS = 3;
export const MAX_COLUMNS = 6;

// How many cells of width cell, spacing apart, fit into width.
export function columnsThatFit(width, cell, spacing) {
    if (!(cell > 0))
        return 1;
    return Math.max(1, Math.floor((width + spacing) / (cell + spacing)));
}

// The panel is at most this many times as wide as it may be high, so a
// low limit (a small screen) does not make it a wide strip either.
export const MAX_ASPECT = 1.6;

// Columns that fit beside the dock and within MAX_ASPECT of the height
// limit. roomWidth and limit: free width and height limit of the panel;
// frame: its horizontal padding around the cells.
export function gridFit({roomWidth, limit, frame, cell, spacing}) {
    const width = Math.min(roomWidth, limit * MAX_ASPECT) - frame;
    return Math.max(Math.min(MIN_COLUMNS, columnsThatFit(roomWidth - frame, cell, spacing)),
        columnsThatFit(width, cell, spacing));
}

// Columns for count items: they grow with the folder, so that its first
// screen is about as wide as high, between MIN_COLUMNS and MAX_COLUMNS.
export function gridColumns(count, fit) {
    const wanted = Math.min(Math.max(Math.ceil(Math.sqrt(Math.max(count, 0) * 1.5)),
        MIN_COLUMNS), MAX_COLUMNS);
    return Math.max(1, Math.min(wanted, fit));
}

// Heights of the panel. workHeight: height of the work area of the
// monitor; room: free height beside the dock; chrome: everything but the
// contents (header, status, "Open in Files", padding and spacing);
// content: natural height of the contents. The contents get what is left
// under the limit and scroll inside it; a small folder keeps its natural
// size. Returns {limit, scroll (height of the scrolled part), height}.
export function panelHeights({workHeight, room, chrome, content}) {
    const limit = Math.max(0, Math.min(Math.floor(workHeight * MAX_HEIGHT_SHARE), Math.floor(room)));
    const scroll = Math.max(0, Math.min(Math.ceil(content), limit - chrome));
    return {limit, scroll, height: chrome + scroll};
}

// Whether the panel should add the next items: some are left and the end
// of what is shown comes within two pages of the view.
export function needsMore({value, pageSize, upper, shown, total}) {
    return shown < total && value + 2 * pageSize >= upper;
}

// Files copied or cut to the clipboard, the way GNOME applications (Files,
// the Deskence desktop) exchange them as "x-special/gnome-copied-files":
// the operation on the first line, then one URI per line.
export const COPIED_FILES = 'x-special/gnome-copied-files';

export function copiedFiles(uris, cut) {
    return [cut ? 'cut' : 'copy', ...uris].join('\n');
}
