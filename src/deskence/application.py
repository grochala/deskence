# SPDX-License-Identifier: GPL-3.0-or-later
"""The Deskence application.

A single-instance GApplication: starting it again, or activating the
"show-page" action over D-Bus (as the desktop menu does), presents the
existing window. It does not stay running after its window is closed.

It also answers to the D-Bus name of Better GNOME Desktop, its former name:
after an update GNOME Shell keeps running the former extensions until the
next login, and their "Dock Settings" and "Desktop Settings" menu items
activate that name (see LegacyName).
"""

import os
import sys
from gettext import gettext as _

from gi.repository import Adw, Gio, GLib, Gtk

from . import rename
from .shell import ShellExtensions

APP_ID = rename.APP_ID
SCHEMA = rename.SCHEMA

LEGACY_PATH = "/io/github/bettergnome/Desktop"
APPLICATION_INTERFACE = """
<node>
  <interface name="org.freedesktop.Application">
    <method name="Activate">
      <arg type="a{sv}" name="platform_data" direction="in"/>
    </method>
    <method name="Open">
      <arg type="as" name="uris" direction="in"/>
      <arg type="a{sv}" name="platform_data" direction="in"/>
    </method>
    <method name="ActivateAction">
      <arg type="s" name="action_name" direction="in"/>
      <arg type="av" name="parameter" direction="in"/>
      <arg type="a{sv}" name="platform_data" direction="in"/>
    </method>
  </interface>
</node>
"""


class LegacyName:
    """org.freedesktop.Application under the former name and path,
    forwarded to the application. The former D-Bus service file starts
    this application when the name is not owned yet. To be removed when
    updates from 0.3.0 no longer need to be supported."""

    def __init__(self, app, connection):
        self._app = app
        self._connection = connection
        node = Gio.DBusNodeInfo.new_for_xml(APPLICATION_INTERFACE)
        self._object_id = connection.register_object(
            LEGACY_PATH, node.interfaces[0], self._on_call, None, None)
        self._name_id = Gio.bus_own_name_on_connection(
            connection, rename.LEGACY_APP_ID, Gio.BusNameOwnerFlags.NONE, None, None)

    def _on_call(self, _connection, _sender, _path, _interface, method, params, invocation):
        if method == "ActivateAction":
            name, parameter, platform_data = params.unpack()
            self._app.activation_token = platform_data.get("activation-token")
            action = self._app.lookup_action(name)
            if action is not None:
                value = GLib.Variant("s", parameter[0]) if parameter else None
                self._app.activate_action(name, value)
        else:
            self._app.activation_token = params.unpack()[-1].get("activation-token")
            self._app.activate()
        invocation.return_value(None)

    def close(self):
        if self._name_id:
            Gio.bus_unown_name(self._name_id)
        if self._object_id:
            self._connection.unregister_object(self._object_id)
        self._name_id = self._object_id = 0


class Application(Adw.Application):
    def __init__(self, version, pkgdatadir):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
                         resource_base_path="/io/github/deskence/Deskence")
        self.version = version
        self.pkgdatadir = pkgdatadir
        self.window = None
        self.shell = None
        self.activation_token = None
        self._legacy_name = None
        self.add_main_option("page", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
                             _("Open a settings page: general, dock, desktop-icons, app-grid, top-bar, "
                               "windows or clipboard"),
                             _("PAGE"))

        show_page = Gio.SimpleAction.new("show-page", GLib.VariantType.new("s"))
        show_page.connect("activate", lambda a, p: self.present_page(p.get_string()))
        self.add_action(show_page)
        for name, callback, accels in (
                ("about", self._about, []),
                ("quit", lambda *a: self.quit(), ["<Control>q"])):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
            if accels:
                self.set_accels_for_action(f"app.{name}", accels)
        self.set_accels_for_action("window.close", ["<Control>w"])

    def do_startup(self):
        Adw.Application.do_startup(self)
        source = Gio.SettingsSchemaSource.get_default()
        if source.lookup(SCHEMA, True) is None:
            print(f"deskence: settings schema {SCHEMA} is not installed",
                  file=sys.stderr)
            self.quit()
            return
        # Settings of the former name and of older releases.
        rename.run(os.path.join(self.pkgdatadir, "legacy-schemas"))
        self.shell = ShellExtensions()

    def do_dbus_register(self, connection, object_path):
        if not Adw.Application.do_dbus_register(self, connection, object_path):
            return False
        try:
            self._legacy_name = LegacyName(self, connection)
        except GLib.Error as e:
            print(f"deskence: the former D-Bus name is not available: {e.message}",
                  file=sys.stderr)
        return True

    def do_dbus_unregister(self, connection, object_path):
        if self._legacy_name is not None:
            self._legacy_name.close()
            self._legacy_name = None
        Adw.Application.do_dbus_unregister(self, connection, object_path)

    def do_command_line(self, command_line):
        options = command_line.get_options_dict().end().unpack()
        self.present_page(options.get("page"))
        return 0

    def do_activate(self):
        self.present_page(None)

    def present_page(self, page):
        if self.shell is None:
            return
        if self.window is None:
            from .window import Window
            self.window = Window(self, self.shell)
            self.window.connect("close-request", self._on_close)
        if page:
            self.window.show_page(page, reveal=True)
        # Raised over other windows when asked through the former name.
        if self.activation_token:
            self.window.set_startup_id(self.activation_token)
            self.activation_token = None
        self.window.present()

    def _on_close(self, window):
        self.window = None
        return False

    def _about(self, *_args):
        dialog = Adw.AboutDialog(
            application_name="Deskence",
            application_icon=APP_ID,
            version=self.version,
            developer_name="Rafał Grochala",
            developers=["Rafał Grochala"],
            copyright="© 2026 Rafał Grochala",
            license_type=Gtk.License.GPL_3_0,
            comments=_("A dock with folders, desktop icons, application icons in the top bar, "
                       "a clipboard history and window settings for GNOME."),
        )
        dialog.present(self.window)

