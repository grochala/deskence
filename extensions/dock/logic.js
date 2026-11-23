// SPDX-License-Identifier: GPL-3.0-or-later
//
// Pure helpers of the dock, unit tested with gjs (tests/unit/test_geometry.js).

// --- Magnification -------------------------------------------------------
//
// Icons near the pointer grow with a smooth cosine bump: full size at the
// pointer, normal size from `radius` on. To make room, every icon moves away
// from the pointer by the extra size accumulated between the pointer and its
// center (the integral of the bump). That mapping is monotonic and leaves the
// pointer position fixed, so the icon under the pointer stays under it and
// the icons never swap places: no target moves out from under the cursor and
// nothing jitters. Only transforms change; the dock layout stays as it is.

// amount: extra scale at the pointer (strength - 1).
export function magnifyScale(distance, amount, radius) {
    const u = Math.min(Math.abs(distance) / radius, 1);
    return 1 + amount * (Math.cos(Math.PI * u) + 1) / 2;
}

export function magnifyShift(distance, amount, radius) {
    const a = Math.min(Math.abs(distance), radius);
    return Math.sign(distance) * amount / 2 * (a + radius / Math.PI * Math.sin(Math.PI * a / radius));
}

// The largest distance anything moves along the dock.
export function maxMagnifyShift(amount, radius) {
    return amount * radius / 2;
}

// spans: [start, end] of every item along the dock axis. progress (0..1)
// fades the whole effect in and out. Returns [{scale, shift}] in the same
// order. Each item scales to exactly the length its span gets after the
// mapping, so magnified items tile without overlapping and the item under
// the pointer always contains it.
export function magnify(spans, pointer, amount, radius, progress = 1) {
    const map = x => x + progress * magnifyShift(x - pointer, amount, radius);
    return spans.map(([start, end]) => {
        const length = end - start;
        const center = (start + end) / 2;
        if (length < 1e-6)
            return {scale: 1, shift: map(center) - center};
        const a = map(start), b = map(end);
        return {scale: (b - a) / length, shift: (a + b) / 2 - center};
    });
}

// Strongest effect (amount) that keeps a magnified list within room spare
// pixels: the list grows by at most amount * radius.
export function amountForRoom(amount, room, radius) {
    return Math.min(amount, Math.max(0, room) / Math.max(radius, 1));
}

// Shift that keeps magnified items inside a list view clipped along the
// dock. spans: [start, end] of the items; results: magnify() for them;
// view: [low, high] visible part. Only items entirely visible at normal size
// are kept in; items already cut by scrolling stay cut, so hovering never
// scrolls the list. When both ends cannot be kept, the end near the
// pointer is. Returns the shift to add to every result.
export function fitInView(spans, results, [low, high], pointer) {
    const inView = spans.map((s, i) => i).filter(i => spans[i][1] > low && spans[i][0] < high);
    if (inView.length === 0)
        return 0;
    const edge = i => {
        const center = (spans[i][0] + spans[i][1]) / 2 + results[i].shift;
        const half = (spans[i][1] - spans[i][0]) / 2 * results[i].scale;
        return [center - half, center + half];
    };
    const first = inView[0], last = inView.at(-1);
    const tolerance = 0.5;
    const startEdge = edge(first)[0];
    const endEdge = edge(last)[1];
    let correction = 0;
    if (startEdge < low && spans[first][0] >= low - tolerance)
        correction = low - startEdge;
    if (endEdge + correction > high && spans[last][1] <= high + tolerance &&
        (correction === 0 || pointer > (low + high) / 2))
        correction = high - endEdge;
    return correction;
}

// --- Applications button icon --------------------------------------------

// Icon names that may hold the logo of the running distribution, most
// specific first. osInfo: values of /etc/os-release ("LOGO", "ID").
//  - Fedora: LOGO=fedora-logo-icon (fedora-logos);
//  - Debian: no LOGO; desktop-base installs emblem-debian.
export function distributionLogoNames(osInfo) {
    const names = [];
    const logo = osInfo.LOGO?.trim();
    if (logo)
        names.push(logo);
    const id = osInfo.ID?.trim().toLowerCase();
    if (id && /^[a-z0-9._-]+$/.test(id))
        names.push(`${id}-logo-icon`, `emblem-${id}`, `${id}-logo`);
    names.push('distributor-logo');
    return [...new Set(names)];
}

// Symbolic (single color) variants of those names, tried before deriving a
// silhouette from a colored logo.
export function symbolicLogoNames(osInfo) {
    return distributionLogoNames(osInfo).map(n => `${n}-symbolic`);
}

// Coverage of one pixel of a colored logo in its single color silhouette:
// light parts become holes, dark and saturated parts solid. A logo drawn
// as a light sign on a colored disc (Fedora) keeps the sign as a cut-out; a
// colored sign on a transparent background (Debian) keeps its shape.
// r, g, b, a: 0..255. Returns 0..255.
export function silhouetteAlpha(r, g, b, a) {
    const luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
    // Everything up to 60 % luminance is solid, white is empty.
    return Math.round(a * Math.min(1, Math.max(0, (1 - luminance) * 2.5)));
}

// Whether a silhouette is a readable sign rather than a solid blob or
// nearly nothing: alphas is the coverage of the pixels inside the logo's
// bounding box. A recognisable sign has a fair share of both solid and
// empty pixels.
export function silhouetteReadable(alphas) {
    if (alphas.length === 0)
        return false;
    let solid = 0, empty = 0;
    for (const value of alphas) {
        if (value >= 160)
            solid++;
        else if (value < 64)
            empty++;
    }
    return solid / alphas.length >= 0.15 && empty / alphas.length >= 0.1;
}

// Size (logical pixels) icons are rendered at: the largest size they are
// shown at, so magnified icons stay sharp instead of enlarging a small
// texture. The texture cache adds the monitor scale on top.
export function iconRenderSize(size, magnifyStrength) {
    return Math.ceil(size * Math.max(1, magnifyStrength));
}

// How many times larger the marks of dock items (window dots, folder
// marker, counter) are drawn than they look at rest: the largest
// magnification, rounded up to a whole number, so their sizes stay whole
// pixels as shown.
export function markScale(magnifyStrength) {
    return Math.ceil(Math.max(1, magnifyStrength));
}

// Window dots, in logical pixels as shown: all the same round size; the
// focused application has them in another color.
export const DOT_SIZE = 4;
export const DOT_SPACING = 3;

// The folder marker: a triangle the width of two dots, a little taller
// than one, pointing into the screen (width along the dock edge).
export const MARKER_WIDTH = 8;
export const MARKER_HEIGHT = 5;

// How large the applications button may grow when it magnifies on its own
// (whole-edge dock, scrolled list). It grows from its outer end towards the
// list, and neither of them moves to make room, so there is no space kept
// free for it: its icon may only grow up to the first icon of the list.
// room: distance from the button's outer end to where that icon starts;
// iconEnd: distance from the outer end to the far edge of the button's own
// icon at normal size. Returns a scale between 1 and the strength.
export function appsButtonMaxScale(room, iconEnd, magnifyStrength) {
    const strength = Math.max(1, magnifyStrength);
    if (!(iconEnd > 0) || !(room > iconEnd))
        return 1;
    return Math.min(strength, room / iconEnd);
}

// Scale of a zone with a limited growth: the same smooth effect, reaching
// at most maxScale where it would otherwise reach the full strength.
export function limitScale(scale, magnifyStrength, maxScale) {
    const amount = magnifyStrength - 1;
    if (amount <= 0 || maxScale >= magnifyStrength)
        return scale;
    return 1 + (scale - 1) * Math.max(0, maxScale - 1) / amount;
}

// --- Window previews ---------------------------------------------------------

// Thumbnail size in the window previews panel. count previews in a row (a
// column for a side dock) with room logical pixels along the dock. Each
// takes itemExtra besides its thumbnail along the row, and titleExtra more
// in a column (the title is under the thumbnail). Thumbnails shrink, down to
// minWidth wide, to fit; beyond that the row scrolls. Returns
// {width, height, scroll}, whole pixels.
export function previewLayout(count, room, {width, height, minWidth, vertical, itemExtra = 0,
    titleExtra = 0}) {
    const n = Math.max(1, count);
    const along = (vertical ? height + titleExtra : width) + itemExtra;
    let factor = 1;
    if (n * along > room) {
        const fixed = itemExtra + (vertical ? titleExtra : 0);
        const base = vertical ? height : width;
        factor = Math.max(minWidth / width, (room / n - fixed) / base);
        factor = Math.min(1, factor);
    }
    const w = Math.floor(width * factor);
    const h = Math.floor(height * factor);
    const used = n * ((vertical ? h + titleExtra : w) + itemExtra);
    return {width: w, height: h, scroll: used > room};
}

// --- Overview backdrop -----------------------------------------------------
//
// value: the overview state (0 hidden, 1 window picker, 2 application grid).

// How much of the band a space-reserving dock takes from the work area is
// added to the workspace preview: all of it when the overview is gone, none
// from the window picker on. The band is part of the preview, so it moves
// and scales with it.
export function dockBandExtension(value) {
    return Math.min(Math.max(1 - value, 0), 1);
}

// Opacities (0..255) of the layers under the application grid, over the
// solid overview background: the wallpaper and, with a custom color, a
// layer of that color above it. transparency: 0..1; customColor: whether
// the color layer is used. With p the progress towards the application
// grid, the result is the plain crossfade
//   (1 - p) * standard + p * (t * wallpaper + (1 - t) * color),
// so the standard background is untouched outside the grid and the alpha
// of the color comes only from the transparency setting.
export function appGridLayers(value, transparency, customColor) {
    const p = Math.min(Math.max(value - 1, 0), 1);
    const t = Math.min(Math.max(transparency, 0), 1);
    if (!customColor)
        return {wallpaper: Math.round(255 * p * t), color: 0};
    const color = p * (1 - t);
    const rest = 1 - color;
    const wallpaper = rest > 1e-9 ? p * t / rest : 0;
    return {wallpaper: Math.round(255 * wallpaper), color: Math.round(255 * color)};
}

// --- Scrollable item list --------------------------------------------------

// Where the item list goes inside the space the dock leaves for it. The
// list always starts at the start (top, or left): spare room stays after
// it, between the list and an applications button at the other end.
// viewLength: that space; listLength: the list's natural length; offset:
// the wanted scroll offset. Returns {overflow, offset}: how far the list
// can scroll, and the scroll offset kept within that.
export function viewportLayout(viewLength, listLength, offset) {
    const overflow = Math.max(0, Math.round(listLength - viewLength));
    return {overflow, offset: overflow > 0 ? Math.min(Math.max(offset, 0), overflow) : 0};
}

// Scroll offset that shows the span [a, b] of the list (list coordinates)
// entirely, moving as little as possible.
export function scrollToReveal(a, b, offset, viewLength) {
    if (a < offset)
        return a;
    if (b > offset + viewLength)
        return Math.min(a, b - viewLength);
    return offset;
}

// Position among the items under the pointer while dragging: the number of
// item centers before it. centers are in list coordinates; pointer too, so
// the scroll offset is already accounted for.
export function insertionIndex(centers, pointer) {
    return centers.filter(c => pointer > c).length;
}

// --- Dock background -------------------------------------------------------

// The background with our overrides. theme: {red, green, blue, alpha}
// (0..255) from the current style; color: "#rrggbb" or null to keep the
// theme color; transparency: 0..100 or null to keep the theme alpha.
// Returns {red, green, blue, alpha} with alpha 0..1.
export function effectiveBackground(theme, color, transparency) {
    let {red, green, blue} = theme;
    const match = color !== null && /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(color);
    if (match)
        [red, green, blue] = match.slice(1).map(h => parseInt(h, 16));
    const alpha = transparency === null
        ? theme.alpha / 255
        : 1 - Math.min(Math.max(transparency, 0), 100) / 100;
    return {red, green, blue, alpha};
}

// The background color as CSS, or null when nothing is overridden.
export function backgroundColor(theme, color, transparency) {
    if (color === null && transparency === null)
        return null;
    const {red, green, blue, alpha} = effectiveBackground(theme, color, transparency);
    return `rgba(${red}, ${green}, ${blue}, ${Number(alpha.toFixed(3))})`;
}

// In the overview (window picker and application grid alike) the dock
// takes the look of the top bar, so the two read as one frame around the
// overview. The top bar is drawn over the overview background (in the
// default styles it is transparent there, and the application grid's own
// wallpaper or color stops below it), so its look is the bar's background
// composed over the overview's. panel and overview: {red, green, blue,
// alpha} (0..255) from the current style. Returns an opaque color with
// alpha 0..1 like effectiveBackground().
export function panelLook(panel, overview) {
    const a = panel.alpha / 255;
    const over = (top, bottom) => Math.round(top * a + bottom * (1 - a));
    return {
        red: over(panel.red, overview.red),
        green: over(panel.green, overview.green),
        blue: over(panel.blue, overview.blue),
        alpha: 1,
    };
}

// How far the dock is towards the overview look, 0..1, for its length
// ("full" or "fit") and the overview state value (0 hidden, 1 window
// picker, 2 application grid). Only a dock along the whole edge takes the
// top bar's look - it frames the overview with the bar; a short dock keeps
// its own background, shape and the user's color everywhere. The full dock
// follows the transition to the window picker and stays there in the grid,
// so moving between the two never brings the desktop look back.
export function overviewProgress(length, value) {
    if (length !== 'full')
        return 0;
    return Math.min(Math.max(value, 0), 1);
}

// The dock background between its desktop look and the overview look;
// both {red, green, blue, alpha} with alpha 0..1. Returns the same form.
export function mixBackground(desktop, overview, progress) {
    const t = Math.min(Math.max(progress, 0), 1);
    const mix = (a, b) => a + (b - a) * t;
    return {
        red: Math.round(mix(desktop.red, overview.red)),
        green: Math.round(mix(desktop.green, overview.green)),
        blue: Math.round(mix(desktop.blue, overview.blue)),
        alpha: mix(desktop.alpha, overview.alpha),
    };
}

export function cssColor({red, green, blue, alpha}) {
    return `rgba(${red}, ${green}, ${blue}, ${Number(alpha.toFixed(3))})`;
}

// Below this opacity the wallpaper decides what is behind the dock.
const SEE_THROUGH_ALPHA = 0.4;

export function isSeeThrough({alpha}) {
    return alpha < SEE_THROUGH_ALPHA;
}

// Foreground ("ink") for symbolic icons, indicators and highlights on a
// background: "dark" on light colors, "light" on dark ones. On a mostly
// transparent background the wallpaper could be anything; like the labels
// GNOME draws over the wallpaper, the ink is then light (with a shadow).
export function inkForBackground({red, green, blue, alpha}) {
    if (isSeeThrough({alpha}))
        return 'light';
    const linear = c => {
        const v = c / 255;
        return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
    };
    const luminance = 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue);
    // Like GNOME, which keeps white on its blue accent, light ink is kept
    // on mid colors; only clearly light colors (light grays, yellow, pale
    // tones) get dark ink.
    return luminance > 0.4 ? 'dark' : 'light';
}

// --- Application folder tiles ----------------------------------------------

// Lightens {red, green, blue} (0..255) by amount (-1..1) of HSL
// lightness, like st-lighten() in the GNOME Shell theme; a negative amount
// darkens.
export function lighten({red, green, blue}, amount) {
    const [r, g, b] = [red, green, blue].map(c => c / 255);
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    let h = 0, s = 0;
    const l = (max + min) / 2;
    if (max !== min) {
        const d = max - min;
        s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
        if (max === r)
            h = (g - b) / d + (g < b ? 6 : 0);
        else if (max === g)
            h = (b - r) / d + 2;
        else
            h = (r - g) / d + 4;
        h /= 6;
    }
    const lightness = Math.min(Math.max(l + amount, 0), 1);
    const q = lightness < 0.5 ? lightness * (1 + s) : lightness + s - lightness * s;
    const p = 2 * lightness - q;
    const channel = t => {
        t = (t + 1) % 1;
        if (t < 1 / 6)
            return p + (q - p) * 6 * t;
        if (t < 1 / 2)
            return q;
        if (t < 2 / 3)
            return p + (q - p) * (2 / 3 - t) * 6;
        return p;
    };
    const [nr, ng, nb] = s === 0
        ? [lightness, lightness, lightness]
        : [channel(h + 1 / 3), channel(h), channel(h - 1 / 3)];
    return {red: Math.round(nr * 255), green: Math.round(ng * 255), blue: Math.round(nb * 255)};
}

// Tile states: how much lighter (or, on a light color, darker) each one
// is, and how much of the way to opaque it goes. The alpha of the tile
// comes only from the transparency setting; a state adds to it, so hover
// and selection are clearly visible in the chosen color even on a fully
// transparent tile, without turning it into an opaque block. Focus gets a
// little background too: St paints the theme's focus ring (an inset box
// shadow) only with a background.
const FOLDER_STATES = {
    normal: [0, 0],
    focus: [0, 0.12],
    hover: [0.08, 0.22],
    active: [0.14, 0.32],
    selected: [0.12, 0.28],
    selectedHover: [0.16, 0.34],
    selectedActive: [0.2, 0.4],
};

// From this alpha on, a tile's own color is what is seen.
const OPAQUE_TILE = 0.85;

// Lowest alpha of a tile background: invisible, but enough for St to paint
// the inset box shadows the theme draws with it (the outline of the high
// contrast style, the focus ring).
const MIN_TILE_ALPHA = 1 / 255;

// A tile state's color from the tile color: amount lighter (or, on a
// light color opaque enough to be what is seen, darker) and raise of the
// way to opaque more. On a translucent light tile darkening the color
// would cancel out the added alpha over the dark overview.
function stateColor(base, amount, raise) {
    const alpha = Math.min(Math.max(base.alpha, 0), 1);
    const darker = alpha >= OPAQUE_TILE && inkForBackground({...base, alpha: 1}) === 'dark';
    const {red, green, blue} = lighten(base, (darker ? -1 : 1) * amount);
    return {red, green, blue, alpha: Math.max(alpha + (1 - alpha) * raise, MIN_TILE_ALPHA)};
}

// Background colors of a folder tile for its states, as CSS. base:
// {red, green, blue, alpha} with alpha 0..1, see effectiveBackground().
export function folderTileColors(base) {
    const colors = {};
    for (const [state, [amount, raise]] of Object.entries(FOLDER_STATES))
        colors[state] = cssColor(stateColor(base, amount, raise));
    return colors;
}

// What is seen of layer drawn over base (both {red, green, blue, alpha},
// alpha 0..1), as one color of the same form.
export function composite(layer, base) {
    const top = Math.min(Math.max(layer.alpha, 0), 1);
    const below = Math.min(Math.max(base.alpha, 0), 1) * (1 - top);
    const alpha = top + below;
    if (alpha <= 0)
        return {red: base.red, green: base.green, blue: base.blue, alpha: 0};
    const mix = (a, b) => Math.round((a * top + b * below) / alpha);
    return {
        red: mix(layer.red, base.red),
        green: mix(layer.green, base.green),
        blue: mix(layer.blue, base.blue),
        alpha,
    };
}

// Press and selection under the pointer, from the hover highlight: a step
// further, like the folder states.
const HOVER_STATES = {
    active: [0.06, 0.12],
    selected: [0.04, 0.08],
};

const INK = {light: '#fafafb', dark: '#1e1e20'};
// What application tiles are drawn over: the dark background of the grid
// and of an open folder in every GNOME style, or a light custom grid
// color (overviewBackdrop.js marks it with .deskence-app-grid-ink-dark).
const DARK_GRID = {red: 34, green: 34, blue: 38, alpha: 1};
const LIGHT_GRID = {red: 246, green: 245, blue: 244, alpha: 1};
const DROP = 'background-color: st-transparentize(-st-accent-color, 0.8);';

// Folder tiles only exist in the application grid (inside
// .apps-scroll-view); the panel of an open folder is an .app-folder-dialog
// elsewhere. Folder tiles are also .overview-tile; naming both classes
// makes their rules win over those of other tiles.
const FOLDER_TILE = '#overviewGroup .apps-scroll-view .overview-tile.app-folder';
const APP_TILES = [
    '#overviewGroup .apps-scroll-view .overview-tile',
    '#overviewGroup .app-folder-dialog .overview-tile',
];

// The stylesheet of the application grid tiles, or null when nothing is
// overridden; the one place their colors are worked out. All colors are
// {red, green, blue, alpha} with alpha 0..1 (effectiveBackground()):
//   folder       background of folder tiles, or null for the theme's
//   hover        highlight under the pointer (application tiles in the
//                grid and in an open folder, folder tiles), or null for
//                the theme's
//   themeFolder  the theme's folder tile background, what the highlight
//                is drawn over when folder is null
// The tile background, the highlight, keyboard focus, press and drop are
// separate: the highlight is a layer over the tile background (with 100 %
// transparency the tile looks as it does at rest), the theme's focus ring
// (an inset box shadow, !important) and drop outline stay, and press,
// selection and drop keep their own colors. Every rule is more specific
// than the theme's, so the states combined with :hover are written out
// too. A text color is only given on a background opaque enough to decide
// what is behind the name, chosen for what is seen there (the highlight
// over the tile or the grid); otherwise the name keeps the grid's color.
// Application rules come first: a rule of a folder tile is as specific as
// the variant for a light grid and has to come later to win.
// Folder tiles mostly see-through are outlined when pressed or selected,
// light or - on a light application grid background (overviewBackdrop.js)
// - dark, so those read on any wallpaper; hover is only the highlight.
export function appGridStylesheet({folder = null, hover = null, themeFolder}) {
    if (!folder && !hover)
        return null;
    let rules = [];
    const add = (selectors, body) => rules.push([selectors.join(',\n'), body]);
    const ink = color => isSeeThrough(color) ? '' : ` color: ${INK[inkForBackground(color)]};`;
    const visible = color => ({...color, alpha: Math.max(color.alpha, MIN_TILE_ALPHA)});
    const states = (tile, list) => list.map(state => `${tile}${state}`);
    const selected = state => [':highlighted', ':selected', ':checked'].map(s => `${s}${state}`);

    // Application tiles, in the grid and in an open folder: nothing at
    // rest, the highlight under the pointer.
    const appRules = [];
    if (hover) {
        const addApp = (selectors, body) => appRules.push([selectors.join(',\n'), body]);
        const layer = visible(hover);
        const active = stateColor(hover, ...HOVER_STATES.active);
        const chosen = stateColor(hover, ...HOVER_STATES.selected);
        const over = (color, grid) => isSeeThrough(color) ? '' : ink(composite(color, grid));
        const lightGrid = APP_TILES[0].replace('#overviewGroup ',
            '#overviewGroup .deskence-app-grid-ink-dark ');
        const looks = [
            [states => APP_TILES.flatMap(t => states.map(x => `${t}${x}`)), DARK_GRID, true],
            [states => states.map(x => `${lightGrid}${x}`), LIGHT_GRID, false],
        ];
        for (const [selectors, grid, background] of looks) {
            for (const [list, color] of [
                [[':hover', ':focus:hover'], layer],
                [[':active:hover'], active],
                [selected(':hover'), chosen],
            ]) {
                const text = over(color, grid);
                if (background)
                    addApp(selectors(list), `background-color: ${cssColor(color)};${text}`);
                else if (text)
                    addApp(selectors(list), text.trim());
            }
        }
        addApp(APP_TILES.map(t => `${t}:drop:hover`), DROP);
    }

    // Folder tiles.
    const base = folder ?? themeFolder;
    const c = folderTileColors(base);
    const T = FOLDER_TILE;
    let hoverBody = `background-color: ${c.hover};`;
    if (hover) {
        const seen = visible(composite(hover, base));
        hoverBody = `background-color: ${cssColor(seen)};${ink(seen)}`;
    }
    if (folder) {
        add([T], `background-color: ${c.normal};${ink(folder)}`);
        add([`${T}:insensitive`], `background-color: ${c.normal};`);
        add([`${T}:focus`], `background-color: ${c.focus};`);
    }
    add(states(T, [':hover', ':focus:hover']), hoverBody);
    if (folder)
        add([`${T}:active`], `background-color: ${c.active};`);
    add([`${T}:active:hover`], `background-color: ${c.active};`);
    if (folder) {
        add([`${T}:active:focus`], `background-color: ${c.active};`);
        add(states(T, selected('')), `background-color: ${c.selected};`);
    }
    add(states(T, selected(':hover')), `background-color: ${c.selectedHover};`);
    if (folder)
        add(states(T, selected(':active')), `background-color: ${c.selectedActive};`);
    add(states(T, [':drop', ':drop:hover']), DROP);
    if (folder && isSeeThrough(folder)) {
        const outlined = [':active', ':highlighted', ':selected', ':checked'];
        for (const [grid, color] of [['', 'rgba(255, 255, 255, 0.3)'],
            ['.deskence-app-grid-ink-dark ', 'rgba(0, 0, 0, 0.25)']]) {
            const tile = `#overviewGroup ${grid}.apps-scroll-view .overview-tile.app-folder`;
            add(states(tile, outlined), `box-shadow: inset 0 0 0 1px ${color};`);
        }
    }

    rules = [...appRules, ...rules];
    return rules.map(([selector, body]) => `${selector} {\n  ${body}\n}\n`).join('\n');
}
