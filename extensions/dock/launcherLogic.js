// SPDX-License-Identifier: GPL-3.0-or-later
//
// Counters and progress that applications report for their dock icon,
// through the LauncherEntry D-Bus API (com.canonical.Unity.LauncherEntry,
// used by Dash to Dock, Plank and KDE; libunity, Electron, Qt and
// Chromium-based applications send it). Without GNOME Shell imports so it
// can be tested (tests/unit/test_launcher.js); launcherEntry.js listens on
// the bus.
//
// An application emits the signal Update(s app_uri, a{sv} properties) from
// any object path. app_uri is "application://<desktop id>"; the properties
// are changes, not the whole state: "count" (int64), "count-visible"
// (boolean), "progress" (double 0..1), "progress-visible" (boolean); others
// ("urgent", "quicklist") are not used. A property with a wrong type or a
// value out of range is ignored; a count below zero is ignored, progress
// is clamped to 0..1.
//
// Several senders (D-Bus connections) can report for the same
// application, for example a browser and its helper process. Their values
// are never added up, which would count the same messages twice: the
// counter shown is the one of the sender that updated it last while
// showing it, and the same for progress. Everything a sender reported goes
// away with its connection (launcherEntry.js watches it), so a counter
// never outlives the process that set it, while an application without
// windows that still runs keeps its counter.

export const MAX_SHOWN_COUNT = 99;

// "firefox.desktop" from "application://firefox.desktop", or null.
export function appIdFromUri(uri) {
    if (typeof uri !== 'string' || !uri.startsWith('application://'))
        return null;
    const id = uri.slice('application://'.length);
    return /^[A-Za-z0-9._+-]+\.desktop$/.test(id) ? id : null;
}

// The valid properties of one update, in our names.
export function parseUpdate(properties) {
    const result = {};
    if (properties === null || typeof properties !== 'object')
        return result;
    const count = properties['count'];
    if (typeof count === 'number' && Number.isInteger(count) && count >= 0)
        result.count = count;
    else if (typeof count === 'bigint' && count >= 0n)
        result.count = count > BigInt(Number.MAX_SAFE_INTEGER) ? Number.MAX_SAFE_INTEGER : Number(count);
    if (typeof properties['count-visible'] === 'boolean')
        result.countVisible = properties['count-visible'];
    const progress = properties['progress'];
    if (typeof progress === 'number' && Number.isFinite(progress))
        result.progress = Math.min(Math.max(progress, 0), 1);
    if (typeof properties['progress-visible'] === 'boolean')
        result.progressVisible = properties['progress-visible'];
    return result;
}

// The text of a counter badge.
export function badgeText(count) {
    return count > MAX_SHOWN_COUNT ? `${MAX_SHOWN_COUNT}+` : `${count}`;
}

// Size of the counter on an icon of iconSize logical pixels: a circle for
// one digit, a pill as wide as needed for more. It is laid out at
// renderScale times its size and shown scaled down by the same factor, so
// it stays sharp at the largest magnification, as the icons do
// (markScale in logic.js). Returns logical pixels at the render scale,
// except the margin from the corner of the icon, which is as shown.
export function badgeGeometry(iconSize, renderScale) {
    const scale = Math.max(1, renderScale);
    const diameter = Math.max(16, Math.round(iconSize * 0.38));
    return {
        diameter: Math.round(diameter * scale),
        fontSize: Math.round(diameter * 0.62 * scale),
        padding: Math.round(diameter * 0.22 * scale),
        margin: Math.round(Math.max(1, iconSize * 0.03)),
        scale,
    };
}

const same = (a, b) => a.count === b.count && a.progress === b.progress;

export class LauncherState {
    constructor() {
        // desktop id -> Map(sender -> {count, countVisible, progress,
        // progressVisible, stamp})
        this._apps = new Map();
    }

    // Applies an update; returns whether what is shown for appId changed.
    update(sender, appId, values, stamp) {
        const before = this.get(appId);
        let senders = this._apps.get(appId);
        if (!senders) {
            senders = new Map();
            this._apps.set(appId, senders);
        }
        senders.set(sender, {...senders.get(sender), ...values, stamp});
        return !same(before, this.get(appId));
    }

    // Forgets a sender; returns the ids whose shown values changed.
    removeSender(sender) {
        const changed = [];
        for (const [appId, senders] of this._apps) {
            if (!senders.has(sender))
                continue;
            const before = this.get(appId);
            senders.delete(sender);
            if (senders.size === 0)
                this._apps.delete(appId);
            if (!same(before, this.get(appId)))
                changed.push(appId);
        }
        return changed;
    }

    // The ids of all applications with something reported.
    appIds() {
        return [...this._apps.keys()];
    }

    clear() {
        const ids = this.appIds().filter(id => {
            const shown = this.get(id);
            return shown.count !== null || shown.progress !== null;
        });
        this._apps.clear();
        return ids;
    }

    // {count, progress}: what to show, null for nothing.
    get(appId) {
        const senders = [...(this._apps.get(appId)?.values() ?? [])]
            .sort((a, b) => b.stamp - a.stamp);
        const counter = senders.find(s => s.countVisible === true && s.count > 0);
        const progress = senders.find(s => s.progressVisible === true &&
            typeof s.progress === 'number');
        return {
            count: counter ? counter.count : null,
            progress: progress ? progress.progress : null,
        };
    }
}
