#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""DEVELOPER TOOL, not packaged: sends LauncherEntry updates like an
application would, to try the counters and progress of the dock.

    launcher-entry.py DESKTOP_ID [--count N] [--hide-count] [--progress P]
                      [--hide-progress] [--raw KEY=VALUE] [--hold SECONDS]

Each option sends one property in one Update signal of
com.canonical.Unity.LauncherEntry, on this process's own connection to the
session bus. The connection stays open for --hold seconds (default: until
interrupted), and closing it is what makes the dock forget the values.
--raw sends a value as given (an int, float, bool or string), to try
invalid data. Run it inside the session (tests/integration/session.sh run).

A synthetic sender: it shows that the dock follows the protocol, not that
every application sends it the same way.
"""

import argparse
import sys
import time

from gi.repository import Gio, GLib


def value(text):
    for kind, parse in (("x", int), ("d", float)):
        try:
            return GLib.Variant(kind, parse(text))
        except ValueError:
            pass
    if text in ("true", "false"):
        return GLib.Variant("b", text == "true")
    return GLib.Variant("s", text)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("desktop_id")
    parser.add_argument("--count", type=int)
    parser.add_argument("--hide-count", action="store_true")
    parser.add_argument("--progress", type=float)
    parser.add_argument("--hide-progress", action="store_true")
    parser.add_argument("--raw", action="append", default=[])
    parser.add_argument("--hold", type=float)
    args = parser.parse_args()

    properties = {}
    if args.count is not None:
        properties["count"] = GLib.Variant("x", args.count)
        properties["count-visible"] = GLib.Variant("b", True)
    if args.hide_count:
        properties["count-visible"] = GLib.Variant("b", False)
    if args.progress is not None:
        properties["progress"] = GLib.Variant("d", args.progress)
        properties["progress-visible"] = GLib.Variant("b", True)
    if args.hide_progress:
        properties["progress-visible"] = GLib.Variant("b", False)
    for item in args.raw:
        key, _sep, text = item.partition("=")
        properties[key] = value(text)

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    bus.emit_signal(None, "/io/github/deskence/LauncherEntryTest",
                    "com.canonical.Unity.LauncherEntry", "Update",
                    GLib.Variant("(sa{sv})", (f"application://{args.desktop_id}", properties)))
    bus.flush_sync(None)
    print(f"sent from {bus.get_unique_name()}: {sorted(properties)}", flush=True)
    try:
        if args.hold is None:
            while True:
                time.sleep(3600)
        time.sleep(args.hold)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
