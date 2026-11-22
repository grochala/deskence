// SPDX-License-Identifier: GPL-3.0-or-later
//
// Files dropped on the dock (fileDrop.js): reading the drag data, the
// operation a drop means and the drops that are refused, without GNOME
// Shell imports so they can be tested (tests/unit/test_drop.js).
//
// URIs are compared as given; the caller normalizes them first (Gio.File
// get_uri()), so "a%20b" and "a b" never meet here.

// The drag data asked for. GTK, Qt and the desktop process offer files as
// a URI list; nothing else is read.
export const URI_LIST = 'text/uri-list';
// At most this much drag data is read.
export const MAX_URI_LIST_BYTES = 4 * 1024 * 1024;

// Hovering a folder of the dock this long opens its panel.
export const EXPAND_DELAY = 600;
// The panel opened for a drag closes this long after the pointer left the
// folder icon and the panel (crossing the gap between them is shorter).
export const COLLAPSE_DELAY = 700;

// Whether a drag offers files.
export function offersFiles(mimetypes) {
    return Array.isArray(mimetypes) && mimetypes.includes(URI_LIST);
}

// The URIs of a text/uri-list (RFC 2483): one per line, CRLF or LF, lines
// starting with "#" are comments. Lines that are not absolute URIs are
// dropped, duplicates too.
export function parseUriList(text) {
    if (typeof text !== 'string')
        return [];
    const uris = [];
    for (const raw of text.split('\n')) {
        const line = raw.replace(/\r$/, '').trim();
        if (!line || line.startsWith('#'))
            continue;
        if (!/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(line))
            continue;
        if (!uris.includes(line))
            uris.push(line);
    }
    return uris;
}

// Index of the slash starting the path of a hierarchical URI
// ("file:///a" -> 7, "sftp://host/a" -> 11), or -1.
function pathStart(uri) {
    const scheme = uri.indexOf('://');
    if (scheme < 0)
        return -1;
    return uri.indexOf('/', scheme + 3);
}

// Without a trailing slash, except for the root of the path.
function withoutSlash(uri) {
    const start = pathStart(uri);
    return uri.endsWith('/') && uri.length - 1 > start ? uri.slice(0, -1) : uri;
}

// Whether a URI names a file that Gio (with GVfs) can copy: a scheme it
// supports, but not web links, which a copy would download.
const WEB_SCHEMES = ['http', 'https'];

export function isFileUri(uri, supportedSchemes) {
    const colon = uri.indexOf(':');
    if (colon <= 0)
        return false;
    const scheme = uri.slice(0, colon).toLowerCase();
    return supportedSchemes.includes(scheme) && !WEB_SCHEMES.includes(scheme);
}

// Whether uri is folder itself or anything inside it.
export function isWithin(uri, folder) {
    const a = withoutSlash(uri);
    const b = withoutSlash(folder);
    return a === b || a.startsWith(b.endsWith('/') ? b : `${b}/`);
}

// The folder a URI is in, or null for a root or a URI without a path.
export function parentUri(uri) {
    const clean = withoutSlash(uri);
    const start = pathStart(clean);
    const slash = clean.lastIndexOf('/');
    if (start < 0 || slash < start || clean.length - 1 === start)
        return null;
    return slash === start ? clean.slice(0, start + 1) : clean.slice(0, slash);
}

// Modifiers of a drag the way mutter reads them (meta-wayland-data-device
// data_source_update_user_dnd_action): Shift moves, Ctrl copies, Shift
// winning when both are held. Without either, files move within one file
// system and are copied to another one, as in Files and on the desktop.
// sameFilesystem: whether a source is on the target's file system (null:
// unknown, which copies: a copy never loses anything).
export function transferAction({shift = false, ctrl = false} = {}, sameFilesystem = null) {
    if (shift)
        return 'move';
    if (ctrl)
        return 'copy';
    return sameFilesystem === true ? 'move' : 'copy';
}

// What dropping sources into the folder target does: {copy: [uris],
// move: [uris]}, or {refused: reason} with reason
//   'nothing'      no files
//   'not-files'    something dragged is not a file (a web link)
//   'unavailable'  the folder is missing or not mounted
//   'read-only'    the folder cannot be written to
//   'into-itself'  a dragged folder would go into itself or a subfolder
//   'already-there' all files would move to the folder they are in
// sources: [{uri, isFile, sameFilesystem}]; folder: {uri, available,
// writable}.
export function planTransfer(sources, folder, modifiers = {}) {
    if (!sources?.length)
        return {refused: 'nothing'};
    if (sources.some(s => s.isFile === false))
        return {refused: 'not-files'};
    if (!folder?.available)
        return {refused: 'unavailable'};
    if (folder.writable === false)
        return {refused: 'read-only'};
    if (sources.some(s => isWithin(folder.uri, s.uri)))
        return {refused: 'into-itself'};
    const plan = {copy: [], move: []};
    for (const source of sources) {
        const action = transferAction(modifiers, source.sameFilesystem);
        const parent = parentUri(source.uri);
        // Moving a file to where it is changes nothing.
        if (action === 'move' && parent !== null && withoutSlash(parent) === withoutSlash(folder.uri))
            continue;
        plan[action].push(source.uri);
    }
    if (!plan.copy.length && !plan.move.length)
        return {refused: 'already-there'};
    return plan;
}

// What a plan does as one word for the label: 'copy', 'move' or 'mixed'.
export function planKind(plan) {
    if (plan.refused)
        return null;
    if (plan.copy.length && plan.move.length)
        return 'mixed';
    return plan.move.length ? 'move' : 'copy';
}

// How an application takes dropped files, from its desktop entry:
// 'uris' (%u/%U: any URI), 'files' (%f/%F: only files with a local path)
// or null (it takes none; dropping is refused). The MIME types it lists
// are not checked: many applications open more than they declare, and the
// application decides what it can read.
// app: {supportsUris, supportsFiles}; sources: [{uri, hasPath}].
export function appAccepts(app, sources) {
    if (!app || !sources?.length)
        return null;
    if (app.supportsUris)
        return 'uris';
    if (app.supportsFiles && sources.every(s => s.hasPath))
        return 'files';
    return null;
}

// Scrolling while a drag rests near an end of a list: a step in pixels per
// tick, negative towards the start, faster closer to the edge. pos: pointer
// position along the list's view, length: the view's length, zone: the
// depth of the edge zones, maxStep: the step at the very edge.
export function edgeScrollStep(pos, length, zone, maxStep) {
    if (!(length > 0) || !(zone > 0))
        return 0;
    const depth = Math.min(zone, length / 3);
    if (pos < 0 || pos > length)
        return 0;
    if (pos < depth)
        return -Math.ceil(maxStep * (depth - pos) / depth);
    if (pos > length - depth)
        return Math.ceil(maxStep * (pos - (length - depth)) / depth);
    return 0;
}

// Whether the end of a drag was a drop (the button released) rather than
// a cancel (Escape, the source going away): only a release drops, so an
// unknown ending never changes any file.
export function isDropEnd(eventType, releaseTypes) {
    return eventType !== null && eventType !== undefined && releaseTypes.includes(eventType);
}
