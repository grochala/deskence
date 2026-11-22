// SPDX-License-Identifier: GPL-3.0-or-later
//
// Colors of the tiles in the application grid: the background of folder
// tiles ("Utilities", "System"...; app-grid-folder-* settings) and the
// highlight under the pointer on applications, folders and applications
// in an open folder (app-grid-hover-* settings).
//
// The theme gives .app-folder an opaque background for every state (hover,
// focus, active, selected, drop), so an inline style would either cover
// those states or lose them. Instead a small stylesheet made by logic.js
// appGridStylesheet() is loaded into the theme and replaced whenever the
// settings or the GNOME style change; St then restyles the tiles at once,
// also while the application grid is open. Without an override nothing is
// loaded and the theme applies unchanged.
//
// With only the transparency (or only the color) overridden, the rest is
// the theme's: it is read from invisible probes with the tiles' style
// classes (a folder at rest, an application under the pointer) inside the
// application grid, outside the scroll view the stylesheet is limited to,
// so the probes always show the style the tiles would have without us. St
// does not restyle an unmapped widget until it is shown, so the probes' own
// style-changed is not reliable; the style is read again after every theme
// change instead, once St has dropped the old style information.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {appGridStylesheet, effectiveBackground} from './logic.js';

export class AppGridTiles {
    constructor() {
        this._folder = {color: null, transparency: null};
        this._hover = {color: null, transparency: null};
        this._css = null;
        this._file = null;
        this._serial = 0;
        this._probe = null;
        this._hoverProbe = null;
        this._idleId = 0;
        const appDisplay = Main.overview._overview?.controls?.appDisplay;
        if (!appDisplay)
            return; // unknown shell internals: keep the standard look
        // Reactive like a real tile: St styles a non-reactive widget as
        // :insensitive, which the theme draws darker.
        this._probe = new St.Widget({
            style_class: 'overview-tile app-folder',
            reactive: true,
            visible: false,
        });
        appDisplay.add_child(this._probe);
        this._hoverProbe = new St.Widget({
            style_class: 'overview-tile',
            reactive: true,
            visible: false,
        });
        this._hoverProbe.add_style_pseudo_class('hover');
        appDisplay.add_child(this._hoverProbe);
        St.ThemeContext.get_for_stage(global.stage).connectObject(
            'changed', () => this._queueUpdate(), this);
    }

    // folder and hover: {color, transparency}; color "#rrggbb" or null for
    // the theme color, transparency 0..100 or null for the theme alpha.
    set(folder, hover) {
        this._folder = folder;
        this._hover = hover;
        this._queueUpdate();
    }

    _queueUpdate() {
        if (this._idleId)
            return;
        this._idleId = GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            this._idleId = 0;
            this._update();
            return GLib.SOURCE_REMOVE;
        });
    }

    _update() {
        if (!this._probe)
            return;
        const overridden = ({color, transparency}) => color !== null || transparency !== null;
        let css = null;
        if (overridden(this._folder) || overridden(this._hover)) {
            const themeFolder = this._themeColor(this._probe);
            const themeHover = this._themeColor(this._hoverProbe);
            const layer = (theme, {color, transparency}) => color !== null || transparency !== null
                ? effectiveBackground(theme, color, transparency) : null;
            css = appGridStylesheet({
                folder: layer(themeFolder, this._folder),
                hover: layer(themeHover, this._hover),
                themeFolder: effectiveBackground(themeFolder, null, null),
            });
        }
        // Loading a stylesheet is a theme change too, which brings us back
        // here: only reload what changed.
        if (css !== this._css)
            this._load(css);
    }

    // {red, green, blue, alpha (0..255)} of a probe.
    _themeColor(probe) {
        if (!probe.get_stage())
            return {red: 0, green: 0, blue: 0, alpha: 255};
        const c = probe.get_theme_node().get_background_color();
        return {red: c.red, green: c.green, blue: c.blue, alpha: c.alpha};
    }

    _load(css) {
        const theme = St.ThemeContext.get_for_stage(global.stage).get_theme();
        const previous = this._file;
        this._css = css;
        this._file = null;
        if (css !== null) {
            // A new file each time: the theme keeps loaded stylesheets by file.
            const dir = GLib.build_filenamev([GLib.get_user_runtime_dir(), 'deskence']);
            GLib.mkdir_with_parents(dir, 0o700);
            const name = `app-grid-${GLib.get_real_time()}-${++this._serial}.css`;
            const file = Gio.File.new_for_path(GLib.build_filenamev([dir, name]));
            try {
                file.replace_contents(new TextEncoder().encode(css), null, false,
                    Gio.FileCreateFlags.REPLACE_DESTINATION, null);
                theme.load_stylesheet(file);
                this._file = file;
            } catch (e) {
                console.warn(`Deskence Dock: cannot style the application grid: ${e.message}`);
                this._delete(file);
            }
        }
        if (previous) {
            theme.unload_stylesheet(previous);
            this._delete(previous);
        }
    }

    _delete(file) {
        try {
            file.delete(null);
        } catch {
            // Already gone; the runtime directory is cleared at logout anyway.
        }
    }

    destroy() {
        if (this._idleId)
            GLib.source_remove(this._idleId);
        this._idleId = 0;
        St.ThemeContext.get_for_stage(global.stage).disconnectObject(this);
        this._probe?.destroy();
        this._probe = null;
        this._hoverProbe?.destroy();
        this._hoverProbe = null;
        if (this._file)
            this._load(null);
    }
}
