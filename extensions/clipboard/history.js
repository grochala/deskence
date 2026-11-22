// SPDX-License-Identifier: GPL-3.0-or-later
//
// The clipboard history as data: entries, duplicates, limits and the
// stored form. No GNOME Shell imports, so it can be tested
// (tests/unit/test_clipboard.js).
//
// An entry is {id, kind: 'text'|'image', text, mime, bytes (GLib.Bytes of
// an image), size, hash, pinned, time}. The newest entry comes first.
//
// Limits: at most maxEntries entries that are not pinned; text up to
// MAX_TEXT_BYTES and images up to MAX_IMAGE_BYTES (larger ones are not
// remembered at all, never cut); all entries together, pinned included, up
// to MAX_TOTAL_BYTES, the oldest unpinned ones going first. Copying the
// same text or image again moves the existing entry to the top.

import GLib from 'gi://GLib';

export const MAX_TEXT_BYTES = 1024 * 1024;
export const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
export const MAX_TOTAL_BYTES = 64 * 1024 * 1024;
// Applications mark secrets (password managers) with this MIME type.
export const SENSITIVE_MIME_TYPES = ['x-kde-passwordManagerHint'];
// Image formats taken from the clipboard, in order of preference.
export const IMAGE_MIME_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif',
    'image/bmp'];
export const TEXT_MIME_TYPES = ['text/plain;charset=utf-8', 'UTF8_STRING', 'text/plain',
    'STRING', 'TEXT'];
export const FORMAT_VERSION = 1;

const encoder = new TextEncoder();

export function isSensitive(mimeTypes) {
    return mimeTypes.some(m => SENSITIVE_MIME_TYPES.includes(m));
}

// What to read from an offer: {kind: 'image', mime} or {kind: 'text'} or
// null. Text wins over images when both are offered (a copied file name,
// a spreadsheet range): it is what Ctrl+V usually pastes.
export function pickFormat(mimeTypes) {
    if (isSensitive(mimeTypes))
        return null;
    if (mimeTypes.some(m => TEXT_MIME_TYPES.includes(m) || m.startsWith('text/plain')))
        return {kind: 'text'};
    const image = IMAGE_MIME_TYPES.find(m => mimeTypes.includes(m));
    return image ? {kind: 'image', mime: image} : null;
}

export function textSize(text) {
    return encoder.encode(text).length;
}

export function hashText(text) {
    return GLib.compute_checksum_for_string(GLib.ChecksumType.SHA256, text, -1);
}

export function hashBytes(bytes) {
    return GLib.compute_checksum_for_bytes(GLib.ChecksumType.SHA256, bytes);
}

// A short, single-paragraph preview of a text for a tile.
export function preview(text, length = 400) {
    const trimmed = text.replace(/\r\n?/g, '\n').replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
    return trimmed.length > length ? `${trimmed.slice(0, length)}…` : trimmed;
}

// Case-insensitive search in texts; images match a search for nothing
// but their kind (empty query).
export function matches(entry, query) {
    if (!query)
        return true;
    return entry.kind === 'text' && entry.text.toLocaleLowerCase().includes(query.toLocaleLowerCase());
}

let lastId = 0;

export class History {
    constructor(maxEntries) {
        this.maxEntries = maxEntries;
        this.entries = [];
    }

    get totalSize() {
        return this.entries.reduce((sum, e) => sum + e.size, 0);
    }

    find(id) {
        return this.entries.find(e => e.id === id) ?? null;
    }

    // Adds text; returns the entry (an existing one moved to the top for
    // the same text) or null when the text is empty or too large.
    addText(text, time = Date.now()) {
        if (!text || !text.trim())
            return null;
        const size = textSize(text);
        if (size > MAX_TEXT_BYTES)
            return null;
        return this._add({kind: 'text', text, size, hash: hashText(text)}, time);
    }

    // Adds an image (GLib.Bytes in the given format).
    addImage(bytes, mime, time = Date.now()) {
        const size = bytes?.get_size() ?? 0;
        if (size === 0 || size > MAX_IMAGE_BYTES)
            return null;
        return this._add({kind: 'image', bytes, mime, size, hash: hashBytes(bytes)}, time);
    }

    _add(data, time) {
        const existing = this.entries.find(e => e.kind === data.kind && e.hash === data.hash);
        if (existing) {
            this.entries.splice(this.entries.indexOf(existing), 1);
            existing.time = time;
            this.entries.unshift(existing);
            return existing;
        }
        const entry = {id: ++lastId, pinned: false, time, ...data};
        this.entries.unshift(entry);
        this.enforceLimits();
        return this.entries.includes(entry) ? entry : null;
    }

    // Unpinned entries beyond the count, then the oldest unpinned ones
    // while everything together is too large.
    enforceLimits() {
        let unpinned = 0;
        this.entries = this.entries.filter(e => e.pinned || ++unpinned <= this.maxEntries);
        let total = this.totalSize;
        for (let i = this.entries.length - 1; i >= 0 && total > MAX_TOTAL_BYTES; i--) {
            const entry = this.entries[i];
            if (entry.pinned)
                continue;
            total -= entry.size;
            this.entries.splice(i, 1);
        }
    }

    setMaxEntries(maxEntries) {
        this.maxEntries = maxEntries;
        this.enforceLimits();
    }

    setPinned(id, pinned) {
        const entry = this.find(id);
        if (entry)
            entry.pinned = pinned;
        this.enforceLimits();
        return entry;
    }

    remove(id) {
        this.entries = this.entries.filter(e => e.id !== id);
    }

    // Clearing keeps pinned entries.
    clear() {
        this.entries = this.entries.filter(e => e.pinned);
    }

    // --- Stored form ----------------------------------------------------

    // The entries to save for a "remember" setting ("nothing", "pinned",
    // "all"), as {index, images}: index is JSON-ready (texts inline,
    // images by file name), images maps a file name to its bytes.
    toStored(remember) {
        const kept = remember === 'all' ? this.entries
            : remember === 'pinned' ? this.entries.filter(e => e.pinned) : [];
        const images = new Map();
        const entries = kept.map(e => {
            const base = {kind: e.kind, pinned: e.pinned, time: e.time};
            if (e.kind === 'text')
                return {...base, text: e.text};
            const file = `image-${e.hash.slice(0, 32)}.${extensionFor(e.mime)}`;
            images.set(file, e.bytes);
            return {...base, mime: e.mime, file};
        });
        return {index: {version: FORMAT_VERSION, entries}, images};
    }

    // Adds stored entries after the current ones (entries of this session
    // are newer); loadImage(file) returns GLib.Bytes or null.
    restore(index, loadImage) {
        if (index?.version !== FORMAT_VERSION || !Array.isArray(index.entries))
            return 0;
        let count = 0;
        for (const stored of index.entries) {
            let data = null;
            if (stored?.kind === 'text' && typeof stored.text === 'string' &&
                textSize(stored.text) <= MAX_TEXT_BYTES) {
                data = {kind: 'text', text: stored.text, size: textSize(stored.text),
                    hash: hashText(stored.text)};
            } else if (stored?.kind === 'image' && IMAGE_MIME_TYPES.includes(stored.mime) &&
                       /^image-[0-9a-f]{32}\.[a-z]+$/.test(stored.file ?? '')) {
                const bytes = loadImage(stored.file);
                if (bytes && bytes.get_size() <= MAX_IMAGE_BYTES)
                    data = {kind: 'image', bytes, mime: stored.mime, size: bytes.get_size(),
                        hash: hashBytes(bytes)};
            }
            if (!data || this.entries.some(e => e.kind === data.kind && e.hash === data.hash))
                continue;
            this.entries.push({id: ++lastId, pinned: Boolean(stored.pinned),
                time: Number(stored.time) || 0, ...data});
            count++;
        }
        this.enforceLimits();
        return count;
    }
}

export function extensionFor(mime) {
    return {
        'image/png': 'png',
        'image/jpeg': 'jpg',
        'image/webp': 'webp',
        'image/gif': 'gif',
        'image/bmp': 'bmp',
    }[mime] ?? 'bin';
}
