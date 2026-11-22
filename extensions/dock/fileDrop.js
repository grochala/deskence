// SPDX-License-Identifier: GPL-3.0-or-later
//
// Files dragged onto the dock from Files, the desktop or other applications:
// dropped on an application they open in it, dropped on a folder ("stack")
// they are copied or moved into it. Pinning and reordering applications are
// a different kind of drag (GNOME Shell's DND, dock.js) and never pass here.
//
// Files come from Wayland clients. GNOME Shell sees such a drag only through
// mutter (Main.xdndHandler): its position, and its end, which is either a
// drop or a cancel. Over the Shell's own actors there is no Wayland surface
// to drop on, so mutter cancels the drag at the source: the application
// never moves or deletes anything because of a drop on the dock. What was
// dragged is read during the drag from the DND selection (text/uri-list,
// Meta.Selection), as soon as the pointer comes near a target; the drop is
// the drag ending with a button release (an Escape or a vanished source
// ends it otherwise, and nothing happens).
//
// - Applications: Gio.DesktopAppInfo.launch_uris_async() with the Shell's
//   launch context, the same for running and stopped applications; the
//   desktop entry decides (%u/%U any URIs, %f/%F local files, neither: the
//   drop is refused). No command line is built from file names.
// - Folders: Files (org.gnome.Nautilus.FileOperations2 CopyURIs/MoveURIs),
//   like the desktop (desktop-icons/deskence_desktop/fileops.py): progress,
//   name conflicts, permissions, errors and undo are those of Files. Without
//   Files nothing is copied; there is no second implementation here, and no
//   file operation runs in the Shell. Shift moves, Ctrl copies; otherwise
//   files move within a file system and are copied across file systems.
//   Drops that cannot work (a missing or read-only folder, a folder into
//   itself, links) are refused while hovering. Only the folder's own
//   information is read, asynchronously.
//
// Hovering a folder opens its panel (stacks.js) without a grab: a Shell grab
// would take the pointer from the Wayland drag. Its subfolders are targets
// too, files in it are not (dropping there means the folder itself). Near
// the ends of its contents the panel scrolls. Wheel events go to the drag
// while it lasts, so the wheel cannot scroll.
//
// During a file drag the icons keep their normal size (like during
// GNOME Shell drags), so targets do not move under the pointer.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Meta from 'gi://Meta';

import * as DND from 'resource:///org/gnome/shell/ui/dnd.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

import {COLLAPSE_DELAY, EXPAND_DELAY, MAX_URI_LIST_BYTES, URI_LIST, appAccepts, isDropEnd,
    isFileUri, offersFiles, parentUri, parseUriList, planKind, planTransfer} from './dropLogic.js';

const NAUTILUS_NAME = 'org.gnome.Nautilus';
const NAUTILUS_PATH = '/org/gnome/Nautilus/FileOperations2';
const NAUTILUS_IFACE = 'org.gnome.Nautilus.FileOperations2';
const MISSING_SERVICE_ERRORS = [
    'org.freedesktop.DBus.Error.ServiceUnknown',
    'org.freedesktop.DBus.Error.NameHasNoOwner',
    'org.freedesktop.DBus.Error.UnknownMethod',
    'org.freedesktop.DBus.Error.Spawn.ServiceNotFound',
];
// Modifier keys change copy and move without moving the pointer.
const MODIFIER_POLL = 150;
const FOLDER_ATTRIBUTES = 'standard::type,access::can-write,id::filesystem';

function isMissingService(error) {
    return Gio.DBusError.is_remote_error(error) &&
        MISSING_SERVICE_ERRORS.includes(Gio.DBusError.get_remote_error(error));
}

function modifiersOf(mask) {
    return {
        shift: (mask & Clutter.ModifierType.SHIFT_MASK) !== 0,
        ctrl: (mask & Clutter.ModifierType.CONTROL_MASK) !== 0,
    };
}

// {available, writable, filesystem} of a folder, read asynchronously.
function queryFolder(file, cancellable) {
    return new Promise(resolve => {
        file.query_info_async(FOLDER_ATTRIBUTES, Gio.FileQueryInfoFlags.NONE,
            GLib.PRIORITY_DEFAULT, cancellable, (_f, res) => {
                let value = {available: false, writable: null, filesystem: null};
                try {
                    const info = file.query_info_finish(res);
                    value = {
                        available: info.get_file_type() === Gio.FileType.DIRECTORY,
                        writable: info.has_attribute('access::can-write')
                            ? info.get_attribute_boolean('access::can-write') : null,
                        filesystem: info.get_attribute_string('id::filesystem'),
                    };
                } catch {
                    // Missing, unmounted or not readable: not available.
                }
                resolve(value);
            });
    });
}

function displayName(file) {
    return GLib.filename_display_basename(file.get_path() ?? file.get_uri());
}

export class FileDrop {
    constructor(manager) {
        this._manager = manager;
        this._active = false;
        this._monitor = null;
        this._uris = null;
        this._urisPromise = null;
        this._cancellable = null;
        // Folder URI -> Promise of {available, writable, filesystem}; the
        // settled values are in _infoValues.
        this._infos = new Map();
        this._infoValues = new Map();
        this._target = null;
        this._lastPoint = null;
        // Drops waiting for what they need (cancelled on disable).
        this._drops = new Set();
        this._modifiers = {shift: false, ctrl: false};
        this._expandId = 0;
        this._collapseId = 0;
        this._modifierId = 0;
        Main.xdndHandler.connectObject(
            'drag-begin', () => this._begin(),
            'drag-end', () => this._end(), this);
    }

    // --- The drag ---------------------------------------------------------

    _begin() {
        this._reset();
        const types = global.display.get_selection().get_mimetypes(Meta.SelectionType.SELECTION_DND);
        if (!offersFiles(types))
            return;
        this._active = true;
        this._cancellable = new Gio.Cancellable();
        this._monitor = {dragMotion: event => this._onMotion(event)};
        DND.addDragMonitor(this._monitor);
        this._manager.fileDragBegin();
    }

    _onMotion(event) {
        if (this._active) {
            this._lastPoint = [event.x, event.y];
            this._update(event.x, event.y, event.targetActor);
        }
        return DND.DragMotionResult.CONTINUE;
    }

    // Something moved under a resting pointer (scrolling, a refreshed
    // panel): find the target again. force: the old one is gone.
    repick(force = false) {
        if (!this._active || !this._lastPoint)
            return;
        if (force) {
            this._clearHighlight();
            this._target = null;
        }
        const [x, y] = this._lastPoint;
        this._update(x, y, global.stage.get_actor_at_pos(Clutter.PickMode.REACTIVE, x, y));
    }

    _update(x, y, actor) {
        const manager = this._manager;
        manager.docks.forEach(d => d.fileDragAt(x, y, actor));
        const panel = manager.stackPanel;
        if (panel.isOpenForDrag) {
            panel.dragScrollAt(x, y);
            const keep = panel.contains(actor) || Boolean(actor && panel.icon?.contains(actor));
            if (keep) {
                this._clearTimeout('_collapseId');
            } else {
                this._collapseId ||= GLib.timeout_add(GLib.PRIORITY_DEFAULT, COLLAPSE_DELAY, () => {
                    this._collapseId = 0;
                    if (this._target?.kind === 'folder')
                        this._setTarget(null);
                    this._manager.stackPanel.close();
                    return GLib.SOURCE_REMOVE;
                });
            }
        }
        this._setTarget(this._targetAt(actor));
    }

    // {kind: 'app', key, icon, item, dock}, {kind: 'stack', key, icon, item,
    // dock, file, name} or {kind: 'folder', key, file, name, button} for
    // the panel, or null.
    _targetAt(actor) {
        if (!actor)
            return null;
        const panel = this._manager.stackPanel;
        if (panel.isOpenForDrag && panel.contains(actor)) {
            const folder = panel.dropTargetAt(actor);
            return folder ? {kind: 'folder', key: `folder:${folder.file?.get_uri()}`, ...folder} : null;
        }
        for (const dock of this._manager.docks) {
            const target = dock.fileDropTarget(actor);
            if (target)
                return target;
        }
        return null;
    }

    _setTarget(target) {
        if (target?.key === this._target?.key) {
            if (target)
                this._refresh();
            return;
        }
        this._clearHighlight();
        this._clearTimeout('_expandId');
        this._target = target;
        if (!target) {
            this._stopModifiers();
            return;
        }
        this._readUris();
        const folder = this._folderOf(target);
        if (folder) {
            this._folderInfo(folder);
            this._modifiers = modifiersOf(global.get_pointer()[2]);
            this._modifierId ||= GLib.timeout_add(GLib.PRIORITY_DEFAULT, MODIFIER_POLL, () => {
                const modifiers = modifiersOf(global.get_pointer()[2]);
                if (modifiers.shift !== this._modifiers.shift || modifiers.ctrl !== this._modifiers.ctrl) {
                    this._modifiers = modifiers;
                    this._refresh();
                }
                return GLib.SOURCE_CONTINUE;
            });
        } else {
            this._stopModifiers();
        }
        const panel = this._manager.stackPanel;
        if (target.kind === 'stack' && !(panel.isOpenForDrag && panel.icon === target.icon)) {
            this._expandId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, EXPAND_DELAY, () => {
                this._expandId = 0;
                if (this._target === target && target.icon.get_stage()) {
                    this._clearHighlight();
                    panel.openForDrag(target.icon, target.dock);
                    this._refresh();
                }
                return GLib.SOURCE_REMOVE;
            });
        }
        this._refresh();
    }

    _folderOf(target) {
        if (target?.kind === 'stack' || target?.kind === 'folder')
            return target.file ?? null;
        return null;
    }

    _stopModifiers() {
        this._clearTimeout('_modifierId');
    }

    _clearTimeout(name) {
        if (this[name])
            GLib.source_remove(this[name]);
        this[name] = 0;
    }

    // --- What is dragged and where it would go -----------------------------

    _readUris() {
        if (this._urisPromise)
            return;
        const cancellable = this._cancellable;
        this._urisPromise = new Promise(resolve => {
            const stream = Gio.MemoryOutputStream.new_resizable();
            global.display.get_selection().transfer_async(Meta.SelectionType.SELECTION_DND,
                URI_LIST, MAX_URI_LIST_BYTES, stream, cancellable, (selection, res) => {
                    let uris = [];
                    try {
                        selection.transfer_finish(res);
                        stream.close(null);
                        const bytes = stream.steal_as_bytes();
                        uris = parseUriList(new TextDecoder().decode(bytes.toArray()))
                            .map(uri => Gio.File.new_for_uri(uri).get_uri());
                    } catch (e) {
                        if (!e.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                            console.warn(`Deskence dock: cannot read the dragged files: ${e.message}`);
                    }
                    resolve(uris);
                });
        });
        this._urisPromise.then(uris => {
            if (cancellable !== this._cancellable)
                return;
            this._uris = uris;
            // The source folders' file systems decide between copy and move.
            for (const parent of new Set(uris.map(parentUri).filter(Boolean)))
                this._folderInfo(Gio.File.new_for_uri(parent));
            this._refresh();
        });
    }

    _folderInfo(file) {
        const uri = file.get_uri();
        let promise = this._infos.get(uri);
        if (promise)
            return promise;
        const cancellable = this._cancellable;
        promise = queryFolder(file, cancellable);
        this._infos.set(uri, promise);
        const values = this._infoValues;
        promise.then(value => {
            if (cancellable !== this._cancellable)
                return;
            values.set(uri, value);
            this._refresh();
        });
        return promise;
    }

    // The plan for dropping into folder with the information known now;
    // null while something is still being read.
    _plan(folder, uris, modifiers, values = this._infoValues) {
        if (!folder)
            return {refused: 'unavailable'};
        const info = values.get(folder.get_uri());
        if (!info || uris === null)
            return null;
        const schemes = Gio.Vfs.get_default().get_supported_uri_schemes();
        const sources = uris.map(uri => {
            const parent = parentUri(uri);
            const parentFs = parent ? values.get(parent)?.filesystem : null;
            return {
                uri,
                isFile: isFileUri(uri, schemes),
                sameFilesystem: uri.startsWith('file:') && parentFs && info.filesystem
                    ? parentFs === info.filesystem : false,
            };
        });
        return planTransfer(sources, {uri: folder.get_uri(), ...info}, modifiers);
    }

    _appAccepts(app, uris) {
        const info = app.get_app_info();
        return appAccepts(info ? {
            supportsUris: info.supports_uris(),
            supportsFiles: info.supports_files(),
        } : null, uris.map(uri => ({uri, hasPath: uri.startsWith('file:')})));
    }

    // --- Showing the target ------------------------------------------------

    // Whether target takes the drop with what is known now (null: still
    // reading), and the text telling what a drop does.
    _verdict(target, modifiers) {
        if (target.kind === 'app') {
            const name = target.icon.app.get_name();
            const accepted = this._uris === null ? null
                : this._appAccepts(target.icon.app, this._uris) !== null;
            return [accepted, accepted === false
                ? _('%s cannot open files').replace('%s', name)
                : _('Open with %s').replace('%s', name)];
        }
        const plan = this._plan(this._folderOf(target), this._uris, modifiers);
        return [plan ? !plan.refused : null, this._planText(plan, target.name)];
    }

    _refresh() {
        const target = this._target;
        if (!target)
            return;
        const panel = this._manager.stackPanel;
        const [accepted, text] = this._verdict(target, this._modifiers);
        const inPanel = panel.isOpenForDrag && (target.kind === 'folder' || panel.icon === target.icon);
        if (target.kind === 'folder') {
            panel.setDropHighlight(target.button, accepted !== false);
        } else if (!inPanel) {
            target.dock.setFileDropFeedback(target.item, accepted !== false, text);
        }
        if (inPanel)
            panel.setDropHint(text, accepted !== false);
    }

    _planText(plan, name) {
        if (!plan)
            return name;
        switch (plan.refused) {
        case undefined:
            break;
        case 'unavailable':
            return _('%s is not available').replace('%s', name);
        case 'read-only':
            return _('%s is read-only').replace('%s', name);
        case 'into-itself':
            return _('A folder cannot be put into itself');
        case 'already-there':
            return _('Already in %s').replace('%s', name);
        case 'not-files':
            return _('Only files can be put into a folder');
        default:
            return name;
        }
        return {
            move: _('Move to %s'),
            copy: _('Copy to %s'),
            mixed: _('Move or copy to %s'),
        }[planKind(plan)].replace('%s', name);
    }

    _clearHighlight() {
        const target = this._target;
        if (!target)
            return;
        if (target.kind === 'folder')
            this._manager.stackPanel.setDropHighlight(null);
        else
            target.dock.setFileDropFeedback(null);
        this._manager.stackPanel.setDropHint(null);
    }

    // --- The end -----------------------------------------------------------

    _end() {
        if (!this._active)
            return;
        const event = Clutter.get_current_event();
        const drop = isDropEnd(event?.type() ?? null,
            [Clutter.EventType.BUTTON_RELEASE, Clutter.EventType.TOUCH_END]);
        let target = null;
        let modifiers = this._modifiers;
        let time = global.get_current_time();
        if (drop) {
            const [x, y] = event.get_coords();
            target = this._targetAt(global.stage.get_actor_at_pos(Clutter.PickMode.REACTIVE, x, y));
            modifiers = modifiersOf(event.get_state());
            time = event.get_time();
        }
        // A drop the target refuses is a failed drop: the drag image
        // slides back to where it came from. Otherwise it just goes away.
        if (target && this._urisPromise && this._verdict(target, modifiers)[0] === false)
            target = null;
        const urisPromise = this._urisPromise;
        const cancellable = this._cancellable;
        const infos = this._infos;
        if (target && urisPromise)
            this._hideDragImage();
        this._reset(false);
        if (target && urisPromise) {
            this._drops.add(cancellable);
            this._drop(target, urisPromise, infos, modifiers, time, cancellable)
                .catch(e => logError(e, 'Deskence dock: drop failed'))
                .finally(() => this._drops?.delete(cancellable));
        } else {
            cancellable?.cancel();
        }
    }

    _hideDragImage() {
        const group = global.compositor?.get_feedback_group?.();
        for (const child of group?.get_children() ?? []) {
            if (GObject.type_name_from_instance(child) === 'MetaDnDActor')
                child.hide();
        }
    }

    async _drop(target, urisPromise, infos, modifiers, time, cancellable) {
        const uris = await urisPromise;
        if (cancellable.is_cancelled() || !uris.length)
            return;
        if (target.kind === 'app') {
            this._open(target.icon, uris, time);
            return;
        }
        // Everything the plan needs, including what was still being read.
        const folder = this._folderOf(target);
        const values = new Map();
        if (folder) {
            const files = [folder, ...new Set(uris.map(parentUri).filter(Boolean))]
                .map(uri => typeof uri === 'string' ? Gio.File.new_for_uri(uri) : uri);
            for (const file of files) {
                const uri = file.get_uri();
                values.set(uri, await (infos.get(uri) ?? queryFolder(file, cancellable)));
            }
        }
        if (cancellable.is_cancelled() || !this._manager)
            return;
        const plan = this._plan(folder, uris, modifiers, values);
        if (!plan || plan.refused)
            return;
        if (plan.move.length)
            this._transfer('MoveURIs', plan.move, folder, target);
        if (plan.copy.length)
            this._transfer('CopyURIs', plan.copy, folder, target);
    }

    _open(icon, uris, time) {
        const app = icon.app;
        const info = app.get_app_info();
        if (!info || this._appAccepts(app, uris) === null)
            return;
        icon.animateLaunch?.();
        info.launch_uris_async(uris, global.create_app_launch_context(time, -1), null, (_i, res) => {
            try {
                info.launch_uris_finish(res);
            } catch (e) {
                Main.notifyError(_('Cannot open the files in %s').replace('%s', app.get_name()),
                    e.message);
            }
        });
        Main.overview.hide();
    }

    _transfer(method, uris, folder, target) {
        const move = method === 'MoveURIs';
        const platformData = {'window-position': new GLib.Variant('s', 'center')};
        Gio.DBus.session.call(NAUTILUS_NAME, NAUTILUS_PATH, NAUTILUS_IFACE, method,
            new GLib.Variant('(assa{sv})', [uris, folder.get_uri(), platformData]),
            null, Gio.DBusCallFlags.NONE, GLib.MAXINT32, null, (bus, res) => {
                try {
                    bus.call_finish(res);
                } catch (e) {
                    const title = move ? _('Cannot move the files to %s') : _('Cannot copy the files to %s');
                    Main.notifyError(title.replace('%s', target.name ?? displayName(folder)),
                        isMissingService(e)
                            ? _('Copying and moving files from the dock needs the Files application.')
                            : e.message);
                }
                // Whether the folder is still there (the panel and the
                // desktop follow their folders by themselves).
                if (target.kind === 'stack' && target.icon.get_stage())
                    target.icon.update(target.icon.item);
            });
    }

    // --- Cleaning up -------------------------------------------------------

    // Ends the drag handling. cancelReads: also cancels what is being read
    // (not when a drop still needs it).
    _reset(cancelReads = true) {
        this._clearHighlight();
        this._target = null;
        this._lastPoint = null;
        for (const name of ['_expandId', '_collapseId', '_modifierId'])
            this._clearTimeout(name);
        if (this._monitor)
            DND.removeDragMonitor(this._monitor);
        this._monitor = null;
        if (cancelReads)
            this._cancellable?.cancel();
        this._cancellable = null;
        this._uris = null;
        this._urisPromise = null;
        this._infos = new Map();
        this._infoValues = new Map();
        const wasActive = this._active;
        this._active = false;
        if (wasActive)
            this._manager.fileDragEnd();
    }

    // The docks are rebuilt during a drag: forget the targets.
    cancel() {
        if (this._active)
            this._reset();
    }

    destroy() {
        this._reset();
        this._drops.forEach(c => c.cancel());
        this._drops = null;
        Main.xdndHandler.disconnectObject(this);
        this._manager = null;
    }
}
