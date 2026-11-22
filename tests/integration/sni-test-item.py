#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Minimal StatusNotifierItem + DBusMenu client for integration tests.

Usage: sni-test-item.py LOGFILE [--path-only] [--pixmap] [--passive]
Logs every method call to LOGFILE. Sends SIGUSR1 to switch icon (NewIcon),
SIGUSR2 to toggle NeedsAttention.
"""

import signal
import sys

from gi.repository import Gio, GLib

ITEM_XML = """
<node>
 <interface name="org.kde.StatusNotifierItem">
  <property name="Category" type="s" access="read"/>
  <property name="Id" type="s" access="read"/>
  <property name="Title" type="s" access="read"/>
  <property name="Status" type="s" access="read"/>
  <property name="IconName" type="s" access="read"/>
  <property name="IconPixmap" type="a(iiay)" access="read"/>
  <property name="AttentionIconName" type="s" access="read"/>
  <property name="IconThemePath" type="s" access="read"/>
  <property name="ItemIsMenu" type="b" access="read"/>
  <property name="Menu" type="o" access="read"/>
  <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
  <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
  <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
  <method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
  <signal name="NewIcon"/>
  <signal name="NewStatus"><arg type="s"/></signal>
 </interface>
</node>"""

MENU_XML = """
<node>
 <interface name="com.canonical.dbusmenu">
  <method name="GetLayout">
   <arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/>
   <arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/>
  </method>
  <method name="Event">
   <arg type="i" direction="in"/><arg type="s" direction="in"/>
   <arg type="v" direction="in"/><arg type="u" direction="in"/>
  </method>
  <method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
  <property name="Version" type="u" access="read"/>
  <signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
 </interface>
</node>"""

log_path = sys.argv[1]
path_only = "--path-only" in sys.argv
use_pixmap = "--pixmap" in sys.argv
state = {"icon": "mail-unread", "status": "Passive" if "--passive" in sys.argv else "Active"}


def log(text):
    with open(log_path, "a") as f:
        f.write(text + "\n")


def node(item_id, props, children=()):
    variant_props = {}
    for key, value in props.items():
        if isinstance(value, bool):
            variant_props[key] = GLib.Variant("b", value)
        elif isinstance(value, int):
            variant_props[key] = GLib.Variant("i", value)
        else:
            variant_props[key] = GLib.Variant("s", value)
    return (item_id, variant_props, [GLib.Variant("(ia{sv}av)", c) for c in children])


def layout():
    return node(0, {}, [
        node(1, {"label": "_Show Window"}),
        node(2, {"type": "separator"}),
        node(3, {"label": "Do Not Disturb", "toggle-type": "checkmark", "toggle-state": 1}),
        node(4, {"label": "Hidden", "visible": False}),
        node(5, {"label": "Disabled", "enabled": False}),
        node(6, {"label": "More", "children-display": "submenu"}, [node(7, {"label": "Nested"})]),
        node(8, {"type": "separator"}),
        node(9, {"label": "_Quit"}),
    ])


def pixmap():
    size = 22
    data = bytearray()
    for _ in range(size * size):
        data += bytes([255, 220, 40, 40])  # ARGB: opaque red
    return [(size, size, bytes(data))]


def item_property(conn, sender, path, iface, prop):
    values = {
        "Category": GLib.Variant("s", "Communications"),
        "Id": GLib.Variant("s", "deskence-test-item"),
        "Title": GLib.Variant("s", "Test Messenger"),
        "Status": GLib.Variant("s", state["status"]),
        "IconName": GLib.Variant("s", "" if use_pixmap else state["icon"]),
        "IconPixmap": GLib.Variant("a(iiay)", pixmap() if use_pixmap else []),
        "AttentionIconName": GLib.Variant("s", "dialog-warning"),
        "IconThemePath": GLib.Variant("s", ""),
        "ItemIsMenu": GLib.Variant("b", False),
        "Menu": GLib.Variant("o", "/MenuBar"),
    }
    return values.get(prop)


def item_call(conn, sender, path, iface, method, params, invocation):
    log(f"{method} {params.unpack()}")
    invocation.return_value(None)


def menu_call(conn, sender, path, iface, method, params, invocation):
    log(f"menu.{method} {params.unpack()[:2]}")
    if method == "GetLayout":
        invocation.return_value(GLib.Variant("(u(ia{sv}av))", (1, layout())))
    elif method == "AboutToShow":
        invocation.return_value(GLib.Variant("(b)", (False,)))
    else:
        invocation.return_value(None)


bus = Gio.bus_get_sync(Gio.BusType.SESSION)
item_info = Gio.DBusNodeInfo.new_for_xml(ITEM_XML).interfaces[0]
menu_info = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
bus.register_object("/StatusNotifierItem", item_info, item_call, item_property, None)
bus.register_object("/MenuBar", menu_info, menu_call,
                    lambda *a: GLib.Variant("u", 3), None)


def register():
    service = "/StatusNotifierItem" if path_only else bus.get_unique_name()
    bus.call_sync("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher",
                  "org.kde.StatusNotifierWatcher", "RegisterStatusNotifierItem",
                  GLib.Variant("(s)", (service,)), None, Gio.DBusCallFlags.NONE, -1, None)
    log("registered")


def on_usr1(*_a):
    state["icon"] = "call-start"
    bus.emit_signal(None, "/StatusNotifierItem", "org.kde.StatusNotifierItem", "NewIcon", None)
    return True


def on_usr2(*_a):
    state["status"] = "NeedsAttention" if state["status"] != "NeedsAttention" else "Active"
    bus.emit_signal(None, "/StatusNotifierItem", "org.kde.StatusNotifierItem", "NewStatus",
                    GLib.Variant("(s)", (state["status"],)))
    return True


GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, on_usr1)
GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, on_usr2)
GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda *a: loop.quit())
register()
loop = GLib.MainLoop()
loop.run()
