// SPDX-License-Identifier: GPL-3.0-or-later
//
// Keeping the clipboard history between sessions, only when the user asked
// for it (the "remember" setting): pinned entries or all of them are saved
// in $XDG_DATA_HOME/deskence/clipboard/ (a folder only the user can read),
// texts in history.json, images as files next to it. With "nothing" (the
// default) the files there are deleted. Everything is asynchronous; contents are
// never logged.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

const SAVE_DELAY = 2000;

export class HistoryStorage {
    constructor() {
        this._folder = Gio.File.new_for_path(
            GLib.build_filenamev([GLib.get_user_data_dir(), 'deskence', 'clipboard']));
        this._saveId = 0;
        this._cancellable = new Gio.Cancellable();
        this._pending = null;
    }

    // Reads the saved history; callback(index, loadImage) or nothing when
    // there is none.
    load(callback) {
        const file = this._folder.get_child('history.json');
        file.load_contents_async(this._cancellable, (_f, res) => {
            let index;
            try {
                const [, contents] = file.load_contents_finish(res);
                index = JSON.parse(new TextDecoder().decode(contents));
            } catch (e) {
                if (!e.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.NOT_FOUND) &&
                    !e.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                    console.warn('Deskence: the saved clipboard history cannot be read');
                return;
            }
            // Images are small and few; read when restoring.
            const loadImage = name => {
                try {
                    const [, data] = this._folder.get_child(name).load_contents(null);
                    return new GLib.Bytes(data);
                } catch {
                    return null;
                }
            };
            callback(index, loadImage);
        });
    }

    // Saves soon; later calls replace the pending state.
    queueSave(stored) {
        this._pending = stored;
        if (this._saveId)
            return;
        this._saveId = GLib.timeout_add(GLib.PRIORITY_LOW, SAVE_DELAY, () => {
            this._saveId = 0;
            this._write(this._pending);
            this._pending = null;
            return GLib.SOURCE_REMOVE;
        });
    }

    _write(stored) {
        if (!stored)
            return;
        try {
            this._folder.make_directory_with_parents(null);
        } catch (e) {
            if (!e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.EXISTS)) {
                console.warn(`Deskence: cannot save the clipboard history: ${e.message}`);
                return;
            }
        }
        // Only the user can read the folder.
        GLib.chmod(this._folder.get_path(), 0o700);
        for (const [name, bytes] of stored.images) {
            const file = this._folder.get_child(name);
            file.replace_contents_bytes_async(bytes, null, false,
                Gio.FileCreateFlags.PRIVATE | Gio.FileCreateFlags.REPLACE_DESTINATION,
                this._cancellable, (_f, res) => {
                    try {
                        file.replace_contents_finish(res);
                    } catch {
                        console.warn('Deskence: cannot save an image of the clipboard history');
                    }
                });
        }
        const index = new GLib.Bytes(new TextEncoder().encode(JSON.stringify(stored.index)));
        const file = this._folder.get_child('history.json');
        file.replace_contents_bytes_async(index, null, false,
            Gio.FileCreateFlags.PRIVATE | Gio.FileCreateFlags.REPLACE_DESTINATION,
            this._cancellable, (_f, res) => {
                try {
                    file.replace_contents_finish(res);
                } catch {
                    console.warn('Deskence: cannot save the clipboard history');
                }
                this._removeUnused(new Set(['history.json', ...stored.images.keys()]));
            });
    }

    // Images of entries that are gone.
    _removeUnused(keep) {
        this._folder.enumerate_children_async('standard::name', Gio.FileQueryInfoFlags.NONE,
            GLib.PRIORITY_LOW, this._cancellable, (_f, res) => {
                let enumerator;
                try {
                    enumerator = this._folder.enumerate_children_finish(res);
                } catch {
                    return;
                }
                enumerator.next_files_async(1000, GLib.PRIORITY_LOW, this._cancellable, (_e, r) => {
                    try {
                        for (const info of enumerator.next_files_finish(r)) {
                            if (!keep.has(info.get_name()))
                                this._folder.get_child(info.get_name()).delete_async(GLib.PRIORITY_LOW, null, null);
                        }
                    } catch {
                        // Nothing to clean up.
                    }
                    enumerator.close_async(GLib.PRIORITY_LOW, null, null);
                });
            });
    }

    // Removes everything saved ("remember" is "nothing").
    erase() {
        if (this._saveId)
            GLib.source_remove(this._saveId);
        this._saveId = 0;
        this._pending = null;
        this._removeUnused(new Set());
    }

    // Writes what is pending at once (turning the feature off).
    flush() {
        if (this._saveId) {
            GLib.source_remove(this._saveId);
            this._saveId = 0;
            this._write(this._pending);
            this._pending = null;
        }
    }

    destroy() {
        this.flush();
        this._cancellable = null;
    }
}
