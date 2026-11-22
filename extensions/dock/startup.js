// SPDX-License-Identifier: GPL-3.0-or-later
//
// Starting a session on the desktop instead of the activities overview
// (show-desktop-at-login).
//
// GNOME Shell enables the extensions while its startup animation runs
// (layout.js _doStartupAnimation and ExtensionManager.init() are both
// asynchronous, GNOME 48 and 51). Which of them gets further first
// depends on how fast the wallpaper and the extension modules load:
//
//  - Before the animation has chosen what to show, the session mode is
//    told it has no overview until the startup is complete. The animation
//    then brings up the desktop and the overview is never opened. The
//    overview itself was set up before extensions load, so it stays a real
//    overview.
//  - Once the startup animation is opening the overview, it is hidden
//    through the path GNOME has for an overview hidden during that
//    animation (Overview.runStartupAnimation), but only after the overview
//    controls got their first allocation. The animation waits for that
//    allocation (OverviewControls.runStartupAnimation awaits
//    ensureAllocation()), and a hidden overview is never allocated: hidden
//    earlier - at once when animations are off, as GNOME Shell does without
//    hardware acceleration - the startup never completed, and GNOME's
//    input blocker over the screen (layout.js _coverPane, removed when the
//    startup completes) stayed, so only the dock, which lies above it, took
//    clicks until the overview was opened once. Until the allocation the
//    overview shows the full-size workspace with transparent controls,
//    which looks like the desktop; the animation then simply turns back to
//    it. There is no timeout. Of the controls only the search entry is
//    laid out in that state (workspace thumbnails are transparent there,
//    GNOME's dash is replaced by the dock), and the startup animation fades
//    it in while the overview hides, so it is kept transparent until the
//    overview is hidden.
//
// Outside the startup (an extension enabled or reloaded during the
// session, unlocking the screen) this does nothing, so an overview the
// user opened is never closed.

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

// Set on the top bar by Overview.runStartupAnimation() and only cleared
// when the overview ends up shown.
const STARTUP_PANEL_STYLE = 'transition-duration: 0ms;';

export class StartOnDesktop {
    constructor(settings) {
        this._mode = null;
        this._searchEntry = null;
        this._hidePending = false;
        const layout = Main.layoutManager;
        if (!layout._startingUp || !settings.get_boolean('show-desktop-at-login'))
            return;
        if (Main.overview.visible) {
            this._hideStartupOverview();
        } else if (Main.sessionMode.hasOverview) {
            this._mode = Main.sessionMode.currentMode;
            Main.sessionMode.hasOverview = false;
        }
        layout.connectObject('startup-complete', () => this._restore(), this);
    }

    _hideStartupOverview() {
        this._searchEntry = Main.overview._overview?.controls?._searchEntryBin ?? null;
        if (this._searchEntry) {
            this._searchEntry.opacity = 0;
            Main.overview.connectObject('hidden', () => this._showSearchEntry(), this);
        }
        this._hidePending = true;
        const hide = () => {
            if (!this._hidePending)
                return;
            this._hidePending = false;
            Main.overview.hide();
        };
        const controlsLayout = Main.overview._overview?.controls?.layout_manager;
        if (controlsLayout?.ensureAllocation) {
            // Resolves right after the startup animation's own wait for
            // the allocation, which was registered first.
            controlsLayout.ensureAllocation().then(hide);
        } else {
            // Without that API, wait for the startup animation to end.
            Main.overview.connectObject('shown', hide, this);
        }
    }

    _showSearchEntry() {
        Main.overview.disconnectObject(this);
        if (this._searchEntry)
            this._searchEntry.opacity = 255;
        this._searchEntry = null;
    }

    _restore() {
        Main.layoutManager.disconnectObject(this);
        // A change of session mode in between already set hasOverview from
        // the new mode; only undo our own change.
        if (this._mode !== null && Main.sessionMode.currentMode === this._mode &&
            !Main.sessionMode.hasOverview)
            Main.sessionMode.hasOverview = true;
        this._mode = null;
        if (Main.panel.style === STARTUP_PANEL_STYLE && !Main.overview.visible)
            Main.panel.style = null;
    }

    destroy() {
        this._hidePending = false;
        this._restore();
        this._showSearchEntry();
    }
}
