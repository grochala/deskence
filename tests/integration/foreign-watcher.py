#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""A foreign StatusNotifierWatcher for testing host mode.

Usage: foreign-watcher.py LOGFILE
"""

import sys

from gi.repository import Gio, GLib

XML = """
<node><interface name="org.kde.StatusNotifierWatcher">
 <method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>
 <method name="RegisterStatusNotifierHost"><arg type="s" direction="in"/></method>
 <property name="RegisteredStatusNotifierItems" type="as" access="read"/>
 <property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
 <property name="ProtocolVersion" type="i" access="read"/>
 <signal name="StatusNotifierItemRegistered"><arg type="s"/></signal>
</interface></node>"""

items = []


def log(text):
    with open(sys.argv[1], "a") as f:
        f.write(text + "\n")


def call(conn, sender, path, iface, method, params, invocation):
    (service,) = params.unpack()
    log(f"foreign {method} {service}")
    if method == "RegisterStatusNotifierItem":
        full = service if not service.startswith("/") else sender + service
        if not full.startswith(":") and "/" not in full:
            full = full + "/StatusNotifierItem"
        items.append(full)
        conn.emit_signal(None, "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher",
                         "StatusNotifierItemRegistered", GLib.Variant("(s)", (full,)))
    invocation.return_value(None)


def prop(conn, sender, path, iface, name):
    return {"RegisteredStatusNotifierItems": GLib.Variant("as", items),
            "IsStatusNotifierHostRegistered": GLib.Variant("b", True),
            "ProtocolVersion": GLib.Variant("i", 0)}[name]


def acquired(conn, name):
    conn.register_object("/StatusNotifierWatcher",
                         Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], call, prop, None)
    log("foreign watcher owns the name")


Gio.bus_own_name(Gio.BusType.SESSION, "org.kde.StatusNotifierWatcher",
                 Gio.BusNameOwnerFlags.NONE, None, acquired, lambda *a: log("foreign lost"))
GLib.MainLoop().run()
