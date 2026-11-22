# SPDX-License-Identifier: GPL-3.0-or-later
"""Available desktop areas, as told by the GNOME Shell extension.

A Wayland client cannot learn the work area, and the desktop windows cover
whole monitors (so every click on the empty desktop reaches this process,
also beside a short dock). The extension therefore starts this process with
AREAS_ENV set and a pipe on standard input, and writes one JSON line whenever
the top bar, the dock or the monitors change:

    {"areas": {"DP-1": [x, y, width, height], ...},
     "exclusions": {"DP-1": [[x, y, width, height], ...], ...},
     "workareas": {"DP-1": [x, y, width, height], ...}}

All in logical pixels relative to the monitor's top-left corner:
  areas       the part of a monitor icons may use (without the top bar);
  exclusions  docks inside that area: icons are kept off them, but the rest
              of the band along a dock stays part of the desktop;
  workareas   what maximized windows get; the shell keeps popups inside it.
Without the pipe (helper started by hand, older extension) the whole window
is used.

Menus go the other way. GTK menus are Wayland popups, which mutter keeps
inside the work area: a menu opened in the band along a dock that reserves
space would be moved above the dock or squeezed. So, with the pipe, the
context menus of the desktop are drawn by the shell at the clicked point:
this process writes the menu as one JSON line on its standard output,

    {"menu": {"connector": "DP-1", "x": 200, "y": 780, "keyboard": false,
              "sections": [[{"label": "New Folder…", "action": "new-folder",
                             "target": null, "enabled": true,
                             "accel": "Shift+Ctrl+N", "checked": null,
                             "submenu": null}, ...], ...]}}

(x, y relative to the monitor), and the shell answers with the chosen item:

    {"activate": {"connector": "DP-1", "action": "new-folder", "target": null}}

Lines that are not JSON objects are ignored on both sides.
"""

import json
import os
import sys

import gi
from gi.repository import Gio, GLib, GObject

from . import legacy

try:
    gi.require_version("GioUnix", "2.0")
    from gi.repository import GioUnix
    _UnixInputStream = GioUnix.InputStream
except (ImportError, ValueError):  # GLib < 2.80
    _UnixInputStream = Gio.UnixInputStream

# The former name when started by the former extension (legacy.py).
AREAS_ENV = legacy.AREAS_ENV if legacy.ACTIVE else "DESKENCE_DESKTOP_AREAS"


class Geometry(tuple):
    """(area, exclusions, workarea) of one monitor, see the module docs."""

    def __new__(cls, area, exclusions, workarea):
        return super().__new__(cls, (area, exclusions, workarea))

    area = property(lambda self: self[0])
    exclusions = property(lambda self: self[1])
    workarea = property(lambda self: self[2])
# How long to wait at startup for the first areas and for the windows to get
# their monitor size, before laying out icons anyway.
STARTUP_GRACE_MS = 2000


def _rect(value):
    x, y, width, height = (int(v) for v in value)
    return (x, y, width, height) if width > 0 and height > 0 else None


def parse_areas(line):
    """{connector: Geometry} from one line, or None if invalid."""
    try:
        data = json.loads(line)
        areas = data["areas"]
        exclusions = data.get("exclusions") or {}
        workareas = data.get("workareas") or {}
        if not all(isinstance(d, dict) for d in (areas, exclusions, workareas)):
            return None
        result = {}
        for connector, rect in areas.items():
            area = _rect(rect)
            if area is None:
                continue
            excluded = tuple(r for r in (_rect(e) for e in exclusions.get(connector, [])) if r)
            workarea = _rect(workareas[connector]) if connector in workareas else None
            result[str(connector)] = Geometry(area, excluded, workarea or area)
        return result
    except (ValueError, TypeError, KeyError):
        return None


def parse_activation(line):
    """(connector, action, target) of an "activate" line, or None."""
    try:
        data = json.loads(line)
        value = data["activate"]
        target = value.get("target")
        return (str(value["connector"]), str(value["action"]),
                None if target is None else str(target))
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


class ShellAreas(GObject.Object):
    """Emits "changed" when the areas change or the startup grace ends.

    Icons must not be laid out before the areas are known: new icons would
    be placed, and their positions remembered, for the wrong area.
    """

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_LAST, None, ()),
        # A menu item chosen in a menu drawn by the shell: connector,
        # action name (without "win."), target string or None.
        "activate": (GObject.SignalFlags.RUN_LAST, None, (str, str, object)),
    }

    def __init__(self):
        super().__init__()
        self._areas = {}
        self._stream = None
        expected = os.environ.get(AREAS_ENV) == "1"
        self._received = not expected
        self.in_grace = True
        GLib.timeout_add(STARTUP_GRACE_MS, self._end_grace)
        if expected:
            self._stream = Gio.DataInputStream.new(_UnixInputStream.new(0, False))
            self._read()

    @property
    def shows_menus(self):
        """Whether the shell draws our menus (see the module docs)."""
        return self._stream is not None

    def send_menu(self, menu):
        """Ask the shell to show a menu; see the module docs for the format."""
        sys.stdout.write(json.dumps({"menu": menu}) + "\n")
        sys.stdout.flush()

    @property
    def ready(self):
        """Whether icons may be laid out."""
        return self._received or not self.in_grace

    def get(self, connector):
        """Geometry of a monitor, or None when the shell did not tell."""
        return self._areas.get(connector)

    def _end_grace(self):
        self.in_grace = False
        self.emit("changed")
        return GLib.SOURCE_REMOVE

    def _read(self):
        self._stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line)

    def _on_line(self, stream, result):
        try:
            line, _length = stream.read_line_finish_utf8(result)
        except GLib.Error as e:
            print(f"deskence-desktop-icons: reading areas failed: {e.message}")
            return
        if line is None:
            return  # the shell side went away; keep the last areas
        activation = parse_activation(line)
        if activation is not None:
            self.emit("activate", *activation)
            self._read()
            return
        areas = parse_areas(line)
        if areas is not None and (areas != self._areas or not self._received):
            self._areas = areas
            # The shell sends an empty line before any desktop window exists.
            self._received = self._received or bool(areas)
            self.emit("changed")
        self._read()
