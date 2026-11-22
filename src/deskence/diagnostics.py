# SPDX-License-Identifier: GPL-3.0-or-later
"""A report for bug reports: what is installed, how the session looks and
in what state each feature is. The settings window and the command line
both show this report (to_text() or the data as JSON).

The report is built from an explicit list of fields, never from a dump:
versions, the distribution, the kind of session, monitors (count, mode,
refresh rate, scale; no make, model or serial number), the saved and the
running state of each feature, conflicts found by conflicts.py, and the
names (not values) of settings that differ from their defaults. It contains
no clipboard contents, window titles, document or file names, paths of
the user, the user or host name, environment variables, dconf dumps or
logs. Messages from GNOME Shell have the home folder, the user name and
the host name replaced. A value that cannot be found is None, shown as
"unavailable"; one failing source never stops the report. It is only shown,
copied or saved by the user; Deskence never sends it anywhere.
"""

import os
import platform
import pwd
import socket

from gi.repository import Gio, GLib

from . import control, presets
from . import shell as shell_module
from .features import UUIDS

FORMAT_ID = "io.github.deskence.Deskence.diagnostics"
FORMAT_VERSION = 2

OS_RELEASE_KEYS = ("NAME", "ID", "ID_LIKE", "VERSION_ID", "VARIANT_ID")


def _os_release(paths=("/etc/os-release", "/usr/lib/os-release")):
    for candidate in paths:
        result = {}
        try:
            with open(candidate, encoding="utf-8") as f:
                for line in f:
                    key, sep, value = line.strip().partition("=")
                    if sep and key in OS_RELEASE_KEYS:
                        result[key.lower().replace("_", "-")] = value.strip().strip("\"'")
            return result
        except OSError:
            continue
    return None


def _private_words():
    words = [GLib.get_home_dir()]
    try:
        words.append(pwd.getpwuid(os.getuid()).pw_name)
    except KeyError:
        pass
    words += [GLib.get_user_name(), GLib.get_real_name(), socket.gethostname(),
              GLib.get_host_name()]
    # Longest first, so a home folder goes before the user name in it.
    return sorted({w for w in words if w and len(w) > 2 and w not in ("/", "Unknown")},
                  key=len, reverse=True)


def scrub(text, words=None):
    """A message with the home folder, user and host names hidden."""
    if not text:
        return text
    for word in words if words is not None else _private_words():
        text = text.replace(word, "~" if word.startswith("/") else "…")
    return text


def _monitors(timeout_ms=2000):
    """[{"width", "height", "refresh", "scale", "primary"}] from mutter, or
    None when it cannot be asked (no GNOME session)."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync(
            "org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
            "org.gnome.Mutter.DisplayConfig", "GetCurrentState", None, None,
            Gio.DBusCallFlags.NO_AUTO_START, timeout_ms, None)
        _serial, monitors, logical, _props = reply.unpack()
    except (GLib.Error, ValueError, TypeError):
        return None
    scales, primary = {}, set()
    for _x, _y, scale, _transform, is_primary, members, _p in logical:
        for spec in members:
            scales[spec[0]] = scale
            if is_primary:
                primary.add(spec[0])
    result = []
    for spec, modes, _p in monitors:
        connector = spec[0]
        current = next((m for m in modes if m[6].get("is-current")), None)
        result.append({
            "width": current[1] if current else None,
            "height": current[2] if current else None,
            "refresh": round(current[3], 2) if current else None,
            "scale": scales.get(connector),
            "primary": connector in primary,
        })
    return result


def collect(version, shell, store, toolkit=None):
    """The report as plain data. shell: a ShellExtensions with its state
    read; toolkit: {"gtk": ..., "libadwaita": ...} when the caller has
    loaded them (the command line does not)."""
    words = _private_words()
    storage = control.storage()
    try:
        import gi
        pygobject = ".".join(str(n) for n in gi.version_info)
    except (ImportError, AttributeError):
        pygobject = None
    toolkit = toolkit or {}
    report = {
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "deskence": {
            "version": version,
            "settings-schema": store.available(presets.SCHEMA),
            "settings-version": store.get(presets.SCHEMA, "settings-version")
            if store.available(presets.SCHEMA, "settings-version") else None,
            "legacy-settings-migrated": store.get(presets.SCHEMA, "legacy-settings-migrated")
            if store.available(presets.SCHEMA, "legacy-settings-migrated") else None,
        },
        "system": {
            "os": _os_release(),
            "python": platform.python_version(),
            "glib": "{}.{}.{}".format(GLib.MAJOR_VERSION, GLib.MINOR_VERSION,
                                      GLib.MICRO_VERSION),
            "pygobject": pygobject,
            "gtk": toolkit.get("gtk"),
            "libadwaita": toolkit.get("libadwaita"),
            "language": os.environ.get("LANG") or None,
        },
        "session": {
            "type": os.environ.get("XDG_SESSION_TYPE") or None,
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP") or None,
            "bus": shell.bus_available,
            "gnome-shell": shell.shell_available,
            "gnome-shell-version": shell.shell_version if shell.shell_available else None,
            "extensions-enabled": not shell.extensions_globally_disabled(),
            "monitors": _monitors(),
        },
        "settings-storage": {"backend": storage.backend, "persistent": storage.persistent},
        "features": [],
        "conflicts": [],
        "changed-settings": [],
        "presets": {
            "saved": len(presets.list_saved()),
            "undo-available": os.path.isfile(presets.backup_path()),
        },
    }
    for module, uuid in UUIDS.items():
        status = shell.status(uuid)
        info = shell.info(uuid) or {}
        metadata = shell_module.installed_metadata(uuid) or {}
        report["features"].append({
            "id": module,
            "enabled": shell.is_enabled(uuid),
            "state": status.state,
            "error": scrub(status.error, words) or None,
            "user-copy": bool(status.user_copy),
            "installed-version": metadata.get("version-name"),
            "running-version": info.get("version-name") if info else None,
        })
        for conflict in shell.conflicts(module):
            report["conflicts"].append({"feature": module, "uuid": conflict.uuid,
                                        "name": scrub(conflict.name, words),
                                        "certain": conflict.certain})
    for schema in presets.DESKENCE_SCHEMAS:
        if not store.available(schema):
            continue
        settings = store.settings(schema)
        for key in sorted(store.keys(schema)):
            if settings.get_user_value(key) is not None and \
                    settings.get_value(key) != settings.get_default_value(key):
                report["changed-settings"].append(f"{schema} {key}")
    return report


def _value(value):
    if value is None:
        return "unavailable"
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return str(value)


def to_text(report):
    """The report as Markdown for a GitHub issue. In English, like the
    rest of a bug report, whatever the language of the interface."""
    d, s, sess = report["deskence"], report["system"], report["session"]
    os_info = s["os"]
    os_text = " ".join(v for v in (os_info.get("name"), os_info.get("version-id")) if v) \
        if os_info else ""
    lines = [
        "### Deskence diagnostics",
        "",
        f"- Deskence: {_value(d['version'])}",
        f"- GNOME Shell: {_value(sess['gnome-shell-version'])}"
        + ("" if sess["gnome-shell"] else " (not reachable)"),
        f"- Distribution: {os_text or 'unavailable'}",
        f"- Session: {_value(sess['type'])}, desktop {_value(sess['desktop'])}",
        f"- Libraries: GLib {_value(s['glib'])}, GTK {_value(s['gtk'])}, "
        f"libadwaita {_value(s['libadwaita'])}, PyGObject {_value(s['pygobject'])}, "
        f"Python {_value(s['python'])}",
        f"- Language: {_value(s['language'])}",
        f"- GNOME extensions enabled: {_value(sess['extensions-enabled'])}",
    ]
    storage = report["settings-storage"]
    lines.append(f"- Settings: {storage['backend']}, kept {_value(storage['persistent'])}, "
                 f"schema version {_value(d['settings-version'])}")
    monitors = sess["monitors"]
    if monitors is None:
        lines.append("- Monitors: unavailable")
    else:
        lines.append(f"- Monitors: {len(monitors)}")
        for i, m in enumerate(monitors, 1):
            mode = "unavailable" if m["width"] is None else \
                f"{m['width']}×{m['height']} at {m['refresh']} Hz"
            lines.append(f"  - {i}: {mode}, scale {_value(m['scale'])}"
                         + (", primary" if m["primary"] else ""))
    lines += ["", "| Feature | Saved | In the session | Installed | Running |",
              "|---|---|---|---|---|"]
    for f in report["features"]:
        lines.append(f"| {f['id']} | {'enabled' if f['enabled'] else 'disabled'} | "
                     f"{f['state']}{' (copy in home folder)' if f['user-copy'] else ''} | "
                     f"{_value(f['installed-version'])} | {_value(f['running-version'])} |")
    errors = [f for f in report["features"] if f["error"]]
    if errors:
        lines += ["", "Errors:"]
        lines += [f"- {f['id']}: {f['error']}" for f in errors]
    lines += ["", "Conflicts: " + (", ".join(
        f"{c['feature']}: {c['name']} ({c['uuid']}, {'certain' if c['certain'] else 'possible'})"
        for c in report["conflicts"]) or "none")]
    lines.append("Changed settings: " + (", ".join(
        k.replace("io.github.deskence.Deskence", "").lstrip(". ")
        for k in report["changed-settings"]) or "none"))
    lines.append(f"Presets: {report['presets']['saved']} saved, undo available "
                 f"{_value(report['presets']['undo-available'])}")
    return "\n".join(lines) + "\n"
