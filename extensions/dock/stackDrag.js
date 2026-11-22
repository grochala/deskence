// SPDX-License-Identifier: GPL-3.0-or-later
//
// Files and folders dragged out of a folder panel (stacks.js), with GNOME
// Shell's own drag and drop: onto another folder in the dock, or onto the
// Deskence desktop. The drag itself changes nothing; a target that accepts
// the drop copies or moves the item through Files (fileDrop.js
// transferFiles: name conflicts, errors, undo), with the same rules as
// files dropped from applications (dropLogic.js planTransfer): Shift moves,
// Ctrl copies, otherwise items move within a file system and are copied
// across file systems; a folder never goes into itself, nothing goes into
// a missing or read-only folder. The source panel follows its folder and
// refreshes by itself, so does the desktop.
//
// Mutter offers GNOME Shell no way to start a Wayland drag, so a drag
// starting in the Shell can only end on Shell actors: windows of other
// applications, such as Files, cannot take it. The desktop is a window,
// but Deskence's own: while such a drag lasts, its window actors get a drop
// delegate, which is removed again however the drag ends.
//
// Drops are only accepted through acceptDrop(): GNOME Shell then ends the
// drag itself (drag-end, its modal grab released). Every end (drop, cancel,
// Escape, the panel closing, the dock turned off) runs one reset that
// releases the monitor, delegates, highlights and reads.

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';

import * as DND from 'resource:///org/gnome/shell/ui/dnd.js';
import {gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

import {Cleanup, parentUri, planTransfer} from './dropLogic.js';
import {planText, queryFolder, transferFiles} from './fileDrop.js';

const DESKTOP_TITLE_TAG = '@deskence-desktop:';

function modifiers() {
    const mask = global.get_pointer()[2];
    return {
        shift: (mask & Clutter.ModifierType.SHIFT_MASK) !== 0,
        ctrl: (mask & Clutter.ModifierType.CONTROL_MASK) !== 0,
    };
}

// The folder the desktop shows, as the desktop process finds it
// (items.py desktop_directory): none when it is the home folder.
function desktopFolder() {
    GLib.reload_user_special_dirs_cache();
    const path = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP);
    if (!path || Gio.File.new_for_path(path).equal(Gio.File.new_for_path(GLib.get_home_dir())))
        return null;
    return Gio.File.new_for_path(path);
}

export class StackDrag {
    constructor(manager) {
        this._manager = manager;
        this._session = null;
    }

    get active() {
        return this._session !== null;
    }

    // An item of a folder panel started to be dragged. source: the
    // delegate of the dragged item ({stackFile}).
    begin(source) {
        this.end();
        const file = source.stackFile;
        const parent = file.get_parent();
        const session = {
            source,
            uri: file.get_uri(),
            parentUri: parentUri(file.get_uri()),
            cancellable: new Gio.Cancellable(),
            infos: new Map(),
            target: null,
            desktop: desktopFolder(),
            desktopActors: [],
            monitor: null,
            cleanup: new Cleanup(),
        };
        this._session = session;
        session.cleanup.add('reads', () => session.cancellable.cancel());

        // What the plans need, read now so it is known when the pointer
        // gets to a target.
        const folders = [parent, session.desktop,
            ...this._manager.stacks.getItems().map(item => item.file)].filter(Boolean);
        for (const folder of folders)
            this._info(session, folder);

        session.monitor = {dragMotion: event => this._onMotion(session, event)};
        DND.addDragMonitor(session.monitor);
        session.cleanup.add('drag monitor', () => DND.removeDragMonitor(session.monitor));
        session.cleanup.add('highlight', () => this._setTarget(session, null));

        if (session.desktop) {
            const delegate = {
                handleDragOver: dragged => this._overDesktop(dragged),
                acceptDrop: dragged => this._dropOnDesktop(dragged),
            };
            for (const actor of global.get_window_actors()) {
                if (!(actor.get_meta_window().get_title() ?? '').includes(DESKTOP_TITLE_TAG) ||
                    actor._delegate)
                    continue;
                actor._delegate = delegate;
                session.cleanup.add('desktop delegate', () => {
                    if (actor._delegate === delegate)
                        delete actor._delegate;
                });
            }
        }
    }

    // However the drag ended; safe to call again.
    end() {
        const session = this._session;
        this._session = null;
        session?.cleanup.run((name, e) => logError(e, `Deskence dock: ending a folder drag (${name})`));
    }

    destroy() {
        this.end();
        this._manager = null;
    }

    _info(session, folder) {
        const uri = folder.get_uri();
        if (!session.infos.has(uri)) {
            session.infos.set(uri, null);
            queryFolder(folder, session.cancellable).then(value => {
                if (!session.cancellable.is_cancelled())
                    session.infos.set(uri, value);
            });
        }
        return session.infos.get(uri);
    }

    // The plan for dropping the dragged item into folder, or null while
    // something is still being read.
    _plan(session, folder) {
        if (!folder)
            return {refused: 'unavailable'};
        const info = this._info(session, folder);
        const parentInfo = session.parentUri ? session.infos.get(session.parentUri) : null;
        if (!info || (session.parentUri && !parentInfo))
            return null;
        const sameFilesystem = Boolean(parentInfo?.filesystem && info.filesystem &&
            parentInfo.filesystem === info.filesystem && session.uri.startsWith('file:'));
        return planTransfer([{uri: session.uri, isFile: true, sameFilesystem}],
            {uri: folder.get_uri(), ...info}, modifiers());
    }

    _result(plan) {
        if (!plan)
            return DND.DragMotionResult.COPY_DROP;
        if (plan.refused)
            return DND.DragMotionResult.NO_DROP;
        return plan.move.length ? DND.DragMotionResult.MOVE_DROP : DND.DragMotionResult.COPY_DROP;
    }

    _onMotion(session, event) {
        // Leaving a highlighted folder icon clears it.
        const target = session.target;
        if (target && !target.icon.contains(event.targetActor))
            this._setTarget(session, null);
        return DND.DragMotionResult.CONTINUE;
    }

    _setTarget(session, target, accepted = true, text = null) {
        const old = session.target;
        if (old && old.icon !== target?.icon && old.icon.get_stage())
            old.dock.setFileDropFeedback(null);
        session.target = target;
        if (target)
            target.dock.setFileDropFeedback(target.icon.get_parent(), accepted, text);
    }

    _isOurs(dragged) {
        const session = this._session;
        return session !== null && dragged === session.source;
    }

    // --- A folder in the dock (StackIcon) -----------------------------

    overStack(dragged, icon, dock) {
        if (!this._isOurs(dragged))
            return DND.DragMotionResult.CONTINUE;
        const session = this._session;
        const plan = this._plan(session, icon.item.file);
        this._setTarget(session, {icon, dock}, !plan?.refused, planText(plan, icon.item.name));
        return this._result(plan);
    }

    dropOnStack(dragged, icon) {
        if (!this._isOurs(dragged))
            return false;
        return this._drop(this._session, icon.item.file, icon.item.name, () => {
            if (icon.get_stage())
                icon.update(icon.item);
        });
    }

    // --- The desktop ----------------------------------------------------

    _overDesktop(dragged) {
        if (!this._isOurs(dragged))
            return DND.DragMotionResult.CONTINUE;
        return this._result(this._plan(this._session, this._session.desktop));
    }

    _dropOnDesktop(dragged) {
        if (!this._isOurs(dragged))
            return false;
        return this._drop(this._session, this._session.desktop, _('Desktop'));
    }

    // Accepts the drop only when everything is known and the plan does
    // something; then the drag is over for GNOME Shell and Files does the
    // work.
    _drop(session, folder, name, done = null) {
        const plan = this._plan(session, folder);
        if (!plan || plan.refused)
            return false;
        if (plan.move.length)
            transferFiles('MoveURIs', plan.move, folder, name, done);
        if (plan.copy.length)
            transferFiles('CopyURIs', plan.copy, folder, name, done);
        return true;
    }
}
