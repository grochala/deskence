# SPDX-License-Identifier: GPL-3.0-or-later
"""State of our GNOME Shell extensions and conflicting ones.

Extensions are enabled and disabled through GNOME Shell's own D-Bus API
(org.gnome.Shell.Extensions), the same one the Extensions application uses.
It appends to or removes from org.gnome.shell enabled-extensions; the list of
other extensions is never replaced.

GNOME Shell only discovers installed extensions when the session starts.
After the package was installed or updated, the new code runs only after
logging out and in again; that state is reported as "needs-login" or
"update-pending" instead of pretending the feature works. Enabling a feature
in that state records the wish in enabled-extensions, so it starts with the
next session.

The settings window uses it asynchronously. The command line creates it
with blocking=True: the bus, GNOME Shell and the list of extensions are
read at once, with a timeout, and set_enabled() waits for GNOME Shell and
says whether the change was applied in the running session or only saved
for the next one.
"""

import json
import os
import sys

from gi.repository import Gio, GLib, GObject

from . import conflicts

SHELL_SCHEMA = "org.gnome.shell"
# GNOME Shell exports the extensions interface on its own bus name.
SHELL_NAME = "org.gnome.Shell"
SHELL_PATH = "/org/gnome/Shell"
EXTENSIONS_IFACE = "org.gnome.Shell.Extensions"

PER_USER = 2

# Results of set_enabled().
APPLIED = "applied"        # GNOME Shell made the change in this session
SAVED = "saved"            # written to enabled-extensions for the next session
UNCHANGED = "unchanged"    # it already was so


class FeatureStatus:
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    OUT_OF_DATE = "out-of-date"
    NEEDS_LOGIN = "needs-login"
    UPDATE_PENDING = "update-pending"
    NOT_INSTALLED = "not-installed"
    EXTENSIONS_DISABLED = "extensions-disabled"
    NO_SHELL = "no-shell"

    def __init__(self, state, error="", user_copy=None):
        self.state = state
        self.error = error
        # Path of a copy in the user's extension directory that hides the
        # packaged one, if any.
        self.user_copy = user_copy


def _system_extension_dirs():
    dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [os.path.join(d, "gnome-shell", "extensions") for d in dirs.split(":") if d]


def _user_extension_dir():
    return os.path.join(GLib.get_user_data_dir(), "gnome-shell", "extensions")


def installed_metadata(uuid):
    """Metadata of the packaged extension on disk, or None."""
    for directory in _system_extension_dirs():
        path = os.path.join(directory, uuid, "metadata.json")
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return None


def user_copy_path(uuid):
    path = os.path.join(_user_extension_dir(), uuid)
    return path if os.path.isdir(path) else None


def _unpack_info(info):
    result = dict(info)
    for key in ("state", "type"):
        if key in result:
            result[key] = int(result[key])
    return result


class ShellExtensions(GObject.Object):
    """Emits "changed" whenever anything relevant may have changed."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_LAST, None, ())}

    def __init__(self, blocking=False, timeout_ms=3000):
        super().__init__()
        self._infos = {}
        self._proxy = None
        self._shell_available = False
        self._blocking = blocking
        self._timeout = timeout_ms
        # Whether the session bus could be reached (blocking mode only).
        self.bus_available = None
        source = Gio.SettingsSchemaSource.get_default()
        self._settings = Gio.Settings.new(SHELL_SCHEMA) \
            if source.lookup(SHELL_SCHEMA, True) else None
        if self._settings:
            for key in ("enabled-extensions", "disabled-extensions", "disable-user-extensions"):
                self._settings.connect(f"changed::{key}", lambda *a: self.emit("changed"))

        if blocking:
            self._connect_blocking()
            return
        Gio.DBusProxy.new_for_bus(
            Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_AUTO_START, None,
            SHELL_NAME, SHELL_PATH, EXTENSIONS_IFACE, None, self._on_proxy)

    def _connect_blocking(self):
        try:
            self._proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_AUTO_START, None,
                SHELL_NAME, SHELL_PATH, EXTENSIONS_IFACE, None)
        except GLib.Error:
            self.bus_available = False
            return
        self.bus_available = True
        self.refresh()

    def _on_proxy(self, _source, result):
        try:
            self._proxy = Gio.DBusProxy.new_for_bus_finish(result)
        except GLib.Error as e:
            print(f"deskence: GNOME Shell is not reachable: {e.message}", file=sys.stderr)
            self.emit("changed")
            return
        self._proxy.connect("g-signal", self._on_signal)
        self._proxy.connect("notify::g-name-owner", lambda *a: self.refresh())
        self.refresh()

    def _on_signal(self, proxy, sender, signal, params):
        if signal == "ExtensionStateChanged":
            uuid, info = params.unpack()
            self._infos[uuid] = _unpack_info(info)
            self.emit("changed")

    def refresh(self):
        if self._proxy is None or self._proxy.get_name_owner() is None:
            self._shell_available = False
            self._infos = {}
            self.emit("changed")
            return

        def listed(extensions):
            self._shell_available = True
            self._infos = {uuid: _unpack_info(info) for uuid, info in extensions.items()}
            self.emit("changed")

        def failed(e):
            print(f"deskence: listing extensions failed: {e.message}", file=sys.stderr)
            self._shell_available = False
            self.emit("changed")

        if self._blocking:
            try:
                (extensions,) = self._proxy.call_sync(
                    "ListExtensions", None, Gio.DBusCallFlags.NONE, self._timeout, None).unpack()
            except GLib.Error as e:
                failed(e)
                return
            listed(extensions)
            return

        def done(proxy, result):
            try:
                (extensions,) = proxy.call_finish(result).unpack()
            except GLib.Error as e:
                failed(e)
                return
            listed(extensions)

        self._proxy.call("ListExtensions", None, Gio.DBusCallFlags.NONE, -1, None, done)

    # -- Queries ---------------------------------------------------------

    @property
    def shell_available(self):
        """Whether GNOME Shell answered (the state of the running session
        is known)."""
        return self._shell_available

    def info(self, uuid):
        """What GNOME Shell reports about an extension, or None."""
        return self._infos.get(uuid)

    @property
    def shell_version(self):
        if self._proxy is None:
            return None
        value = self._proxy.get_cached_property("ShellVersion")
        return value.unpack() if value else None

    def extensions_globally_disabled(self):
        return bool(self._settings and self._settings.get_boolean("disable-user-extensions"))

    def is_enabled(self, uuid):
        """Whether the user wants the extension on (it may still need a login)."""
        if self._settings is None:
            return False
        return uuid in self._settings.get_strv("enabled-extensions")

    def status(self, uuid):
        metadata = installed_metadata(uuid)
        info = self._infos.get(uuid)
        copy = user_copy_path(uuid)
        if info and info.get("type") != PER_USER:
            copy = None

        if metadata is None and info is None:
            return FeatureStatus(FeatureStatus.NOT_INSTALLED)
        if not self._shell_available:
            return FeatureStatus(FeatureStatus.NO_SHELL)
        if self.extensions_globally_disabled():
            return FeatureStatus(FeatureStatus.EXTENSIONS_DISABLED)
        if info is None:
            return FeatureStatus(FeatureStatus.NEEDS_LOGIN)
        if copy is None and metadata and \
                metadata.get("version-name") != info.get("version-name"):
            return FeatureStatus(FeatureStatus.UPDATE_PENDING)
        state = info.get("state")
        if state == conflicts.STATE_ERROR:
            return FeatureStatus(FeatureStatus.ERROR, str(info.get("error", "")), copy)
        if state == conflicts.STATE_OUT_OF_DATE:
            return FeatureStatus(FeatureStatus.OUT_OF_DATE, user_copy=copy)
        if state in (conflicts.STATE_ACTIVE, conflicts.STATE_ACTIVATING):
            return FeatureStatus(FeatureStatus.ACTIVE, user_copy=copy)
        return FeatureStatus(FeatureStatus.INACTIVE, user_copy=copy)

    def conflicts(self, feature):
        return conflicts.find_conflicts(feature, self._infos)

    # -- Changes ---------------------------------------------------------

    def set_enabled(self, uuid, enabled):
        """Asks GNOME Shell to enable or disable one of our extensions, or
        records the choice for the next session. Only the given extension
        is touched. In blocking mode returns APPLIED, SAVED or UNCHANGED
        (SAVED also when GNOME Shell did not confirm the change); raises
        GLib.Error when GNOME Shell refuses it."""
        if self._shell_available and uuid in self._infos:
            method = "EnableExtension" if enabled else "DisableExtension"
            if not self._blocking:
                self._proxy.call(method, GLib.Variant("(s)", (uuid,)), Gio.DBusCallFlags.NONE,
                                 -1, None, self._on_call_done)
                return None
            running = conflicts.is_running(self._infos[uuid])
            if self.is_enabled(uuid) == enabled and running == enabled:
                return UNCHANGED
            self._proxy.call_sync(method, GLib.Variant("(s)", (uuid,)),
                                  Gio.DBusCallFlags.NONE, self._timeout, None)
            # GNOME Shell stores enabled-extensions through dconf after it
            # answered: wait a little for the state and the setting to agree.
            deadline = GLib.get_monotonic_time() + self._timeout * 1000
            while True:
                self.refresh()
                info = self._infos.get(uuid)
                if info is not None and conflicts.is_running(info) == enabled and \
                        self.is_enabled(uuid) == enabled:
                    return APPLIED
                if GLib.get_monotonic_time() > deadline:
                    return SAVED
                GLib.MainContext.default().iteration(False)
                GLib.usleep(50000)
        # GNOME Shell does not know the extension yet (installed during this
        # session) or is not running: record the choice the same way GNOME
        # Shell does, for the next session.
        if self._settings is None:
            return UNCHANGED
        before = self.is_enabled(uuid)
        enabled_list = self._settings.get_strv("enabled-extensions")
        disabled_list = self._settings.get_strv("disabled-extensions")
        if enabled:
            if uuid not in enabled_list:
                self._settings.set_strv("enabled-extensions", enabled_list + [uuid])
            if uuid in disabled_list:
                self._settings.set_strv("disabled-extensions",
                                        [u for u in disabled_list if u != uuid])
        else:
            if uuid in enabled_list:
                self._settings.set_strv("enabled-extensions",
                                        [u for u in enabled_list if u != uuid])
        return UNCHANGED if before == enabled else SAVED

    def disable_other(self, uuid):
        """Disable another extension at the user's explicit request."""
        if self._proxy is not None:
            self._proxy.call("DisableExtension", GLib.Variant("(s)", (uuid,)),
                             Gio.DBusCallFlags.NONE, -1, None, self._on_call_done)

    def enable_extensions_globally(self):
        if self._settings is not None:
            self._settings.set_boolean("disable-user-extensions", False)

    def _on_call_done(self, proxy, result):
        try:
            proxy.call_finish(result)
        except GLib.Error as e:
            print(f"deskence: changing an extension failed: {e.message}", file=sys.stderr)
        self.refresh()


def log_out():
    """Ask GNOME to log out; GNOME shows its usual confirmation dialog."""
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    bus.call("org.gnome.SessionManager", "/org/gnome/SessionManager",
             "org.gnome.SessionManager", "Logout", GLib.Variant("(u)", (0,)),
             None, Gio.DBusCallFlags.NONE, -1, None, None)
