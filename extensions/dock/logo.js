// SPDX-License-Identifier: GPL-3.0-or-later
//
// The distribution logo of the applications button as a symbolic icon: one
// color, taken from the dock's foreground like every symbolic icon.
//
// A symbolic variant installed by the system ("<logo>-symbolic") is used as
// it is. Otherwise a silhouette is derived from the colored logo (see
// logic.js silhouetteAlpha()), only when the result is a readable sign
// (silhouetteReadable()); a logo that would turn into a blob is shown in
// its own colors instead. The silhouette is fitted to the optical size of
// GNOME's 16 px symbolic icons and stored as "*.symbolic.png" in the cache
// folder: St recolors such files with the icon's CSS color. Black pixels
// with coverage in alpha stand for the foreground color.
//
// Only the built-in distribution logo is converted; a custom image chosen
// by the user is never recolored.

import GdkPixbuf from 'gi://GdkPixbuf';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {silhouetteAlpha, silhouetteReadable} from './logic.js';

const SOURCE_SIZE = 256;
// Largest side of the sign inside the square, like the 11 of 16 pixels most
// GNOME symbolic icons use.
const CONTENT_RATIO = 11 / 16;
const FORMAT_VERSION = 1;

function cacheDirectory() {
    return GLib.build_filenamev([GLib.get_user_cache_dir(), 'deskence']);
}

// Coverage of the logo's pixels and the box around the visible ones.
function readCoverage(pixbuf) {
    const width = pixbuf.get_width();
    const height = pixbuf.get_height();
    const channels = pixbuf.get_n_channels();
    const stride = pixbuf.get_rowstride();
    const pixels = pixbuf.get_pixels();
    const alpha = channels === 4;
    const coverage = new Uint8Array(width * height);
    let x1 = width, y1 = height, x2 = -1, y2 = -1;
    for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
            const o = y * stride + x * channels;
            const value = silhouetteAlpha(pixels[o], pixels[o + 1], pixels[o + 2],
                alpha ? pixels[o + 3] : 255);
            coverage[y * width + x] = value;
            // The box of the logo itself, holes included.
            if ((alpha ? pixels[o + 3] : value) > 16) {
                x1 = Math.min(x1, x);
                y1 = Math.min(y1, y);
                x2 = Math.max(x2, x);
                y2 = Math.max(y2, y);
            }
        }
    }
    return {coverage, width, box: x2 < 0 ? null : {x1, y1, x2, y2}};
}

function writeSilhouette(path, coverage, width, box) {
    const boxWidth = box.x2 - box.x1 + 1;
    const boxHeight = box.y2 - box.y1 + 1;
    const scale = SOURCE_SIZE * CONTENT_RATIO / Math.max(boxWidth, boxHeight);
    const offsetX = (SOURCE_SIZE - boxWidth * scale) / 2;
    const offsetY = (SOURCE_SIZE - boxHeight * scale) / 2;
    const data = new Uint8Array(SOURCE_SIZE * SOURCE_SIZE * 4);
    // Box filter over the source pixels each target pixel covers.
    for (let y = 0; y < SOURCE_SIZE; y++) {
        const sy1 = (y - offsetY) / scale + box.y1;
        const sy2 = (y + 1 - offsetY) / scale + box.y1;
        for (let x = 0; x < SOURCE_SIZE; x++) {
            const sx1 = (x - offsetX) / scale + box.x1;
            const sx2 = (x + 1 - offsetX) / scale + box.x1;
            let sum = 0, count = 0;
            for (let sy = Math.floor(sy1); sy < Math.ceil(sy2); sy++) {
                for (let sx = Math.floor(sx1); sx < Math.ceil(sx2); sx++) {
                    if (sx >= box.x1 && sx <= box.x2 && sy >= box.y1 && sy <= box.y2)
                        sum += coverage[sy * width + sx];
                    count++;
                }
            }
            data[(y * SOURCE_SIZE + x) * 4 + 3] = count ? Math.round(sum / count) : 0;
        }
    }
    const pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(new GLib.Bytes(data),
        GdkPixbuf.Colorspace.RGB, true, 8, SOURCE_SIZE, SOURCE_SIZE, SOURCE_SIZE * 4);
    GLib.mkdir_with_parents(GLib.path_get_dirname(path), 0o700);
    const tmp = `${path}.tmp`;
    pixbuf.savev(tmp, 'png', [], []);
    Gio.File.new_for_path(tmp).move(Gio.File.new_for_path(path),
        Gio.FileCopyFlags.OVERWRITE, null, null);
}

// gicon of the silhouette of the themed icon `name`, or null when the
// logo cannot be read or would not stay recognisable.
export function logoSilhouette(theme, name) {
    const info = theme.lookup_icon(name, SOURCE_SIZE, 0);
    const source = info?.get_filename();
    if (!source)
        return null;
    try {
        const stat = Gio.File.new_for_path(source).query_info('time::modified,standard::size',
            Gio.FileQueryInfoFlags.NONE, null);
        const key = GLib.compute_checksum_for_string(GLib.ChecksumType.SHA256,
            [FORMAT_VERSION, source, stat.get_size(),
                stat.get_attribute_uint64('time::modified')].join('\n'), -1).slice(0, 16);
        const path = GLib.build_filenamev([cacheDirectory(), `apps-button-logo-${key}.symbolic.png`]);
        if (!GLib.file_test(path, GLib.FileTest.EXISTS)) {
            const pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(source, SOURCE_SIZE, SOURCE_SIZE);
            const {coverage, width, box} = readCoverage(pixbuf);
            if (!box)
                return null;
            const inside = [];
            for (let y = box.y1; y <= box.y2; y++) {
                for (let x = box.x1; x <= box.x2; x++)
                    inside.push(coverage[y * width + x]);
            }
            if (!silhouetteReadable(inside)) {
                console.log(`Deskence Dock: ${name} has no readable single color form, ` +
                    'showing it in color');
                return null;
            }
            writeSilhouette(path, coverage, width, box);
        }
        return new Gio.FileIcon({file: Gio.File.new_for_path(path)});
    } catch (e) {
        console.warn(`Deskence Dock: cannot derive a symbolic logo from ${source}: ${e.message}`);
        return null;
    }
}
