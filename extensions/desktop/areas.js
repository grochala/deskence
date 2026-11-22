// SPDX-License-Identifier: GPL-3.0-or-later
//
// Geometry of the interactive desktop of a monitor. Pure functions, unit
// tested with gjs (tests/unit/test_geometry.js).
//
// The work area (what maximized windows get) and the desktop icons are not
// the same: a dock reserving space removes a whole band along its edge from
// the work area, but on the desktop only the dock itself is in the way.
// Beside a dock shorter than the edge the desktop stays usable for icons,
// clicks and rubberband selection. A dock as long as the edge simply ends
// the area.

// The Deskence dock marks the actor that holds it with this style class
// plus "deskence-dock-edge-<left|bottom|right>". The holder keeps the
// dock's place while the dock slides out of view, so icons never end up
// under a dock that hides.
export const DOCK_HOLDER_CLASS = 'deskence-dock-holder';
export const DOCK_EDGES = ['left', 'bottom', 'right'];

function intersects(a, b) {
    return a.x < b.x + b.width && a.x + a.width > b.x &&
        a.y < b.y + b.height && a.y + a.height > b.y;
}

function relative(rect, monitor) {
    return {x: rect.x - monitor.x, y: rect.y - monitor.y, width: rect.width, height: rect.height};
}

// monitor, workArea: {x, y, width, height} in stage coordinates.
// docks: [{edge, x, y, width, height}] of our docks.
// Returns, relative to the monitor's top-left corner:
//   area        where icons may be: the work area, given back the bands our
//               docks reserve (other panels and docks keep theirs);
//   exclusions  the dock rectangles inside the area;
//   workArea    the work area itself (the shell keeps popups inside it).
export function desktopGeometry(monitor, workArea, docks) {
    let left = Math.max(monitor.x, workArea.x);
    let top = Math.max(monitor.y, workArea.y);
    let right = Math.min(monitor.x + monitor.width, workArea.x + workArea.width);
    let bottom = Math.min(monitor.y + monitor.height, workArea.y + workArea.height);
    const clippedWorkArea = {x: left, y: top, width: right - left, height: bottom - top};

    const exclusions = [];
    for (const dock of docks) {
        if (dock.width <= 0 || dock.height <= 0 || !intersects(dock, monitor))
            continue;
        // A dock as long as its edge leaves nothing of its band: the area
        // simply ends at the dock, so the grid starts right next to it.
        const whole = dock.edge === 'bottom'
            ? dock.x <= left && dock.x + dock.width >= right
            : dock.y <= top && dock.y + dock.height >= bottom;
        if (whole) {
            if (dock.edge === 'left')
                left = Math.max(left, dock.x + dock.width);
            else if (dock.edge === 'right')
                right = Math.min(right, dock.x);
            else
                bottom = Math.min(bottom, dock.y);
            continue;
        }
        // A dock reserving space ends exactly where the work area does.
        if (dock.edge === 'left' && left === dock.x + dock.width)
            left = monitor.x;
        else if (dock.edge === 'right' && right === dock.x)
            right = monitor.x + monitor.width;
        else if (dock.edge === 'bottom' && bottom === dock.y)
            bottom = monitor.y + monitor.height;
        exclusions.push(dock);
    }

    if (right <= left || bottom <= top) {
        const whole = {x: 0, y: 0, width: monitor.width, height: monitor.height};
        return {area: whole, exclusions: [], workArea: whole};
    }
    const area = {x: left, y: top, width: right - left, height: bottom - top};
    return {
        area: relative(area, monitor),
        exclusions: exclusions.filter(d => intersects(d, area)).map(d => relative(d, monitor)),
        workArea: relative(clippedWorkArea, monitor),
    };
}

// Where a context menu goes: its top-left corner at the clicked point, as
// GTK and the shell open context menus. Only when it does not fit is it
// moved: flipped above the point when there is room there, otherwise slid
// back inside; horizontally slid left as far as needed. point {x, y},
// size {width, height}, area {x, y, width, height}: the part of the clicked
// monitor menus may use. Returns the top-left corner {x, y}.
export function placeMenu(point, size, area) {
    const right = area.x + area.width;
    const bottom = area.y + area.height;
    let x = point.x;
    let y = point.y;
    if (x + size.width > right)
        x = right - size.width;
    if (y + size.height > bottom)
        y = point.y - size.height >= area.y ? point.y - size.height : bottom - size.height;
    return {x: Math.max(x, area.x), y: Math.max(y, area.y)};
}

// The part of a monitor a desktop menu may use: the monitor below the
// struts at its top (the top bar). Docks and their bands are not excluded:
// menus open above them like anywhere else.
export function menuArea(monitor, workArea) {
    const top = Math.min(Math.max(workArea.y, monitor.y), monitor.y + monitor.height);
    return {x: monitor.x, y: top, width: monitor.width, height: monitor.y + monitor.height - top};
}
