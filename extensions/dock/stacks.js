// SPDX-License-Identifier: GPL-3.0-or-later
//
// Folders in the dock ("stacks").
//
// A folder pinned to the dock (folder-stacks setting, see stackLogic.js)
// opens a panel with its contents instead of the file manager: a grid or a
// list, sorted by name, date (newest first; the default for Downloads) or
// type, with subfolders to step into and back out of, and "Open in Files"
// always at the bottom. Files open in their default application; desktop
// entries (launchers) are never run from here, they are shown in Files.
//
// Everything that touches the disk is asynchronous: folders are read in
// batches (Gio enumerators), at most MAX_SCANNED entries; icons and
// thumbnails (from the thumbnail cache, or small images themselves) are
// loaded by St in its threads. The panel shows CHUNK items and adds more
// while it is scrolled towards the end. A folder monitor refreshes the
// panel after changes, keeping the scroll position. A folder that is
// missing or cannot be read says so; the dock item stays, dimmed.
//
// The whole panel is at most half as tall as the work area of its monitor
// (less when the dock leaves less room) and only the contents scroll; the
// header and "Open in Files" stay in place. The grid gets more columns for
// larger folders so the panel stays compact; long names are shortened and
// shown in full in a tooltip. Stepping back out of a subfolder returns to
// the earlier scroll position.
//
// Removing a folder from the dock removes the entry only; nothing on the
// disk is ever changed here.
//
// The panel opens on the side of the dock facing the inside of the screen,
// on the dock's monitor, and holds a grab like a menu: a click outside or
// Escape closes it. The dock stays shown and stops magnifying while it is
// open (Dock.setMenuOpen).
//
// Its files and folders can be dragged onto another folder in the dock or
// onto the desktop (stackDrag.js); while one is dragged, or its menu is
// open, the contents are not rebuilt, so the drag or menu keeps its item.
// Applications such as Files cannot take a drag from GNOME Shell, so an
// item can also be copied or cut to the clipboard (its menu: right click,
// the Menu key, Shift+F10; or Ctrl+C, Ctrl+X) and pasted there. Nothing is
// changed on the disk until it is pasted; pasting is the work of Files or
// the desktop.
//
// Files dragged onto the folder open the panel without a grab, which would
// take the pointer from the drag (fileDrop.js). It then shows what a drop
// does instead of the sorting buttons, highlights the subfolder a drop
// would go into, scrolls while the pointer rests near an end of the
// contents and closes when the drag ends.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Pango from 'gi://Pango';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as DND from 'resource:///org/gnome/shell/ui/dnd.js';
import * as GrabHelper from 'resource:///org/gnome/shell/ui/grabHelper.js';
import * as IconGrid from 'resource:///org/gnome/shell/ui/iconGrid.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {EventEmitter} from 'resource:///org/gnome/shell/misc/signals.js';
import {gettext as _, ngettext} from 'resource:///org/gnome/shell/extensions/extension.js';

import {setVertical} from './appIcon.js';
import {edgeScrollStep} from './dropLogic.js';
import {BATCH, CHUNK, COPIED_FILES, MAX_SCANNED, canThumbnailDirectly, copiedFiles, gridColumns, gridFit, isLauncher, needsMore, panelHeights, parseEntry, sortItems, sortModeFor, xdgIconName}
    from './stackLogic.js';

const ATTRIBUTES = [
    'standard::name', 'standard::display-name', 'standard::type', 'standard::icon',
    'standard::content-type', 'standard::size', 'standard::is-hidden', 'standard::is-backup',
    'time::modified', 'thumbnail::path', 'thumbnail::is-valid',
].join(',');
const RELOAD_DELAY = 300;
const TOOLTIP_DELAY = 600;
const GAP = 8;
const LIST_WIDTH = 420;
const GRID_ICON = 48;
const LIST_ICON = 24;
const ITEM_WIDTH = 96;
const GRID_SPACING = 4;
// Scrolling while a drag rests near an end of the contents: the depth of
// the edge zones and the largest step per tick, in logical pixels.
const DRAG_SCROLL_ZONE = 40;
const DRAG_SCROLL_STEP = 12;
const DRAG_SCROLL_INTERVAL = 16;

function launchContext() {
    return global.create_app_launch_context(0, -1);
}

export function openInFiles(file, select = null) {
    // Showing an item selects it in its folder; opening a folder opens it.
    if (select) {
        Gio.DBus.session.call('org.freedesktop.FileManager1', '/org/freedesktop/FileManager1',
            'org.freedesktop.FileManager1', 'ShowItems',
            new GLib.Variant('(ass)', [[select.get_uri()], '']), null,
            Gio.DBusCallFlags.NONE, -1, null, (bus, res) => {
                try {
                    bus.call_finish(res);
                } catch {
                    openInFiles(file);
                }
            });
        return;
    }
    Gio.AppInfo.launch_default_for_uri_async(file.get_uri(), launchContext(), null, (_o, res) => {
        try {
            Gio.AppInfo.launch_default_for_uri_finish(res);
        } catch (e) {
            Main.notifyError(_('Could not open location'), e.message);
        }
    });
}

// The folders of the folder-stacks setting, resolved on this computer.
export class StacksModel extends EventEmitter {
    constructor(settings) {
        super();
        this._settings = settings;
        this._settings.connectObject(
            'changed::folder-stacks', () => this.emit('changed'),
            'changed::show-folder-stacks', () => this.emit('changed'), this);
    }

    getItems() {
        if (!this._settings.get_boolean('show-folder-stacks'))
            return [];
        GLib.reload_user_special_dirs_cache();
        const home = GLib.get_home_dir();
        const items = [];
        for (const entry of new Set(this._settings.get_strv('folder-stacks'))) {
            const parsed = parseEntry(entry);
            if (!parsed)
                continue;
            let file = null;
            if (parsed.kind === 'xdg') {
                const path = GLib.get_user_special_dir(GLib.UserDirectory[`DIRECTORY_${parsed.value}`]);
                // An unset standard folder points at the home folder.
                if (path && path !== home)
                    file = Gio.File.new_for_path(path);
            } else if (parsed.kind === 'home') {
                file = Gio.File.new_for_path(GLib.build_filenamev([home, parsed.value]));
            } else {
                file = Gio.File.new_for_uri(parsed.value);
            }
            const name = file ? GLib.filename_display_basename(file.get_path() ?? file.get_uri())
                : parsed.value;
            items.push({id: `stack:${entry}`, entry, file, name, iconName: xdgIconName(entry)});
        }
        return items;
    }

    sortMode(entry) {
        return sortModeFor(entry, this._settings.get_value('folder-stack-sorting').deepUnpack());
    }

    setSortMode(entry, mode) {
        const sorting = this._settings.get_value('folder-stack-sorting').deepUnpack();
        sorting[entry] = mode;
        this._settings.set_value('folder-stack-sorting', new GLib.Variant('a{ss}', sorting));
    }

    get view() {
        return this._settings.get_string('folder-stack-view');
    }

    set view(view) {
        this._settings.set_string('folder-stack-view', view);
    }

    // Removes the dock entry only; the folder is not touched.
    remove(entry) {
        const entries = this._settings.get_strv('folder-stacks').filter(e => e !== entry);
        this._settings.set_strv('folder-stacks', entries);
        const sorting = this._settings.get_value('folder-stack-sorting').deepUnpack();
        if (entry in sorting) {
            delete sorting[entry];
            this._settings.set_value('folder-stack-sorting', new GLib.Variant('a{ss}', sorting));
        }
    }

    destroy() {
        this._settings.disconnectObject(this);
        this.disconnectAll();
    }
}

// A triangle filling the area, its tip towards the inside of the screen,
// with rounded corners so it matches the round dots.
function drawMarker(area, side) {
    const cr = area.get_context();
    const [width, height] = area.get_surface_size();
    const color = area.get_theme_node().get_foreground_color();
    const round = Math.min(width, height) / 4;
    const points = {
        bottom: [[round, height - round], [width / 2, round], [width - round, height - round]],
        left: [[round, round], [width - round, height / 2], [round, height - round]],
        right: [[width - round, round], [round, height / 2], [width - round, height - round]],
    }[side];
    cr.setSourceRGBA(color.red / 255, color.green / 255, color.blue / 255, color.alpha / 255);
    cr.setLineJoin(1); // Cairo.LineJoin.ROUND
    cr.setLineWidth(2 * round);
    cr.moveTo(...points[0]);
    cr.lineTo(...points[1]);
    cr.lineTo(...points[2]);
    cr.closePath();
    cr.strokePreserve();
    cr.fill();
    cr.$dispose();
}

// The dock item of a folder: its icon, dimmed while the folder is not
// available, and a small arrow telling it opens a panel (applications have
// window dots there instead).
export const StackIcon = GObject.registerClass({
    GTypeName: 'DeskenceDockStackIcon',
}, class StackIcon extends St.Button {
    _init(item, dock) {
        super._init({
            style_class: 'overview-tile deskence-dock-stack',
            reactive: true,
            can_focus: true,
            track_hover: true,
            button_mask: (St.ButtonMask.PRIMARY ?? St.ButtonMask.ONE) |
                (St.ButtonMask.SECONDARY ?? St.ButtonMask.THREE),
        });
        this._dock = dock;
        this._gicon = null;
        this._available = true;
        // A drop target for items dragged out of a folder panel.
        this._delegate = this;
        this._cancellable = null;
        this.icon = new IconGrid.BaseIcon(item.name, {
            setSizeManually: true,
            showLabel: false,
            createIcon: size => new St.Icon({
                gicon: this._gicon ?? new Gio.ThemedIcon({name: 'folder'}),
                fallback_icon_name: 'folder',
                icon_size: this._dock.iconRenderSize(size),
                width: size,
                height: size,
                opacity: this._available ? 255 : 110,
            }),
        });
        const layout = new St.Widget({layout_manager: new Clutter.BinLayout()});
        layout.add_child(this.icon);
        // Where running applications have their dots: a small solid
        // triangle as thick as a dot (stylesheet.css), pointing into the
        // screen where the panel opens, in the color of the dots.
        this._marker = new St.DrawingArea({
            style_class: `deskence-dock-stack-marker deskence-dock-stack-marker-${dock.position}`,
            x_expand: true,
            y_expand: true,
        });
        this._marker.connect('repaint', area => drawMarker(area, dock.position));
        this._alignMarker();
        layout.add_child(this._marker);
        this.set_child(layout);
        this._menu = null;
        this._menuManager = new PopupMenu.PopupMenuManager(this);
        this.connect('popup-menu', () => this.popupMenu());
        this.connect('destroy', () => {
            this._cancellable?.cancel();
            this._menu?.destroy();
        });
        this.update(item);
    }

    // Where window dots are for applications: under the icon in a bottom
    // dock, on the inner side in a side dock.
    _alignMarker() {
        const side = this._dock.position;
        if (side === 'bottom') {
            this._marker.x_align = Clutter.ActorAlign.CENTER;
            this._marker.y_align = Clutter.ActorAlign.END;
        } else {
            this._marker.x_align = side === 'left' ? Clutter.ActorAlign.END : Clutter.ActorAlign.START;
            this._marker.y_align = Clutter.ActorAlign.CENTER;
        }
    }

    get item() {
        return this._item;
    }

    get available() {
        return this._available;
    }

    update(item) {
        this._item = item;
        this.accessible_name = _('Folder %s').replace('%s', item.name);
        this._gicon = item.iconName ? new Gio.ThemedIcon({name: item.iconName}) : null;
        this.icon.setIconSize(this._dock.iconSize);
        this._refreshIcon();
        this._queryFolder();
    }

    _refreshIcon() {
        // BaseIcon only recreates its icon on size changes.
        this.icon._createIconTexture?.(this._dock.iconSize);
    }

    // Whether the folder exists and is readable, and its own icon.
    _queryFolder() {
        this._cancellable?.cancel();
        const file = this._item.file;
        if (!file) {
            this._setAvailable(false);
            return;
        }
        const cancellable = new Gio.Cancellable();
        this._cancellable = cancellable;
        file.query_info_async('standard::type,standard::icon,access::can-read',
            Gio.FileQueryInfoFlags.NONE, GLib.PRIORITY_LOW, cancellable, (_f, res) => {
                let available = false;
                try {
                    const info = file.query_info_finish(res);
                    available = info.get_file_type() === Gio.FileType.DIRECTORY &&
                        (!info.has_attribute('access::can-read') ||
                         info.get_attribute_boolean('access::can-read'));
                    if (!this._item.iconName && info.get_icon())
                        this._gicon = info.get_icon();
                } catch (e) {
                    if (e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                        return;
                }
                if (this._cancellable === cancellable)
                    this._cancellable = null;
                this._setAvailable(available);
            });
    }

    _setAvailable(available) {
        this._available = available;
        this._refreshIcon();
        this.remove_style_pseudo_class('insensitive');
        if (!available)
            this.add_style_pseudo_class('insensitive');
    }

    updateIconRendering() {
        this.icon.update();
    }

    // Items dragged out of a folder panel (stackDrag.js); other drags go
    // on to the dock.
    handleDragOver(source) {
        return this._dock.manager.stackDrag.overStack(source, this, this._dock);
    }

    acceptDrop(source) {
        return this._dock.manager.stackDrag.dropOnStack(source, this);
    }

    vfunc_clicked(button) {
        if (button === Clutter.BUTTON_SECONDARY) {
            this.popupMenu();
            return;
        }
        this._dock.manager.stackPanel.toggle(this, this._dock);
    }

    popupMenu() {
        this._dock.manager.stackPanel.close();
        this._menu?.destroy();
        this._menu = new PopupMenu.PopupMenu(this, 0.5, this._dock.menuSide);
        Main.uiGroup.add_child(this._menu.actor);
        this._menuManager.addMenu(this._menu);
        const item = this._item;
        const open = this._menu.addAction(_('Open in Files'), () => {
            if (item.file)
                openInFiles(item.file);
            Main.overview.hide();
        });
        open.setSensitive(this._available);
        this._menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._menu.addAction(_('Remove From Dock'),
            () => this._dock.manager.stacks.remove(item.entry));
        this._menu.connect('open-state-changed', (_m, isOpen) => {
            this._dock.setMenuOpen(this, isOpen);
            if (isOpen)
                this.add_style_pseudo_class('active');
            else
                this.remove_style_pseudo_class('active');
        });
        this._menu.open();
        this._menu.actor.navigate_focus(null, St.DirectionType.TAB_FORWARD, false);
    }
});

// The contents panel; one per dock manager.
export class StackPanel {
    constructor(manager) {
        this._manager = manager;
        this._panel = null;
        this._icon = null;
        this._dock = null;
        // The folders stepped into, each with the view to come back to:
        // {file, scroll, shown, focus (name of the focused item)}.
        this._trail = [];
        this._cancellable = null;
        this._monitor = null;
        this._reloadId = 0;
        this._moreId = 0;
        this._tooltipId = 0;
        this._restoreId = 0;
        this._grabHelper = null;
        this._items = [];
        this._sorted = [];
        this._shown = 0;
        this._tooltip = null;
        this._quietFocus = false;
        this._cell = ITEM_WIDTH;
        this._columns = 1;
        // Opened for files dragged onto the folder (fileDrop.js).
        this._forDrag = false;
        this._dragPoint = null;
        this._dragScrollId = 0;
        this._dropButton = null;
        this._hint = null;
        // An item being dragged out, and a refresh waiting for its end.
        this._itemDrag = false;
        this._reloadWanted = false;
        // The menu of an item (copy, cut).
        this._itemMenu = null;
        this._itemMenuManager = null;
    }

    get isOpen() {
        return this._panel !== null;
    }

    get isOpenForDrag() {
        return this._panel !== null && this._forDrag;
    }

    get icon() {
        return this._icon;
    }

    contains(actor) {
        return Boolean(actor && this._panel?.contains(actor));
    }

    isOpenFor(dock) {
        return this._panel !== null && this._dock === dock;
    }

    toggle(icon, dock) {
        if (this._icon === icon) {
            this.close();
            return;
        }
        this.open(icon, dock);
    }

    open(icon, dock, forDrag = false) {
        this.close();
        const item = icon.item;
        this._icon = icon;
        this._dock = dock;
        this._trail = item.file ? [this._view(item.file)] : [];
        this._manager.previews.close();

        this._panel = new St.BoxLayout({
            style_class: 'popup-menu-content deskence-stack-panel',
            reactive: true,
            accessible_name: _('Folder %s').replace('%s', item.name),
        });
        setVertical(this._panel, true);
        this._panel.connect('key-press-event', (_a, event) => this._onKeyPress(event));

        // Header: back, the folder name.
        const header = new St.BoxLayout({style_class: 'deskence-stack-header'});
        this._back = new St.Button({
            style_class: 'deskence-stack-header-button',
            child: new St.Icon({icon_name: 'go-previous-symbolic', icon_size: 16}),
            accessible_name: _('Back'),
            can_focus: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._back.connect('clicked', () => this._goBack());
        this._title = new St.Label({
            style_class: 'deskence-stack-title',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._title.clutter_text.ellipsize = Pango.EllipsizeMode.MIDDLE;
        header.add_child(this._back);
        header.add_child(this._title);
        this._panel.add_child(header);

        // Sorting and the view, as buttons in the panel (no nested menus).
        const tools = new St.BoxLayout({style_class: 'deskence-stack-tools'});
        this._sortButtons = {};
        for (const [mode, label] of [['name', _('Name')], ['modified', _('Date')],
            ['type', _('Type')]]) {
            const button = new St.Button({
                style_class: 'deskence-stack-sort',
                label,
                toggle_mode: true,
                can_focus: true,
                accessible_name: _('Sort by %s').replace('%s', label),
            });
            button.connect('clicked', () => this._setSort(mode));
            this._sortButtons[mode] = button;
            tools.add_child(button);
        }
        tools.add_child(new St.Widget({x_expand: true}));
        this._viewButton = new St.Button({
            style_class: 'deskence-stack-header-button',
            child: new St.Icon({icon_size: 16}),
            can_focus: true,
        });
        this._viewButton.connect('clicked', () => {
            const stacks = this._manager.stacks;
            stacks.view = stacks.view === 'list' ? 'grid' : 'list';
            this._resetView();
            this._syncTools();
            this._render();
        });
        tools.add_child(this._viewButton);
        this._panel.add_child(tools);

        // What a drop does, in place of the tools while files are dragged.
        this._hint = new St.Label({
            style_class: 'deskence-stack-drop-hint',
            text: item.name,
            visible: false,
        });
        this._hint.clutter_text.ellipsize = Pango.EllipsizeMode.END;
        this._panel.add_child(this._hint);

        this._status = new St.Label({style_class: 'deskence-stack-status', visible: false});
        this._status.clutter_text.line_wrap = true;
        this._panel.add_child(this._status);

        // Only the contents scroll; their height is set in _place().
        this._scroll = new St.ScrollView({
            style_class: 'deskence-stack-scroll',
            hscrollbar_policy: St.PolicyType.NEVER,
            vscrollbar_policy: St.PolicyType.AUTOMATIC,
            overlay_scrollbars: true,
            x_expand: true,
        });
        this._content = new St.Viewport({style_class: 'deskence-stack-content'});
        this._scroll.set_child(this._content);
        this._scroll.vadjustment.connect('notify::value', () => {
            this._hideTooltip();
            this._queueMore();
        });
        this._scroll.vadjustment.connect('changed', () => this._queueMore());
        this._panel.add_child(this._scroll);

        // Always there, whatever state the folder is in.
        const open = new St.Button({
            style_class: 'popup-menu-item deskence-stack-open',
            can_focus: true,
            accessible_name: _('Open in Files'),
        });
        const openBox = new St.BoxLayout({style_class: 'deskence-stack-open-box'});
        openBox.add_child(new St.Icon({icon_name: 'folder-open-symbolic', style_class: 'popup-menu-icon'}));
        openBox.add_child(new St.Label({text: _('Open in Files'), y_align: Clutter.ActorAlign.CENTER}));
        open.set_child(openBox);
        open.connect('clicked', () => {
            const folder = this._current;
            this.close();
            if (folder)
                openInFiles(folder);
            Main.overview.hide();
        });
        this._panel.add_child(open);

        Main.layoutManager.addTopChrome(this._panel);
        this._cell = this._measureCell();
        // The full name of a shortened one, above the panel.
        this._tooltip = new St.Label({style_class: 'dash-label deskence-stack-tooltip', visible: false});
        Main.layoutManager.addTopChrome(this._tooltip);
        dock.setMenuOpen(icon, true);
        icon.add_style_pseudo_class('active');
        if (forDrag) {
            this._forDrag = true;
            tools.hide();
            this._hint.show();
        } else {
            this._grabHelper = new GrabHelper.GrabHelper(this._panel, {actionMode: Shell.ActionMode.POPUP});
            const panel = this._panel;
            this._grabHelper.grab({actor: panel, focus: open, onUngrab: () => this._onUngrab(panel)});
        }
        this._load();
        return true;
    }

    openForDrag(icon, dock) {
        return this.open(icon, dock, true);
    }

    closeForDrag() {
        if (this._forDrag)
            this.close();
    }

    // --- Files dragged onto the folder (fileDrop.js) ------------------

    // Where files dropped on actor go: a subfolder shown in the panel, or
    // otherwise (the background, a file, the header) the folder of the
    // stack: {file, name, button (the subfolder's item or null)}, or null
    // outside the panel.
    dropTargetAt(actor) {
        if (!this.contains(actor))
            return null;
        const button = this._content.get_children().find(c => c.contains(actor));
        const item = button?._stackItem;
        if (item?.isDir && this._current)
            return {file: this._current.get_child(item.info.get_name()), name: item.name, button};
        return {file: this._trail[0]?.file ?? null, name: this._icon.item.name, button: null};
    }

    // Highlights the subfolder a drop goes into, like a hovered item; only
    // when it takes the files.
    setDropHighlight(button, accepted = true) {
        if (this._dropButton && this._dropButton !== button)
            this._dropButton.remove_style_class_name('deskence-drop-target');
        this._dropButton = button;
        if (button && accepted)
            button.add_style_class_name('deskence-drop-target');
        else
            button?.remove_style_class_name('deskence-drop-target');
    }

    // What a drop does; null: the folder's name.
    setDropHint(text, accepted = true) {
        if (!this._hint)
            return;
        this._hint.text = text ?? this._icon.item.name;
        if (accepted || text === null)
            this._hint.remove_style_class_name('deskence-stack-drop-hint-refused');
        else
            this._hint.add_style_class_name('deskence-stack-drop-hint-refused');
    }

    // The drag is at stage point x, y: near an end of the contents they
    // scroll, faster closer to the edge, until the pointer moves away.
    dragScrollAt(x, y) {
        this._dragPoint = [x, y];
        if (this._dragScrollStep() === 0)
            return;
        this._dragScrollId ||= GLib.timeout_add(GLib.PRIORITY_DEFAULT, DRAG_SCROLL_INTERVAL, () => {
            const step = this._dragScrollStep();
            if (step === 0) {
                this._dragScrollId = 0;
                return GLib.SOURCE_REMOVE;
            }
            const adjustment = this._scroll.vadjustment;
            const value = Math.clamp(adjustment.value + step, 0,
                Math.max(0, adjustment.upper - adjustment.page_size));
            if (value !== adjustment.value) {
                adjustment.value = value;
                // Other items are under the pointer now.
                this._manager.fileDrop?.repick();
            }
            return GLib.SOURCE_CONTINUE;
        });
    }

    _dragScrollStep() {
        if (!this._panel || !this._dragPoint)
            return 0;
        const [ok, x, y] = this._scroll.transform_stage_point(...this._dragPoint);
        if (!ok || x < 0 || x > this._scroll.width)
            return 0;
        return edgeScrollStep(y, this._scroll.height, DRAG_SCROLL_ZONE, DRAG_SCROLL_STEP);
    }

    // Width of a grid cell, from the style of an empty one.
    _measureCell() {
        const probe = new St.Button({
            style_class: 'popup-menu-item deskence-stack-item',
            child: new St.Widget({width: ITEM_WIDTH}),
        });
        this._content.add_child(probe);
        const [, width] = probe.get_preferred_width(-1);
        probe.destroy();
        return Math.max(width, ITEM_WIDTH);
    }

    _view(file) {
        return {file, scroll: 0, shown: 0, focus: null};
    }

    get _current() {
        return this._trail.at(-1)?.file ?? null;
    }

    get _entry() {
        return this._icon?.item.entry;
    }

    // Remembers where the current folder is scrolled to and what has the
    // focus, to come back to after a subfolder or a refresh.
    _saveView() {
        const view = this._trail.at(-1);
        if (!view || !this._panel)
            return;
        view.scroll = this._scroll.vadjustment.value;
        view.shown = this._shown;
        const focus = global.stage.key_focus;
        view.focus = focus && this._content.contains(focus)
            ? this._content.get_children().find(c => c.contains(focus))?._stackName ?? null
            : null;
    }

    _resetView() {
        const view = this._trail.at(-1);
        if (view)
            Object.assign(view, this._view(view.file));
    }

    _syncTools() {
        const mode = this._manager.stacks.sortMode(this._entry);
        for (const [m, button] of Object.entries(this._sortButtons))
            button.checked = m === mode;
        const list = this._manager.stacks.view === 'list';
        this._viewButton.child.icon_name = list ? 'view-grid-symbolic' : 'view-list-symbolic';
        this._viewButton.accessible_name = list ? _('Show as Grid') : _('Show as List');
        this._back.visible = this._trail.length > 1;
        const folder = this._current;
        this._title.text = this._trail.length > 1 && folder
            ? GLib.filename_display_basename(folder.get_path() ?? folder.get_uri())
            : this._icon.item.name;
    }

    _setSort(mode) {
        this._manager.stacks.setSortMode(this._entry, mode);
        this._resetView();
        this._syncTools();
        this._render();
    }

    // --- Reading --------------------------------------------------------

    _load() {
        this._cancellable?.cancel();
        this._monitor?.cancel();
        this._monitor = null;
        this._items = [];
        this._truncated = false;
        this._syncTools();
        const folder = this._current;
        if (!folder) {
            this._showStatus(_('This standard folder is not set up.'));
            this._place();
            return;
        }
        this._showStatus(_('Loading…'));
        this._place();
        const cancellable = new Gio.Cancellable();
        this._cancellable = cancellable;
        try {
            this._monitor = folder.monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, null);
            this._monitor.connect('changed', () => this._queueReload());
        } catch {
            // Without a monitor the panel just does not refresh by itself.
        }
        folder.enumerate_children_async(ATTRIBUTES, Gio.FileQueryInfoFlags.NONE,
            GLib.PRIORITY_DEFAULT, cancellable, (_f, res) => {
                let enumerator;
                try {
                    enumerator = folder.enumerate_children_finish(res);
                } catch (e) {
                    if (!e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                        this._failed(e);
                    return;
                }
                this._readBatch(enumerator, cancellable, []);
            });
    }

    _readBatch(enumerator, cancellable, items) {
        enumerator.next_files_async(BATCH, GLib.PRIORITY_DEFAULT, cancellable, (_e, res) => {
            let infos;
            try {
                infos = enumerator.next_files_finish(res);
            } catch (e) {
                if (!e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                    this._failed(e);
                enumerator.close_async(GLib.PRIORITY_LOW, null, null);
                return;
            }
            for (const info of infos) {
                if (info.get_is_hidden() || info.get_is_backup())
                    continue;
                items.push(info);
            }
            if (infos.length > 0 && items.length < MAX_SCANNED) {
                this._readBatch(enumerator, cancellable, items);
                return;
            }
            enumerator.close_async(GLib.PRIORITY_LOW, null, null);
            if (cancellable !== this._cancellable)
                return;
            this._cancellable = null;
            this._truncated = infos.length > 0;
            this._items = items.map(info => ({
                info,
                name: info.get_display_name(),
                isDir: info.get_file_type() === Gio.FileType.DIRECTORY,
                modified: info.get_attribute_uint64('time::modified'),
                type: info.get_content_type() ?? '',
            }));
            this._render();
        });
    }

    _failed(error) {
        if (this._cancellable)
            this._cancellable = null;
        let message;
        if (error.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.NOT_FOUND))
            message = _('This folder does not exist anymore.');
        else if (error.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.PERMISSION_DENIED))
            message = _('You do not have permission to open this folder.');
        else
            message = _('This folder cannot be opened: %s').replace('%s', error.message);
        this._content.destroy_all_children();
        this._sorted = [];
        this._shown = 0;
        this._showStatus(message);
        this._place();
    }

    _queueReload() {
        if (this._reloadId)
            return;
        this._reloadId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, RELOAD_DELAY, () => {
            this._reloadId = 0;
            // Not under a drag or an item's menu: they keep their item.
            if (this._itemDrag || this._itemMenu) {
                this._reloadWanted = true;
                return GLib.SOURCE_REMOVE;
            }
            if (this._panel) {
                this._saveView();
                this._load();
            }
            return GLib.SOURCE_REMOVE;
        });
    }

    _showStatus(text) {
        this._status.text = text ?? '';
        this._status.visible = Boolean(text);
    }

    // --- Showing --------------------------------------------------------

    _render() {
        if (!this._panel)
            return;
        this._cancelRestore();
        this._hideTooltip();
        const focused = global.stage.key_focus;
        const hadFocus = focused && this._content.contains(focused);
        // The items are made again: a highlighted one is found again below.
        this._dropButton = null;
        this._content.destroy_all_children();
        // A grid with a fixed number of columns, not a flow layout: the
        // scroll range comes from the minimum height of the contents, and
        // a flow layout reports a single row as its minimum.
        const list = this._manager.stacks.view === 'list';
        const room = this._dock?.monitor ? this._room() : null;
        this._columns = gridColumns(this._items.length, gridFit({
            roomWidth: room?.width ?? 0,
            limit: room ? panelHeights({workHeight: room.area.height, room: room.height,
                chrome: 0, content: 0}).limit : 0,
            frame: this._frame(),
            cell: this._cell,
            spacing: GRID_SPACING,
        }));
        this._content.layout_manager = list
            ? new Clutter.BoxLayout({orientation: Clutter.Orientation.VERTICAL})
            : new Clutter.GridLayout({
                column_spacing: GRID_SPACING,
                row_spacing: GRID_SPACING,
                column_homogeneous: true,
            });
        this._sorted = sortItems(this._items, this._manager.stacks.sortMode(this._entry));
        this._shown = 0;
        const view = this._trail.at(-1);
        this._appendItems(Math.max(CHUNK, view?.shown ?? 0));

        if (this._items.length === 0) {
            this._showStatus(_('This folder is empty.'));
        } else if (this._truncated) {
            this._showStatus(_('This folder has more than %d items; only the first ones are shown. Open it in Files to see all.')
                .replace('%d', MAX_SCANNED));
        } else {
            this._showStatus(null);
        }
        this._place();

        // Back where it was: the same item focused and the same scroll
        // position, once the contents have their size.
        const children = this._content.get_children();
        const again = view?.focus ? children.find(c => c._stackName === view.focus) : null;
        if (again || hadFocus) {
            this._quietFocus = true;
            (again ?? children[0])?.grab_key_focus();
            this._quietFocus = false;
        }
        if (view?.scroll > 0)
            this._restoreScroll(view.scroll);
        else
            this._scroll.vadjustment.value = 0;
        if (this._forDrag)
            this._manager.fileDrop?.repick(true);
    }

    // Builds the next count items (of the sorted ones) into the panel.
    _appendItems(count) {
        const list = this._manager.stacks.view === 'list';
        const layout = this._content.layout_manager;
        const end = Math.min(this._sorted.length, this._shown + count);
        for (let i = this._shown; i < end; i++) {
            const item = this._sorted[i];
            if (list)
                this._content.add_child(this._listItem(item));
            else
                layout.attach(this._gridItem(item), i % this._columns, Math.floor(i / this._columns), 1, 1);
        }
        this._shown = end;
    }

    // More items while the view nears the end of those shown; outside the
    // layout pass that reports it.
    _queueMore() {
        if (this._moreId || !this._panel)
            return;
        const adjustment = this._scroll.vadjustment;
        if (!needsMore({value: adjustment.value, pageSize: adjustment.page_size,
            upper: adjustment.upper, shown: this._shown, total: this._sorted.length}))
            return;
        this._moreId = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._moreId = 0;
            if (this._panel)
                this._appendItems(CHUNK);
            return GLib.SOURCE_REMOVE;
        });
    }

    // The scroll range is only known after the contents are laid out:
    // apply the value as soon as it fits.
    _restoreScroll(value) {
        const adjustment = this._scroll.vadjustment;
        const apply = () => {
            adjustment.value = Math.min(value, Math.max(0, adjustment.upper - adjustment.page_size));
            return adjustment.value >= value - 1;
        };
        if (apply())
            return;
        this._restoreId = adjustment.connect('changed', () => {
            if (apply())
                this._cancelRestore();
        });
    }

    _cancelRestore() {
        if (this._restoreId)
            this._scroll.vadjustment.disconnect(this._restoreId);
        this._restoreId = 0;
    }

    _gicon(item) {
        const info = item.info;
        const thumbnail = info.get_attribute_byte_string('thumbnail::path');
        if (thumbnail && info.get_attribute_boolean('thumbnail::is-valid'))
            return new Gio.FileIcon({file: Gio.File.new_for_path(thumbnail)});
        if (canThumbnailDirectly(item.type, info.get_size()))
            return new Gio.FileIcon({file: this._current.get_child(info.get_name())});
        return info.get_icon() ?? new Gio.ThemedIcon({name: 'text-x-generic'});
    }

    _button(item, styleClass) {
        const button = new St.Button({
            style_class: `popup-menu-item ${styleClass}`,
            can_focus: true,
            track_hover: true,
            accessible_name: item.name,
        });
        button._stackName = item.name;
        button._stackItem = item;
        button.connect('clicked', () => this._activate(item));
        this._makeDraggable(button, item);
        button.connect('button-press-event', (_b, event) => {
            if (event.get_button() !== Clutter.BUTTON_SECONDARY)
                return Clutter.EVENT_PROPAGATE;
            this._openItemMenu(button);
            return Clutter.EVENT_STOP;
        });
        button.connect('popup-menu', () => this._openItemMenu(button));
        // The focus follows the pointer when it moves, like in menus; not
        // when the contents scroll under a resting pointer, which would
        // take the focus away from the keyboard.
        button.connect('motion-event', () => {
            if (!button.has_key_focus()) {
                this._quietFocus = true;
                button.grab_key_focus();
                this._quietFocus = false;
            }
            return Clutter.EVENT_PROPAGATE;
        });
        button.connect('key-focus-in', () => {
            if (!this._quietFocus)
                this._scrollTo(button);
        });
        button.connect('notify::hover', () => {
            if (button.hover)
                this._queueTooltip(button);
            else
                this._hideTooltip();
        });
        return button;
    }

    // The item can be dragged onto another folder or the desktop
    // (stackDrag.js); starting to drag changes nothing.
    _makeDraggable(button, item) {
        const file = this._current.get_child(item.info.get_name());
        button._delegate = {
            stackFile: file,
            getDragActor: () => new St.Icon({
                gicon: this._gicon(item),
                fallback_icon_name: item.isDir ? 'folder' : 'text-x-generic',
                icon_size: GRID_ICON,
            }),
            getDragActorSource: () => button._stackIcon ?? button,
        };
        const draggable = DND.makeDraggable(button);
        draggable.connect('drag-begin', () => {
            this._itemDrag = true;
            this._hideTooltip();
            this._manager.stackDrag.begin(button._delegate);
        });
        draggable.connect('drag-end', () => this._endItemDrag());
    }

    _endItemDrag() {
        if (!this._itemDrag)
            return;
        this._itemDrag = false;
        this._manager.stackDrag.end();
        if (this._reloadWanted) {
            this._reloadWanted = false;
            this._queueReload();
        }
    }

    _gridItem(item) {
        const button = this._button(item, 'deskence-stack-item');
        const box = new St.BoxLayout({style_class: 'deskence-stack-item-box', width: ITEM_WIDTH});
        setVertical(box, true);
        button._stackIcon = new St.Icon({
            gicon: this._gicon(item),
            fallback_icon_name: item.isDir ? 'folder' : 'text-x-generic',
            icon_size: GRID_ICON,
            x_align: Clutter.ActorAlign.CENTER,
        });
        box.add_child(button._stackIcon);
        const label = new St.Label({
            text: item.name,
            style_class: 'deskence-stack-item-label',
            x_align: Clutter.ActorAlign.CENTER,
        });
        label.clutter_text.ellipsize = Pango.EllipsizeMode.MIDDLE;
        box.add_child(label);
        button.set_child(box);
        button.label_actor = label;
        return button;
    }

    _listItem(item) {
        const button = this._button(item, 'deskence-stack-row');
        const box = new St.BoxLayout({style_class: 'deskence-stack-row-box', x_expand: true});
        button._stackIcon = new St.Icon({
            gicon: this._gicon(item),
            fallback_icon_name: item.isDir ? 'folder' : 'text-x-generic',
            icon_size: LIST_ICON,
            y_align: Clutter.ActorAlign.CENTER,
        });
        box.add_child(button._stackIcon);
        const text = new St.BoxLayout({x_expand: true});
        setVertical(text, true);
        const name = new St.Label({text: item.name, style_class: 'deskence-stack-row-name'});
        name.clutter_text.ellipsize = Pango.EllipsizeMode.MIDDLE;
        const date = GLib.DateTime.new_from_unix_local(item.modified);
        const details = [
            item.isDir ? _('Folder') : GLib.format_size(item.info.get_size()),
            date?.format('%x %H:%M') ?? '',
        ].filter(Boolean).join(' · ');
        text.add_child(name);
        text.add_child(new St.Label({text: details, style_class: 'deskence-stack-row-details'}));
        box.add_child(text);
        button.set_child(box);
        button.label_actor = name;
        button.x_expand = true;
        return button;
    }

    // --- Tooltip --------------------------------------------------------

    _queueTooltip(button) {
        this._hideTooltip();
        this._tooltipId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, TOOLTIP_DELAY, () => {
            this._tooltipId = 0;
            this._showTooltip(button);
            return GLib.SOURCE_REMOVE;
        });
    }

    // Only for a name that does not fit.
    _showTooltip(button) {
        const label = button.label_actor;
        if (!this._panel || !button.hover || !label?.clutter_text.get_layout().is_ellipsized())
            return;
        const tooltip = this._tooltip;
        tooltip.text = button._stackName;
        tooltip.opacity = 0;
        tooltip.show();
        const monitor = this._dock.monitor;
        const [x, y] = button.get_transformed_position();
        const [width, height] = button.get_transformed_size();
        const [, natural] = tooltip.get_preferred_width(-1);
        tooltip.width = Math.min(natural, monitor.width - 2 * GAP);
        const [, tooltipHeight] = tooltip.get_preferred_height(tooltip.width);
        let tx = x + width / 2 - tooltip.width / 2;
        let ty = y - tooltipHeight - GAP / 2;
        if (ty < monitor.y + GAP)
            ty = y + height + GAP / 2;
        tx = Math.clamp(tx, monitor.x + GAP, monitor.x + monitor.width - tooltip.width - GAP);
        tooltip.set_position(Math.round(tx), Math.round(ty));
        tooltip.ease({opacity: 255, duration: 100, mode: Clutter.AnimationMode.EASE_OUT_QUAD});
    }

    _hideTooltip() {
        if (this._tooltipId)
            GLib.source_remove(this._tooltipId);
        this._tooltipId = 0;
        this._tooltip?.remove_all_transitions();
        this._tooltip?.hide();
    }

    _activate(item) {
        const file = this._current.get_child(item.info.get_name());
        if (item.isDir) {
            this._saveView();
            this._trail.push(this._view(file));
            this._load();
            return;
        }
        this.close();
        Main.overview.hide();
        // Launchers are shown, not run.
        if (isLauncher(item.info.get_name(), item.type)) {
            openInFiles(this._current ?? file.get_parent(), file);
            return;
        }
        Gio.AppInfo.launch_default_for_uri_async(file.get_uri(), launchContext(), null,
            (_o, res) => {
                try {
                    Gio.AppInfo.launch_default_for_uri_finish(res);
                } catch (e) {
                    Main.notifyError(_('Could not open “%s”').replace('%s', item.name), e.message);
                }
            });
    }

    _goBack() {
        if (this._trail.length <= 1)
            return;
        this._trail.pop();
        this._load();
    }

    _onKeyPress(event) {
        const key = event.get_key_symbol();
        if (event.get_state() & Clutter.ModifierType.CONTROL_MASK) {
            const cut = [Clutter.KEY_x, Clutter.KEY_X].includes(key);
            const focus = global.stage.key_focus;
            const button = focus && this._content.contains(focus)
                ? this._content.get_children().find(c => c.contains(focus)) : null;
            if (button && (cut || [Clutter.KEY_c, Clutter.KEY_C].includes(key))) {
                this._toClipboard(button, cut);
                return Clutter.EVENT_STOP;
            }
        }
        if (key === Clutter.KEY_BackSpace ||
            (key === Clutter.KEY_Left && (event.get_state() & Clutter.ModifierType.MOD1_MASK))) {
            this._goBack();
            return Clutter.EVENT_STOP;
        }
        const directions = {
            [Clutter.KEY_Left]: St.DirectionType.LEFT,
            [Clutter.KEY_Right]: St.DirectionType.RIGHT,
            [Clutter.KEY_Up]: St.DirectionType.UP,
            [Clutter.KEY_Down]: St.DirectionType.DOWN,
        };
        const direction = directions[key];
        if (direction === undefined)
            return Clutter.EVENT_PROPAGATE;
        // The focused item scrolls into view by itself (key-focus-in).
        const focus = global.stage.key_focus;
        this._panel.navigate_focus(this._panel.contains(focus) ? focus : null, direction, false);
        return Clutter.EVENT_STOP;
    }

    // --- The clipboard --------------------------------------------------

    // Copy and Cut for the item of button. The menu holds its own grab
    // above the panel's: a click outside it or Escape closes only the
    // menu.
    _openItemMenu(button) {
        if (!this._grabHelper || this._itemDrag || !button._delegate?.stackFile)
            return;
        this._closeItemMenu();
        this._hideTooltip();
        const menu = new PopupMenu.PopupMenu(button, 0.5, St.Side.TOP);
        menu.addAction(_('Copy'), () => this._toClipboard(button, false), 'edit-copy-symbolic');
        menu.addAction(_('Cut'), () => this._toClipboard(button, true), 'edit-cut-symbolic');
        Main.layoutManager.addTopChrome(menu.actor);
        this._itemMenuManager ??= new PopupMenu.PopupMenuManager(this._panel);
        this._itemMenuManager.addMenu(menu);
        menu.connect('open-state-changed', (_m, open) => {
            if (open)
                return;
            if (button.get_stage())
                button.grab_key_focus();
            // Not while the menu emits its signal.
            GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
                if (this._itemMenu === menu)
                    this._closeItemMenu();
                return GLib.SOURCE_REMOVE;
            });
        });
        this._itemMenu = menu;
        menu.open();
        menu.actor.navigate_focus(null, St.DirectionType.TAB_FORWARD, false);
    }

    _closeItemMenu() {
        const menu = this._itemMenu;
        if (!menu)
            return;
        this._itemMenu = null;
        // Destroying it releases its grab (PopupMenuManager).
        menu.destroy();
        if (this._reloadWanted && this._panel && !this._itemDrag) {
            this._reloadWanted = false;
            this._queueReload();
        }
    }

    // The item as copied or cut files for Files or the desktop to paste.
    _toClipboard(button, cut) {
        const file = button._delegate?.stackFile;
        if (!file)
            return;
        const text = copiedFiles([file.get_uri()], cut);
        St.Clipboard.get_default().set_content(St.ClipboardType.CLIPBOARD, COPIED_FILES,
            new GLib.Bytes(new TextEncoder().encode(text)));
    }

    // Shows the whole item, scrolling as little as needed.
    _scrollTo(actor) {
        if (!this._content.contains(actor))
            return;
        const adjustment = this._scroll.vadjustment;
        const box = actor.get_allocation_box();
        const top = box.y1;
        const bottom = box.y2;
        const page = adjustment.page_size;
        if (top < adjustment.value)
            adjustment.value = top;
        else if (bottom > adjustment.value + page)
            adjustment.value = bottom - page;
    }

    // The free area beside the dock, inside the work area of its monitor:
    // {left, right, top, bottom} of the work area on the monitor, {start,
    // end} horizontally and {bottom} beside the dock, and the room for the
    // panel there.
    _room() {
        const dock = this._dock;
        const monitor = dock.monitor;
        const area = Main.layoutManager.getWorkAreaForMonitor(dock.monitorIndex);
        const [across] = dock.magnifier.overflow();
        const rect = dock.rect;
        const left = Math.max(area.x, monitor.x);
        const right = Math.min(area.x + area.width, monitor.x + monitor.width);
        const top = Math.max(area.y, monitor.y);
        let bottom = Math.min(area.y + area.height, monitor.y + monitor.height);
        let start = left, end = right;
        switch (dock.position) {
        case 'left':
            start = Math.max(start, rect.x + rect.width + across);
            break;
        case 'right':
            end = Math.min(end, rect.x - across);
            break;
        default:
            bottom = Math.min(bottom, rect.y - across);
        }
        return {
            area, left, right, top, bottom, start, end,
            width: Math.max(0, end - start - 2 * GAP),
            height: Math.max(0, bottom - top - 2 * GAP),
        };
    }

    // Horizontal space of the panel around its contents.
    _frame() {
        const node = this._panel.get_theme_node();
        return node.get_horizontal_padding() +
            node.get_border_width(St.Side.LEFT) + node.get_border_width(St.Side.RIGHT) +
            this._scroll.get_theme_node().get_horizontal_padding();
    }

    // Next to the icon, on the inner side of the dock, inside the work area
    // of the dock's monitor. As tall as the contents, up to the limit of
    // panelHeights(); the grid has the columns chosen in _render().
    _place() {
        const panel = this._panel;
        const dock = this._dock;
        if (!panel || !dock?.monitor)
            return;
        const room = this._room();
        const item = this._icon.get_parent() ?? this._icon;
        const extents = item.get_transformed_extents();

        // Width: a fixed one for the list, whole columns for the grid.
        const frame = this._frame();
        const list = this._manager.stacks.view === 'list';
        const columns = this._columns;
        const width = Math.round(list ? Math.min(LIST_WIDTH, room.width)
            : Math.min(columns * this._cell + (columns - 1) * GRID_SPACING + frame, room.width));
        panel.width = width;

        // Height: everything but the contents, then the contents up to
        // what is left under the limit.
        this._scroll.height = 0;
        const [, chrome] = panel.get_preferred_height(width);
        this._scroll.height = -1;
        const [, content] = this._scroll.get_preferred_height(
            width - frame + this._scroll.get_theme_node().get_horizontal_padding());
        const {scroll, height} = panelHeights({
            workHeight: room.area.height, room: room.height, chrome, content,
        });
        this._scroll.height = scroll;

        let x, y;
        const centerX = extents.get_x() + extents.get_width() / 2;
        const centerY = extents.get_y() + extents.get_height() / 2;
        switch (dock.position) {
        case 'left':
            x = room.start + GAP;
            y = centerY - height / 2;
            break;
        case 'right':
            x = room.end - width - GAP;
            y = centerY - height / 2;
            break;
        default:
            x = centerX - width / 2;
            y = room.bottom - height - GAP;
        }
        x = Math.clamp(x, room.left + GAP, Math.max(room.left + GAP, room.right - width - GAP));
        y = Math.clamp(y, room.top + GAP, Math.max(room.top + GAP, room.bottom - height - GAP));
        panel.set_position(Math.round(x), Math.round(y));
    }

    // A click outside or Escape: GrabHelper still holds the modal grab of
    // the panel while it calls this, so the panel is only hidden now and
    // destroyed once the grab is gone.
    _onUngrab(panel) {
        if (this._panel !== panel)
            return;
        this._grabHelper = null;
        panel.hide();
        this._closeItemMenu();
        this._hideTooltip();
        GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            if (this._panel === panel)
                this.close();
            return GLib.SOURCE_REMOVE;
        });
    }

    close() {
        if (!this._panel)
            return;
        const panel = this._panel;
        const icon = this._icon;
        const dock = this._dock;
        this._cancelRestore();
        // First: closing it gives the hover back to its item, which would
        // queue a tooltip.
        this._closeItemMenu();
        this._itemMenuManager = null;
        this._hideTooltip();
        this._panel = null;
        this._icon = null;
        this._dock = null;
        this._cancellable?.cancel();
        this._cancellable = null;
        this._monitor?.cancel();
        this._monitor = null;
        for (const id of [this._reloadId, this._moreId]) {
            if (id)
                GLib.source_remove(id);
        }
        this._reloadId = 0;
        this._moreId = 0;
        if (this._dragScrollId)
            GLib.source_remove(this._dragScrollId);
        this._dragScrollId = 0;
        // GNOME Shell cancels the drag of a destroyed item without telling
        // its handlers (Draggable disconnects them), so end it here.
        this._endItemDrag();
        this._reloadWanted = false;
        this._dragPoint = null;
        this._dropButton = null;
        this._forDrag = false;
        this._hint = null;
        this._items = [];
        this._sorted = [];
        this._shown = 0;
        this._trail = [];
        const grabHelper = this._grabHelper;
        this._grabHelper = null;
        if (grabHelper?.grabbed)
            grabHelper.ungrab({actor: panel});
        if (icon?.get_stage()) {
            icon.remove_style_pseudo_class('active');
            dock?.setMenuOpen(icon, false);
        }
        this._tooltip?.destroy();
        this._tooltip = null;
        panel.destroy();
    }

    closeFor(dock) {
        if (this._dock === dock)
            this.close();
    }

    destroy() {
        this.close();
        this._manager = null;
    }
}
