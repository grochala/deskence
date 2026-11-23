// SPDX-License-Identifier: GPL-3.0-or-later
// Run with: gjs -m tests/unit/test_geometry.js
import System from 'system';

import {amountForRoom, appGridLayers, appsButtonMaxScale, backgroundColor, distributionLogoNames,
    appGridStylesheet, composite as compositeColor, cssColor, dockBandExtension, effectiveBackground, fitInView,
    folderTileColors, iconRenderSize, inkForBackground, insertionIndex, isSeeThrough, lighten,
    limitScale, magnify, markScale, magnifyScale, magnifyShift, maxMagnifyShift, mixBackground,
    overviewProgress, panelLook, scrollToReveal, silhouetteAlpha, silhouetteReadable,
    symbolicLogoNames, viewportLayout}
    from '../../extensions/dock/logic.js';
import {desktopGeometry, menuArea, placeMenu} from '../../extensions/desktop/areas.js';

let failures = 0;
function check(name, condition) {
    if (!condition) {
        failures++;
        printerr(`FAIL: ${name}`);
    } else {
        print(`ok: ${name}`);
    }
}
const near = (a, b) => Math.abs(a - b) < 1e-6;

// --- Magnification
const amount = 0.5, radius = 120;
check('full size at the pointer', near(magnifyScale(0, amount, radius), 1.5));
check('normal size from the radius on', near(magnifyScale(radius, amount, radius), 1) &&
    near(magnifyScale(-500, amount, radius), 1));
check('icon under the pointer does not move', near(magnifyShift(0, amount, radius), 0));
check('shift is symmetric', near(magnifyShift(-40, amount, radius), -magnifyShift(40, amount, radius)));
check('shift saturates', near(magnifyShift(1000, amount, radius), maxMagnifyShift(amount, radius)));

// Items 60 px long, pointer moving across them: order and target kept.
const spans = [0, 60, 120, 180, 240, 300].map(a => [a, a + 60]);
let monotonic = true, targetKept = true, noOverlap = true, grows = true;
for (let p = 0; p <= 360; p += 0.5) {
    const r = magnify(spans, p, amount, radius);
    const moved = spans.map(([a, b], i) => {
        const center = (a + b) / 2 + r[i].shift;
        const half = (b - a) / 2 * r[i].scale;
        return [center - half, center + half];
    });
    for (let i = 1; i < moved.length; i++) {
        if (moved[i][0] < moved[i - 1][0])
            monotonic = false;
        if (moved[i][0] < moved[i - 1][1] - 1e-6)
            noOverlap = false;
    }
    if (r.some(x => x.scale < 1 - 1e-9 || x.scale > 1 + amount + 1e-9))
        grows = false;
    // The item whose span holds the pointer still holds it.
    const i = spans.findIndex(([a, b]) => p >= a && p < b);
    if (i >= 0 && (p < moved[i][0] - 1e-6 || p > moved[i][1] + 1e-6))
        targetKept = false;
}
check('items never swap places', monotonic);
check('the item under the pointer stays under it', targetKept);
check('magnified items do not overlap', noOverlap);
check('scale between normal and strength', grows);
check('progress 0 means no effect', magnify(spans, 100, amount, radius, 0)
    .every(r => r.scale === 1 && r.shift === 0));
check('separator only moves', magnify([[60, 60]], 0, amount, radius)[0].scale === 1);

// --- Overview backdrop
check('dock band: all of it when the overview is gone', dockBandExtension(0) === 1);
check('dock band: none from the window picker on',
    dockBandExtension(1) === 0 && dockBandExtension(2) === 0);
check('dock band: continuous', dockBandExtension(0.5) === 0.5);

// The resulting background over the standard one, per channel, for
// standard S, wallpaper W and color C (both layers stacked as in
// overviewBackdrop.js).
function composite(layers, S, W, C) {
    const w = layers.wallpaper / 255, c = layers.color / 255;
    return C * c + (W * w + S * (1 - w)) * (1 - c);
}
const S = 34, W = 200, C = 120;
check('grid: nothing outside the grid', [0, 0.5, 1].every(v =>
    ['wallpaper', 'color'].every(k => appGridLayers(v, 0.7, true)[k] === 0)));
check('grid: defaults keep the standard background',
    appGridLayers(2, 0, false).wallpaper === 0 && appGridLayers(2, 0, false).color === 0);
check('grid: 100 % transparency shows only the wallpaper',
    Math.abs(composite(appGridLayers(2, 1, true), S, W, C) - W) < 1.5 &&
    Math.abs(composite(appGridLayers(2, 1, false), S, W, C) - W) < 1.5);
check('grid: custom color at 0 % is the color only',
    Math.abs(composite(appGridLayers(2, 0, true), S, W, C) - C) < 1.5);
check('grid: color and transparency blend by the slider only',
    Math.abs(composite(appGridLayers(2, 0.3, true), S, W, C) - (0.3 * W + 0.7 * C)) < 1.5);
check('grid: default color with transparency',
    Math.abs(composite(appGridLayers(2, 0.3, false), S, W, C) - (0.3 * W + 0.7 * S)) < 1.5);
let crossfade = true;
for (let v = 1; v <= 2; v += 0.05) {
    const p = v - 1;
    const want = (1 - p) * S + p * (0.4 * W + 0.6 * C);
    if (Math.abs(composite(appGridLayers(v, 0.4, true), S, W, C) - want) > 1.5)
        crossfade = false;
}
check('grid: a plain crossfade during the transition', crossfade);

// --- Scrollable list
let v = viewportLayout(500, 300, 0);
check('fits: no scrolling', v.overflow === 0 && v.offset === 0);
v = viewportLayout(500, 300, 40);
check('fits: a stale offset is ignored', v.offset === 0);
v = viewportLayout(500, 800, 999);
check('overflow: offset clamped', v.overflow === 300 && v.offset === 300);
check('overflow: negative offset clamped', viewportLayout(500, 800, -5).offset === 0);
check('exactly full: no scrolling', viewportLayout(500, 500, 10).overflow === 0);
check('reveal before', scrollToReveal(100, 160, 200, 300) === 100);
check('reveal after', scrollToReveal(560, 620, 200, 300) === 320);
check('already visible', scrollToReveal(250, 300, 200, 300) === 200);
// List coordinates include scrolling: an item at 700..764 in a list
// scrolled by 400 is under the pointer at viewport 330, list 730.
check('insertion with scrolling', insertionIndex([32, 96, 160, 732], 730) === 3);
check('insertion at the start', insertionIndex([32, 96], 0) === 0);
check('insertion at the end', insertionIndex([32, 96], 500) === 2);

// --- Dock background
const themeColor = {red: 30, green: 30, blue: 30, alpha: 204};
check('no override: theme', backgroundColor(themeColor, null, null) === null);
check('color only keeps the theme alpha',
    backgroundColor(themeColor, '#ff0000', null) === 'rgba(255, 0, 0, 0.8)');
check('transparency only keeps the theme color',
    backgroundColor(themeColor, null, 25) === 'rgba(30, 30, 30, 0.75)');
check('0 % opaque, 100 % transparent', backgroundColor(themeColor, null, 0).endsWith(' 1)') &&
    backgroundColor(themeColor, null, 100).endsWith(' 0)'));
check('both', backgroundColor(themeColor, '#3584e4', 50) === 'rgba(53, 132, 228, 0.5)');
check('invalid color keeps the theme color',
    backgroundColor(themeColor, 'red', 0) === 'rgba(30, 30, 30, 1)');

// --- Ink on the dock background
const dark = {red: 36, green: 31, blue: 49, alpha: 1};
const light = {red: 246, green: 245, blue: 244, alpha: 1};
check('light ink on a dark dock', inkForBackground(dark) === 'light');
check('dark ink on a light dock', inkForBackground(light) === 'dark');
check('saturated mid color: the better contrast',
    inkForBackground({red: 53, green: 132, blue: 228, alpha: 1}) === 'light' &&
    inkForBackground({red: 248, green: 228, blue: 92, alpha: 1}) === 'dark');
check('see-through dock: light ink like labels over the wallpaper',
    inkForBackground({...light, alpha: 0.1}) === 'light' && isSeeThrough({alpha: 0.1}) &&
    !isSeeThrough({alpha: 0.8}));
check('effective background with transparency', effectiveBackground(
    {red: 1, green: 2, blue: 3, alpha: 255}, '#ffffff', 75).alpha === 0.25);

// --- Sharp magnified icons
check('rendered for the magnified size', iconRenderSize(48, 1.5) === 72 &&
    iconRenderSize(48, 2) === 96);
check('no magnification: normal size', iconRenderSize(48, 1) === 48);
check('marks drawn at a whole scale', markScale(1.5) === 2 && markScale(2) === 2 &&
    markScale(2.5) === 3);
check('marks without magnification at their size', markScale(1) === 1 && markScale(0) === 1);
// Whole-edge dock whose list nearly fills the edge (18 items of 64 px in
// a 1204 px view, 52 px to spare): the effect is limited so the magnified
// list fits, and nothing is cut at either end.
{
    const spans = Array.from({length: 18}, (_, i) => [i * 64, i * 64 + 64]);
    const room = 1204 - 18 * 64;
    const radius = 144;
    const used = amountForRoom(1, room, radius);
    check('limited effect for little spare room', near(used, room / radius));
    check('enough room: full effect', amountForRoom(1, 500, radius) === 1);
    let worst = 0;
    for (let pointer = 0; pointer <= 1152; pointer += 8) {
        const results = magnify(spans, pointer, used, radius);
        const shift = fitInView(spans, results, [0, 1204], pointer);
        spans.forEach(([a, b], i) => {
            const center = (a + b) / 2 + results[i].shift + shift;
            const half = (b - a) / 2 * results[i].scale;
            worst = Math.max(worst, -(center - half), center + half - 1204);
        });
    }
    check('magnified list stays in the view', worst < 1e-6);
}
// A scrolled list that cannot keep both ends: the end near the pointer.
{
    const spans = Array.from({length: 30}, (_, i) => [i * 64, i * 64 + 64]);
    const view = [640, 1600];
    const results = magnify(spans, 1580, 1, 144);
    const shift = fitInView(spans, results, view, 1580);
    const last = spans.findLastIndex(([a, b]) => b <= 1600);
    const end = (spans[last][0] + spans[last][1]) / 2 + results[last].shift + shift +
        32 * results[last].scale;
    check('scrolled list: icon near the pointer kept in view', end <= 1600 + 1e-6);
    check('nothing to do inside the view', fitInView([[100, 164]], [{scale: 1, shift: 0}],
        [0, 500], 120) === 0);
}

// Applications button next to the list (48 px icons, 6 px icon padding,
// 2 px margins): no room is kept, the button grows up to the first icon.
// Its icon ends 2 + 6 + 48 = 56 px from its outer end; the first icon of
// the list starts 64 + 8 = 72 px from it, less 2 px of clearance.
check('button grows up to the first icon of the list', near(appsButtonMaxScale(70, 56, 2), 70 / 56));
check('button never grows past the strength', appsButtonMaxScale(500, 56, 1.5) === 1.5);
check('button without room does not grow', appsButtonMaxScale(50, 56, 2) === 1 &&
    appsButtonMaxScale(70, 0, 2) === 1);
check('limited zone: same curve, lower top', near(limitScale(2, 2, 1.25), 1.25) &&
    near(limitScale(1.5, 2, 1.25), 1.125) && near(limitScale(1, 2, 1.25), 1));
check('unlimited zone unchanged', near(limitScale(1.7, 2, 2), 1.7));

// --- Distribution logo
check('symbolic variants tried first', symbolicLogoNames({LOGO: 'fedora-logo-icon', ID: 'fedora'})[0] ===
    'fedora-logo-icon-symbolic');
check('silhouette: white is a hole, color solid', silhouetteAlpha(255, 255, 255, 255) === 0 &&
    silhouetteAlpha(81, 162, 218, 255) === 255 && silhouetteAlpha(0, 0, 0, 255) === 255);
check('silhouette: transparency kept', silhouetteAlpha(0, 0, 0, 0) === 0 &&
    silhouetteAlpha(0, 0, 0, 128) === 128);
check('silhouette: a solid blob is not readable', !silhouetteReadable(new Array(100).fill(255)));
check('silhouette: nothing is not readable', !silhouetteReadable(new Array(100).fill(0)));
check('silhouette: sign with holes is readable',
    silhouetteReadable([...new Array(70).fill(255), ...new Array(30).fill(0)]));

const fedora = distributionLogoNames({LOGO: 'fedora-logo-icon', ID: 'fedora'});
check('fedora logo from os-release first', fedora[0] === 'fedora-logo-icon');
check('no duplicates', new Set(fedora).size === fedora.length);
const debian = distributionLogoNames({LOGO: null, ID: 'debian'});
check('debian emblem from desktop-base', debian.includes('emblem-debian'));
check('generic fallback last', debian.at(-1) === 'distributor-logo');
check('odd ids ignored', distributionLogoNames({ID: '../x'}).length === 1);

// --- Desktop geometry
const monitor = {x: 0, y: 0, width: 1280, height: 800};
const bottomDock = {edge: 'bottom', x: 373, y: 718, width: 533, height: 82};
let g = desktopGeometry(monitor, {x: 0, y: 32, width: 1280, height: 686}, [bottomDock]);
check('reserving dock: its band is given back to the desktop',
    g.area.y === 32 && g.area.height === 768 && g.area.width === 1280);
check('reserving dock: only the dock is excluded', g.exclusions.length === 1 &&
    g.exclusions[0].x === 373 && g.exclusions[0].width === 533 && g.exclusions[0].y === 718);
check('work area kept for popups', g.workArea.y === 32 && g.workArea.height === 686);
g = desktopGeometry(monitor, {x: 0, y: 32, width: 1280, height: 768}, [bottomDock]);
check('hiding dock: same desktop, dock excluded', g.area.height === 768 &&
    g.exclusions.length === 1 && g.workArea.height === 768);
g = desktopGeometry(monitor, {x: 80, y: 32, width: 1200, height: 768},
    [{edge: 'left', x: 0, y: 200, width: 80, height: 400}]);
check('left dock', g.area.x === 0 && g.area.width === 1280 && g.exclusions[0].x === 0 &&
    g.workArea.x === 80);
g = desktopGeometry(monitor, {x: 0, y: 32, width: 1200, height: 768},
    [{edge: 'right', x: 1200, y: 200, width: 80, height: 400}]);
check('right dock', g.area.width === 1280 && g.exclusions[0].x === 1200);
g = desktopGeometry(monitor, {x: 0, y: 32, width: 1280, height: 668}, [bottomDock]);
check('foreign panel above our dock keeps its band', g.area.height === 668 &&
    g.exclusions.length === 0);
g = desktopGeometry(monitor, {x: 76, y: 32, width: 1204, height: 768},
    [{edge: 'left', x: 0, y: 32, width: 76, height: 768}]);
check('whole-edge dock: the area ends at the dock, no empty band', g.area.x === 76 &&
    g.area.width === 1204 && g.exclusions.length === 0);
g = desktopGeometry(monitor, {x: 0, y: 32, width: 1280, height: 768},
    [{edge: 'bottom', x: 0, y: 718, width: 1280, height: 82}]);
check('whole-edge dock that hides: the area ends at it too', g.area.height === 686 &&
    g.exclusions.length === 0);
const second = {x: 1280, y: 0, width: 1024, height: 768};
g = desktopGeometry(second, second, [bottomDock]);
check('dock on another monitor is ignored', g.exclusions.length === 0 && g.area.height === 768);
g = desktopGeometry(second, {x: 1350, y: 0, width: 954, height: 768},
    [{edge: 'left', x: 1280, y: 100, width: 70, height: 300}]);
check('relative to its monitor', g.area.x === 0 && g.area.width === 1024 &&
    g.exclusions[0].x === 0 && g.exclusions[0].y === 100 && g.workArea.x === 70);

const negative = {x: -1920, y: -200, width: 1920, height: 1080};
g = desktopGeometry(negative, {x: -1920, y: -200, width: 1920, height: 1000},
    [{edge: 'bottom', x: -1200, y: 800, width: 500, height: 80}]);
check('negative coordinates: relative to the monitor', g.area.x === 0 && g.area.y === 0 &&
    g.area.height === 1080 && g.exclusions[0].x === 720 && g.exclusions[0].y === 1000);
const upper = {x: 0, y: -800, width: 1280, height: 800};
g = desktopGeometry(upper, upper, [bottomDock]);
check('monitor above: dock of the lower one ignored', g.exclusions.length === 0);

// --- Desktop menu
const area = menuArea({x: 0, y: 0, width: 1280, height: 800}, {x: 0, y: 32, width: 1280, height: 686});
check('menu area: monitor below the top bar, dock band included',
    area.y === 32 && area.height === 768 && area.width === 1280);
const menuSize = {width: 230, height: 230};
let at = placeMenu({x: 200, y: 400}, menuSize, area);
check('menu at the click', at.x === 200 && at.y === 400);
at = placeMenu({x: 200, y: 780}, menuSize, area);
check('click beside the dock: opens upwards from the click', at.x === 200 && at.y === 550);
at = placeMenu({x: 200, y: 700}, menuSize, area);
check('room below the click inside the band is used', at.y === 470);
at = placeMenu({x: 1200, y: 400}, menuSize, area);
check('right edge: slid left just enough', at.x === 1050 && at.y === 400);
at = placeMenu({x: 200, y: 100}, {width: 230, height: 750}, area);
check('fits neither below nor above: slid inside', at.y === 50);
at = placeMenu({x: 200, y: 100}, {width: 230, height: 900}, area);
check('taller than the monitor: starts below the top bar', at.y === 32);
const leftArea = menuArea({x: -1920, y: -200, width: 1920, height: 1080},
    {x: -1850, y: -200, width: 1850, height: 1080});
at = placeMenu({x: -1910, y: 300}, menuSize, leftArea);
check('negative coordinates, left dock band not excluded', at.x === -1910 && at.y === 300);
at = placeMenu({x: -100, y: 870}, menuSize, leftArea);
check('stays on its monitor', at.x === -230 && at.y === 640);

// --- Dock in the overview
const overviewBg = {red: 34, green: 34, blue: 38, alpha: 255};
let look = panelLook({red: 0, green: 0, blue: 0, alpha: 0}, overviewBg);
check('transparent bar: the overview background', look.red === 34 && look.blue === 38 &&
    look.alpha === 1);
look = panelLook({red: 0, green: 0, blue: 0, alpha: 255}, overviewBg);
check('opaque bar: its own color', look.red === 0 && look.alpha === 1);
look = panelLook({red: 255, green: 255, blue: 255, alpha: 128}, overviewBg);
check('translucent bar: composed over the overview', look.red === 145 && look.alpha === 1);
check('full dock: desktop, halfway, window picker', overviewProgress('full', 0) === 0 &&
    overviewProgress('full', 0.5) === 0.5 && overviewProgress('full', 1) === 1);
check('full dock: the grid keeps the bar look, no flash between them',
    overviewProgress('full', 1.3) === 1 && overviewProgress('full', 2) === 1);
check('short dock: its own look on the desktop, in the window picker and in the grid',
    [0, 0.5, 1, 1.5, 2].every(v => overviewProgress('fit', v) === 0));
const desktopDock = {red: 229, green: 165, blue: 10, alpha: 0.7};
const overviewDock = panelLook({red: 0, green: 0, blue: 0, alpha: 0}, overviewBg);
check('mix: desktop look at 0', cssColor(mixBackground(desktopDock, overviewDock, 0)) ===
    'rgba(229, 165, 10, 0.7)');
check('mix: bar look at 1', cssColor(mixBackground(desktopDock, overviewDock, 1)) ===
    'rgba(34, 34, 38, 1)');
const half = mixBackground(desktopDock, overviewDock, 0.5);
check('mix: continuous', half.red === 132 && near(half.alpha, 0.85));
check('ink on the bar look of the default style is light',
    inkForBackground(overviewDock) === 'light' && !isSeeThrough(overviewDock));

// --- Application folder tiles
const tileTheme = {red: 53, green: 51, blue: 57, alpha: 255};
const alphaOf = css => Number(/, ([0-9.]+)\)$/.exec(css)[1]);
check('lighten: gray gets lighter, stays gray', (() => {
    const l = lighten({red: 100, green: 100, blue: 100}, 0.1);
    return l.red === l.green && l.green === l.blue && l.red === 126;
})());
check('lighten: hue kept', (() => {
    const l = lighten({red: 53, green: 132, blue: 228}, 0.04);
    return l.blue > l.green && l.green > l.red && l.blue > 228;
})());
check('lighten: white stays white', lighten({red: 255, green: 255, blue: 255}, 0.1).red === 255);
let tiles = folderTileColors(effectiveBackground(tileTheme, null, null));
check('theme color, opaque: every state opaque', Object.values(tiles).every(c => alphaOf(c) === 1));
check('theme color: normal state unchanged', tiles.normal === 'rgba(53, 51, 57, 1)');
check('hover lighter than normal', /^rgba\((\d+)/.exec(tiles.hover)[1] > 53);
tiles = folderTileColors(effectiveBackground(tileTheme, '#3584e4', null));
check('custom color only: theme alpha kept', tiles.normal === 'rgba(53, 132, 228, 1)');
tiles = folderTileColors(effectiveBackground(tileTheme, null, 60));
check('transparency only: theme color, chosen alpha', tiles.normal === 'rgba(53, 51, 57, 0.4)');
check('states add to the chosen alpha without making the tile opaque',
    alphaOf(tiles.hover) >= 0.5 && alphaOf(tiles.hover) < 0.6 && alphaOf(tiles.active) < 0.7);
tiles = folderTileColors(effectiveBackground(tileTheme, '#3584e4', 100));
check('100 %: tile invisible at rest (alpha kept just above 0 for inset outlines)',
    alphaOf(tiles.normal) > 0 && alphaOf(tiles.normal) < 0.01);
check('100 %: hover and selection clearly visible, not opaque',
    alphaOf(tiles.hover) >= 0.2 && alphaOf(tiles.hover) < 0.3 && alphaOf(tiles.selected) > 0.2 &&
    alphaOf(tiles.selectedActive) <= 0.4);
check('100 %: focus keeps a background, so the focus ring is drawn',
    alphaOf(tiles.focus) > 0 && alphaOf(tiles.focus) < 0.2);
tiles = folderTileColors(effectiveBackground(tileTheme, '#3584e4', 0));
check('0 %: opaque', alphaOf(tiles.normal) === 1 && alphaOf(tiles.hover) === 1);
const themeFolder = effectiveBackground(tileTheme, null, null);
const folderSheet = (color, t) => appGridStylesheet({
    folder: effectiveBackground(tileTheme, color, t), themeFolder});
check('nothing overridden: no stylesheet', appGridStylesheet({themeFolder}) === null);
let sheet = folderSheet('#3584e4', 30);
const selectorsOf = css => css.split('\n').filter(l => l.endsWith('{') || l.endsWith(','))
    .map(l => l.replace(/[ ,{]+$/, ''));
const onlyFolderTiles = css => selectorsOf(css).every(l =>
    /^#overviewGroup (\.deskence-app-grid-ink-dark )?\.apps-scroll-view \.overview-tile\.app-folder(:|$)/
        .test(l));
check('folder background only: rules only for grid folder tiles', onlyFolderTiles(sheet) &&
    onlyFolderTiles(folderSheet('#3584e4', 100)));
check('stylesheet covers hover, focus, selection and drop', [':hover,', ':focus {',
    ':focus:hover {', ':active {', ':selected,', ':checked {', ':drop,'].every(x => sheet.includes(x)));
check('mostly opaque tile: focus ring and drop outline left to the theme',
    !sheet.includes('box-shadow'));
check('drop keeps the accent color', sheet.includes('st-transparentize(-st-accent-color, 0.8)'));
check('name readable on an opaque dark tile', sheet.includes('color: #fafafb;'));
sheet = folderSheet('#f6f5f4', 0);
check('dark name on a light opaque tile', sheet.includes('color: #1e1e20;'));
sheet = folderSheet('#f6f5f4', 80);
check('see-through tile: name keeps the grid color', !/[^-]color: #/.test(sheet));
check('see-through tile: press and selection outlined, light and on a light grid dark',
    /:active,[^{]*\{\n  box-shadow: inset 0 0 0 1px rgba\(255, 255, 255/.test(sheet) &&
    sheet.includes('#overviewGroup .deskence-app-grid-ink-dark .apps-scroll-view .overview-tile.app-folder:active'));
check('see-through tile: hover is a highlight of the surface, never an outline',
    !/:hover[,\s][^{]*\{\n  box-shadow/.test(sheet) && !/:hover \{\n  box-shadow/.test(sheet));
check('see-through tile: the focus ring is not replaced', !/:focus[^{]*\{\n  box-shadow/.test(sheet));
const ruleOf = (css, selector) => {
    const at = css.split('\n}\n').map(r => r.trim()).find(r =>
        r.split(' {')[0].split(',\n').includes(selector));
    return at ? at.split('{\n  ')[1] : null;
};
const F = '#overviewGroup .apps-scroll-view .overview-tile.app-folder';
const A = '#overviewGroup .apps-scroll-view .overview-tile';
const D = '#overviewGroup .app-folder-dialog .overview-tile';
check('folder hover follows the folder background',
    ruleOf(sheet, `${F}:hover`) === `background-color: ${folderTileColors(
        effectiveBackground(tileTheme, '#f6f5f4', 80)).hover};`);
check('folder background only: application tiles untouched', ruleOf(sheet, `${A}:hover`) === null);

// The hover highlight.
const white = (t) => effectiveBackground({red: 0, green: 0, blue: 0, alpha: 255}, '#ffffff', t);
check('composite: transparent layer leaves the base', cssColor(compositeColor(white(100), themeFolder)) ===
    cssColor(themeFolder));
check('composite: opaque layer covers it', cssColor(compositeColor(white(0), themeFolder)) ===
    'rgba(255, 255, 255, 1)');
check('composite: half over opaque', cssColor(compositeColor(white(50), {red: 0, green: 0, blue: 0,
    alpha: 1})) === 'rgba(128, 128, 128, 1)');
check('composite: over see-through', near(compositeColor(white(50), {...themeFolder, alpha: 0.5}).alpha,
    0.75));
const hoverSheet = (hover, folder = null) => appGridStylesheet({hover, folder, themeFolder});
sheet = hoverSheet(white(50));
check('hover: applications in the grid and in an open folder, folders too',
    ruleOf(sheet, `${A}:hover`)?.startsWith('background-color: rgba(255, 255, 255, 0.5)') &&
    ruleOf(sheet, `${D}:hover`) === ruleOf(sheet, `${A}:hover`) &&
    ruleOf(sheet, `${A}:focus:hover`) === ruleOf(sheet, `${A}:hover`) &&
    ruleOf(sheet, `${F}:hover`) !== null);
check('hover only: folder tiles keep the theme at rest and focus',
    ruleOf(sheet, F) === null && ruleOf(sheet, `${F}:focus`) === null &&
    ruleOf(sheet, `${F}:insensitive`) === null);
check('hover only: nothing outside the grid and the open folder (dock, desktop)',
    selectorsOf(sheet).every(l => l.startsWith('#overviewGroup .apps-scroll-view ') ||
        l.startsWith('#overviewGroup .deskence-app-grid-ink-dark .apps-scroll-view ') ||
        l.startsWith('#overviewGroup .app-folder-dialog ')));
check('hover on a folder is drawn over its background',
    ruleOf(sheet, `${F}:hover`).startsWith(`background-color: ${cssColor(compositeColor(white(50),
        themeFolder))}`));
check('hover: focus ring, press, selection and drop kept apart',
    ruleOf(sheet, `${A}:focus`) === null && !/box-shadow/.test(sheet) &&
    ruleOf(sheet, `${A}:active:hover`) !== ruleOf(sheet, `${A}:hover`) &&
    ruleOf(sheet, `${A}:selected:hover`) !== null &&
    ruleOf(sheet, `${A}:drop:hover`).includes('-st-accent-color') &&
    ruleOf(sheet, `${F}:drop:hover`).includes('-st-accent-color') &&
    ruleOf(sheet, `${F}:active:hover`) !== ruleOf(sheet, `${F}:hover`));
sheet = hoverSheet(white(100), effectiveBackground(tileTheme, '#3584e4', 30));
check('100 %: folder looks under the pointer as at rest',
    ruleOf(sheet, `${F}:hover`).startsWith(`background-color: ${cssColor(
        effectiveBackground(tileTheme, '#3584e4', 30))}`));
check('100 %: applications keep a background just above 0, so the focus ring is drawn',
    /rgba\(255, 255, 255, 0\.004\)/.test(ruleOf(sheet, `${A}:focus:hover`)));
check('100 %: press still shows', alphaOf(/rgba\([^)]*\)/.exec(ruleOf(sheet,
    `${A}:active:hover`))[0]) >= 0.1);
sheet = hoverSheet(white(0));
check('0 %: opaque highlight, names dark on white',
    ruleOf(sheet, `${A}:hover`) === 'background-color: rgba(255, 255, 255, 1); color: #1e1e20;');
sheet = hoverSheet(effectiveBackground(tileTheme, '#1c71d8', 0));
check('0 %: light names on a dark highlight', ruleOf(sheet, `${A}:hover`).endsWith('color: #fafafb;'));
const orange = t => effectiveBackground(tileTheme, '#e5a50a', t);
sheet = hoverSheet(orange(50));
check('half transparent highlight: name color for what is seen over the dark grid',
    ruleOf(sheet, `${A}:hover`).endsWith('color: #fafafb;') &&
    ruleOf(sheet, `#overviewGroup .deskence-app-grid-ink-dark .apps-scroll-view .overview-tile:hover`) ===
        'color: #1e1e20;');
check('application rules come before folder rules (same specificity as the light grid variant)',
    sheet.indexOf('.deskence-app-grid-ink-dark') < sheet.indexOf('.overview-tile.app-folder'));
sheet = hoverSheet(white(80));
check('mostly transparent highlight: application names keep the grid color',
    !/[^-]color: #/.test(ruleOf(sheet, `${A}:hover`)));
sheet = hoverSheet(white(40), effectiveBackground(tileTheme, '#3584e4', 0));
check('custom folder and custom hover: folder background kept at rest, highlight over it',
    ruleOf(sheet, F).startsWith('background-color: rgba(53, 132, 228, 1)') &&
    ruleOf(sheet, `${F}:hover`).startsWith(`background-color: ${cssColor(compositeColor(white(40),
        effectiveBackground(tileTheme, '#3584e4', 0)))}`));
check('the hover rule of folders is more specific than that of applications',
    F.startsWith(A) && F.length > A.length);

const hoverOf = (color, t) => folderTileColors(effectiveBackground(tileTheme, color, t)).hover;
const rgbOf = css => /rgba\((\d+), (\d+), (\d+)/.exec(css).slice(1).map(Number);
check('dark color: hover lighter', rgbOf(hoverOf('#1c71d8', 50))[0] > 0x1c);
check('opaque light color: hover darker, not lost in white', rgbOf(hoverOf('#f6f5f4', 0))[0] < 0xf6);
// What a tile looks like over the dark overview background.
const seen = css => {
    const [r] = rgbOf(css);
    const a = alphaOf(css);
    return r * a + 34 * (1 - a);
};
check('translucent light color: hover clearly visible over the overview',
    seen(hoverOf('#f6f5f4', 50)) - seen(folderTileColors(
        effectiveBackground(tileTheme, '#f6f5f4', 50)).normal) >= 25);
check('hover keeps the hue of the chosen color', (() => {
    const [r, g, b] = rgbOf(hoverOf('#3584e4', 50));
    return b > g && g > r;
})());
const lighterStep = rgbOf(hoverOf('#3584e4', 0))[0] - 0x35;
check('opaque hover step clearly visible (more than GNOME 4 %)', lighterStep >= 30);

if (failures)
    System.exit(1);
