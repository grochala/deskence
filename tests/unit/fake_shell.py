# SPDX-License-Identifier: GPL-3.0-or-later
"""A stand-in for GNOME Shell's extensions D-Bus interface, for test_cli.py.

Run on a private session bus; it owns org.gnome.Shell, knows our six
extensions plus one of somebody else, and like GNOME Shell keeps
org.gnome.shell enabled-extensions up to date when an extension is enabled
or disabled over D-Bus.

    python3 fake_shell.py
"""

from gi.repository import Gio, GLib

OURS = ["dock", "desktop-icons", "tray", "app-grid", "clipboard", "keep-awake"]
UUIDS = [f"{name}@deskence.github.io" for name in OURS] + ["foreign@example.org"]
ACTIVE, INACTIVE = 1, 2

INTERFACE = """
<node>
  <interface name="org.gnome.Shell.Extensions">
    <method name="ListExtensions">
      <arg type="a{sa{sv}}" direction="out"/>
    </method>
    <method name="EnableExtension">
      <arg type="s" direction="in"/>
      <arg type="b" direction="out"/>
    </method>
    <method name="DisableExtension">
      <arg type="s" direction="in"/>
      <arg type="b" direction="out"/>
    </method>
    <property name="ShellVersion" type="s" access="read"/>
    <signal name="ExtensionStateChanged">
      <arg type="s"/>
      <arg type="a{sv}"/>
    </signal>
  </interface>
</node>
"""

settings = Gio.Settings.new("org.gnome.shell")


def info(uuid):
    enabled = uuid in settings.get_strv("enabled-extensions")
    return {
        "uuid": GLib.Variant("s", uuid),
        "name": GLib.Variant("s", uuid.split("@")[0]),
        "state": GLib.Variant("d", float(ACTIVE if enabled else INACTIVE)),
        "type": GLib.Variant("d", 1.0),
        "version-name": GLib.Variant("s", "test"),
    }


def call(connection, _sender, _path, _interface, method, params, invocation):
    if method == "ListExtensions":
        invocation.return_value(GLib.Variant("(a{sa{sv}})", ({u: info(u) for u in UUIDS},)))
        return
    (uuid,) = params.unpack()
    if uuid not in UUIDS:
        invocation.return_value(GLib.Variant("(b)", (False,)))
        return
    enabled = settings.get_strv("enabled-extensions")
    if method == "EnableExtension" and uuid not in enabled:
        settings.set_strv("enabled-extensions", enabled + [uuid])
    elif method == "DisableExtension" and uuid in enabled:
        settings.set_strv("enabled-extensions", [u for u in enabled if u != uuid])
    Gio.Settings.sync()
    connection.emit_signal(None, "/org/gnome/Shell", "org.gnome.Shell.Extensions",
                           "ExtensionStateChanged", GLib.Variant("(sa{sv})", (uuid, info(uuid))))
    invocation.return_value(GLib.Variant("(b)", (True,)))


def get_property(*_args):
    return GLib.Variant("s", "51.0")


def main():
    loop = GLib.MainLoop()
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    node = Gio.DBusNodeInfo.new_for_xml(INTERFACE)
    bus.register_object("/org/gnome/Shell", node.interfaces[0], call, get_property, None)
    Gio.bus_own_name_on_connection(bus, "org.gnome.Shell", Gio.BusNameOwnerFlags.NONE,
                                   lambda *a: print("ready", flush=True), None)
    loop.run()


if __name__ == "__main__":
    main()
