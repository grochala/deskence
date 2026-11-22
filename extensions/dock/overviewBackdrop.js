// SPDX-License-Identifier: GPL-3.0-or-later
//
// Wallpaper and color under the overview, driven by the overview's own state
// (0 hidden, 1 window picker, 2 application grid).
//
// While the overview is shown, GNOME hides the windows and the desktop
// background and paints #overviewGroup in a solid color; the workspace
// preview draws the wallpaper only inside the work area.
//
//  - Dock band: a dock that reserves space takes a band along its edge out
//    of the work area. The workspace preview (Workspace.WorkspaceBackground)
//    lays out the wallpaper of the whole monitor so that its work area part
//    fills the preview, and clips it there. Near the end of closing the
//    overview the band along the dock would therefore stay solid color and
//    the real wallpaper would appear only when the overview is gone.
//    Instead the preview itself is extended over the band: its clip (and
//    the rounded clip of its wallpaper) grows by the band, scaled like the
//    preview, by logic.js dockBandExtension() of the overview state - all
//    of it when the overview is gone, nothing from the window picker on. The
//    band is drawn by the same actor as the rest of the preview, so it
//    moves and scales with it in one continuous transition, and the last
//    frame of the overview equals the desktop. Secondary monitors clip
//    their workspace view to the work area; that clip is widened the same
//    way.
//  - Application grid: with a custom background the wallpaper and/or a
//    color layer are blended in above #overviewGroup's background in the
//    application grid state only (the shell's CSS is not touched, so other
//    views stay as they are). Both layers are below every overview child,
//    so icons, labels and the search entry are not affected. The alpha of
//    the color comes from the transparency setting alone, see logic.js
//    appGridLayers(). The layers cover the primary monitor below the top
//    bar: the bar, transparent in the overview, keeps the standard dark
//    background its light text is made for.

import Clutter from 'gi://Clutter';
import Cogl from 'gi://Cogl';
import Graphene from 'gi://Graphene';
import Meta from 'gi://Meta';

import * as Background from 'resource:///org/gnome/shell/ui/background.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as Workspace from 'resource:///org/gnome/shell/ui/workspace.js';
import {InjectionManager} from 'resource:///org/gnome/shell/extensions/extension.js';

import {appGridLayers, dockBandExtension, inkForBackground} from './logic.js';

// Given to the application grid while its background lets the wallpaper
// through (names get a shadow to stay readable on bright images), or has a
// light custom color (dark names and controls).
const SEE_THROUGH_CLASS = 'deskence-app-grid-see-through';
const DARK_INK_CLASS = 'deskence-app-grid-ink-dark';
// The color is used for the contrast of names from this opacity on.
const OPAQUE_ENOUGH = 0.4;

function parseColor(color) {
    const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(color ?? '');
    if (!match)
        return null;
    const [red, green, blue] = match.slice(1).map(h => parseInt(h, 16));
    return {red, green, blue};
}

function makeColor({red, green, blue}) {
    const Color = Cogl.Color ?? Clutter.Color;
    return new Color({red, green, blue, alpha: 255});
}

class WallpaperLayer {
    constructor(parent, monitorIndex) {
        this.actor = new Meta.BackgroundGroup({opacity: 0, visible: false});
        parent.add_child(this.actor);
        this._background = new Background.BackgroundManager({
            container: this.actor,
            monitorIndex,
            controlPosition: true,
            useContentSize: true,
        });
    }

    setOpacity(opacity) {
        this.actor.opacity = opacity;
        this.actor.visible = opacity > 0;
    }

    destroy() {
        this._background.destroy();
        this.actor.destroy();
    }
}

export class OverviewBackdrop {
    constructor() {
        this._adjustment = Main.overview._overview?.controls?._stateAdjustment ?? null;
        this._bands = new Map();
        this._backgrounds = new Set();
        this._appGrid = null;
        this._appGridColor = null;
        this._appGridTransparency = 0;
        this._appGridCustomColor = null;
        if (!this._adjustment || !Workspace.WorkspaceBackground)
            return; // unknown shell internals: keep the standard look

        this._root = new Clutter.Actor({reactive: false});
        Main.layoutManager.overviewGroup.insert_child_at_index(this._root, 0);
        this._adjustment.connectObject('notify::value', () => this._sync(), this);

        // Every workspace preview background registers itself when it sets
        // up its clip; the shell creates new ones whenever the overview
        // opens.
        const backdrop = this;
        this._injections = new InjectionManager();
        const proto = Workspace.WorkspaceBackground.prototype;
        for (const method of ['_updateRoundedClipBounds', '_updateBorderRadius']) {
            this._injections.overrideMethod(proto, method, original => function (...args) {
                original.call(this, ...args);
                backdrop._track(this);
            });
        }
    }

    // bands: [{monitorIndex, edge, size}]: the band a dock on that edge of
    // the monitor takes from the work area, in logical pixels.
    setDockBands(bands) {
        if (!this._root)
            return;
        this._bands = new Map();
        for (const {monitorIndex, edge, size} of bands) {
            const band = this._bands.get(monitorIndex) ?? {left: 0, right: 0, bottom: 0};
            band[edge] = Math.max(band[edge], size);
            this._bands.set(monitorIndex, band);
        }
        this._sync();
    }

    // transparency: 0 (standard, opaque) .. 1 (wallpaper only);
    // color: "#rrggbb", or null for the standard color.
    setAppGridBackground(transparency, color) {
        if (!this._root)
            return;
        this._appGridTransparency = transparency;
        this._appGridCustomColor = parseColor(color);
        const index = Main.layoutManager.primaryIndex;
        if (transparency > 0 && (!this._appGrid || this._appGridMonitor !== index)) {
            this._appGrid?.destroy();
            this._appGrid = new WallpaperLayer(this._root, index);
            this._appGridMonitor = index;
        } else if (transparency === 0) {
            this._appGrid?.destroy();
            this._appGrid = null;
        }
        if (this._appGridCustomColor) {
            if (!this._appGridColor) {
                this._appGridColor = new Clutter.Actor({reactive: false, visible: false});
                // Above the wallpaper, below the overview content.
                this._root.add_child(this._appGridColor);
            }
            this._root.set_child_above_sibling(this._appGridColor, null);
            this._appGridColor.background_color = makeColor(this._appGridCustomColor);
        } else {
            this._appGridColor?.destroy();
            this._appGridColor = null;
        }
        this._updateAppGridArea();
        this._updateAppGridStyle();
        this._sync();
    }

    // The primary monitor below the top bar.
    _updateAppGridArea() {
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor)
            return;
        const panel = Main.layoutManager.panelBox;
        const top = panel.visible ? panel.height : 0;
        const rect = [monitor.x, monitor.y + top, monitor.width, Math.max(0, monitor.height - top)];
        this._appGridColor?.set_position(rect[0], rect[1]);
        this._appGridColor?.set_size(rect[2], rect[3]);
        this._appGrid?.actor.set_clip(...rect);
    }

    // Names, folders and page controls readable on the chosen background.
    _updateAppGridStyle() {
        const t = this._appGridTransparency;
        const color = this._appGridCustomColor;
        const darkInk = color !== null && 1 - t >= OPAQUE_ENOUGH &&
            inkForBackground({...color, alpha: 1 - t}) === 'dark';
        this._setAppGridClass(SEE_THROUGH_CLASS, t > 0 && !darkInk);
        this._setAppGridClass(DARK_INK_CLASS, darkInk);
    }

    _setAppGridClass(name, wanted) {
        const appDisplay = Main.overview._overview?.controls?.appDisplay;
        if (wanted)
            appDisplay?.add_style_class_name(name);
        else
            appDisplay?.remove_style_class_name(name);
    }

    _track(background) {
        if (!this._backgrounds.has(background)) {
            this._backgrounds.add(background);
            background._bin.connectObject('notify::allocation',
                () => this._extend(background), this);
            background.connectObject('destroy', () => this._backgrounds.delete(background), this);
        }
        this._extend(background);
    }

    // The band of this preview's monitor scaled like the preview, or null.
    _scaledBand(monitorIndex) {
        const band = this._bands.get(monitorIndex);
        if (!band || !this._adjustment)
            return null;
        const extension = dockBandExtension(this._adjustment.value);
        if (extension === 0)
            return null;
        return {
            left: band.left * extension,
            right: band.right * extension,
            bottom: band.bottom * extension,
        };
    }

    _extend(background) {
        const bin = background._bin;
        const content = background._bgManager?.backgroundActor?.content;
        const monitor = Main.layoutManager.monitors[background._monitorIndex];
        const workArea = background._workarea;
        if (!bin || !content || !monitor || !workArea)
            return;
        const band = this._scaledBand(background._monitorIndex);

        const bounds = new Graphene.Rect();
        bounds.origin.x = workArea.x - monitor.x - (band?.left ?? 0);
        bounds.origin.y = workArea.y - monitor.y;
        bounds.size.width = workArea.width + (band ? band.left + band.right : 0);
        bounds.size.height = workArea.height + (band?.bottom ?? 0);
        content.set_rounded_clip_bounds(bounds);

        if (!band) {
            bin.remove_clip();
            bin.clip_to_allocation = true;
            return;
        }
        // The bin shows the work area; the wallpaper around it is laid out
        // with the same scale.
        const [width, height] = bin.get_size();
        const xScale = width / workArea.width;
        const yScale = height / workArea.height;
        bin.clip_to_allocation = false;
        bin.set_clip(-band.left * xScale, 0,
            width + (band.left + band.right) * xScale, height + band.bottom * yScale);
    }

    // Secondary monitors clip their workspace view to the work area.
    _extendSecondaryViews() {
        const views = Main.overview._overview?.controls?._workspacesDisplay?._workspacesViews ?? [];
        for (const view of views) {
            if (!view.has_style_class_name?.('secondary-monitor-workspaces'))
                continue;
            const band = this._scaledBand(view._monitorIndex);
            if (!band) {
                view.remove_clip();
                view.clip_to_allocation = true;
                continue;
            }
            const [width, height] = view.get_size();
            view.clip_to_allocation = false;
            view.set_clip(-band.left, 0, width + band.left + band.right, height + band.bottom);
        }
    }

    _sync() {
        const value = this._adjustment.value;
        this._backgrounds.forEach(b => this._extend(b));
        this._extendSecondaryViews();
        const layers = appGridLayers(value, this._appGridTransparency,
            this._appGridColor !== null);
        this._appGrid?.setOpacity(layers.wallpaper);
        if (this._appGridColor) {
            this._appGridColor.opacity = layers.color;
            this._appGridColor.visible = layers.color > 0;
        }
    }

    destroy() {
        this._adjustment?.disconnectObject(this);
        this._injections?.clear();
        this._injections = null;
        // Without bands, the previews get their own clips back.
        this._bands = new Map();
        for (const background of this._backgrounds) {
            background._bin.disconnectObject(this);
            background.disconnectObject(this);
            this._extend(background);
        }
        this._backgrounds.clear();
        if (this._root)
            this._extendSecondaryViews();
        this._setAppGridClass(SEE_THROUGH_CLASS, false);
        this._setAppGridClass(DARK_INK_CLASS, false);
        this._appGrid?.destroy();
        this._appGrid = null;
        this._appGridColor = null;
        this._root?.destroy();
        this._root = null;
    }
}
