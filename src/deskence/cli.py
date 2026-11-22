# SPDX-License-Identifier: GPL-3.0-or-later
"""The command line: status, enabling features, presets, restoring defaults
and diagnostics, also when the settings window cannot be used.

It never loads GTK and needs no display: settings go through GSettings
(normally dconf on the session bus) and features through GNOME Shell's own
D-Bus interface, the same code as the settings window (shell, presets,
control, diagnostics). Everything concerns the user running it; it refuses
to run as root.

Writing a setting and applying it in the running session are told apart:
without a reachable GNOME Shell a feature can still be turned on or off for
the next login, and the command says that it could not confirm the change.
When the settings cannot be stored at all (no session bus for dconf, an
in-memory backend), nothing is written and the command fails.

Output: results on stdout, messages on stderr, no colors. With --json,
stdout holds exactly one JSON document {"format": FORMAT_ID, "version":
FORMAT_VERSION, "command": ..., ...} and nothing asks questions: changes
that need confirming need --yes. Exit status: see EXIT_*.
"""

import argparse
import json
import os
import sys
import tempfile
from gettext import gettext as _
from gettext import ngettext

from gi.repository import GLib

from . import appgrid, control, diagnostics, presets, rename
from .features import IDS, UUIDS
from .shell import APPLIED, SAVED, UNCHANGED, FeatureStatus, ShellExtensions

FORMAT_ID = "io.github.deskence.Deskence.cli"
FORMAT_VERSION = 1

COMMANDS = ("status", "enable", "disable", "preset", "reset", "diagnostics")

EXIT_OK = 0
EXIT_FAILED = 1          # nothing or not everything was done
EXIT_USAGE = 2           # invalid command line
EXIT_CONFIRM = 3         # a change needs confirming: declined, or no terminal and no --yes
EXIT_UNCONFIRMED = 4     # saved, but the running GNOME session did not confirm it


def handles(args):
    """Whether these arguments are for the command line (and not for the
    settings window, such as --page or --gapplication-service)."""
    return bool(args) and (args[0] in COMMANDS or args[0] in ("-h", "--help", "--version"))


def root_message():
    return _("deskence: do not run Deskence as root; run it as your own user (without sudo).")


class Failure(Exception):
    def __init__(self, message, code=EXIT_FAILED):
        super().__init__(message)
        self.code = code


# --- Output -----------------------------------------------------------------

class Output:
    def __init__(self, as_json):
        self.as_json = as_json

    def line(self, text=""):
        if not self.as_json:
            print(text)

    def note(self, text):
        print(text, file=sys.stderr)

    def document(self, command, **data):
        if self.as_json:
            doc = {"format": FORMAT_ID, "version": FORMAT_VERSION, "command": command}
            doc.update({key.replace("_", "-"): value for key, value in data.items()})
            json.dump(doc, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")


def _short(value, limit=60):
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else repr(value)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _table(rows):
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    return ["  ".join(str(c).ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows]


# --- Shared state -----------------------------------------------------------

class Session:
    """What a command needs, created on first use."""

    def __init__(self, version, pkgdatadir):
        self.version = version
        self.pkgdatadir = pkgdatadir
        self._store = None
        self._shell = None

    @property
    def store(self):
        if self._store is None:
            self._store = presets.SettingsStore()
            if not self._store.available(presets.SCHEMA):
                raise Failure(_("The Deskence settings schema is not installed. "
                                "Reinstall the deskence package."))
        return self._store

    @property
    def shell(self):
        if self._shell is None:
            self._shell = ShellExtensions(blocking=True)
        return self._shell

    def features(self):
        return control.enabled_features(self.shell)

    def writable(self):
        """Stops unless written settings will be kept; then brings the
        settings up to date, as the settings window does when it starts."""
        self.store  # noqa: B018 - the schema must exist
        storage = control.storage()
        if not storage.persistent:
            raise Failure(_("Nothing was changed: the settings cannot be saved.") + " " +
                          storage.reason)
        rename.run(os.path.join(self.pkgdatadir, "legacy-schemas"))

    def set_feature(self, module, enabled):
        """For presets and resets: the result of the change, kept to report
        it afterwards."""
        result = self.shell.set_enabled(UUIDS[module], enabled)
        self.feature_results = getattr(self, "feature_results", {})
        self.feature_results[module] = result


def _confirm(args, out, question):
    """True to go on. Without a terminal (or with --json) only --yes
    confirms."""
    if getattr(args, "yes", False):
        return True
    if out.as_json or not sys.stdin.isatty():
        raise Failure(_("This change needs confirming. Run the command again with --yes "
                        "to confirm it without a question."), EXIT_CONFIRM)
    sys.stderr.write(f"{question} [{_('y/N')}] ")
    sys.stderr.flush()
    answer = sys.stdin.readline().strip().casefold()
    if answer in ("y", "yes", _("y").casefold(), _("yes").casefold()):
        return True
    out.note(_("Nothing was changed."))
    raise Failure("", EXIT_CONFIRM)


def _unconfirmed_message():
    return _("Saved. The change could not be confirmed in the current GNOME session; "
             "logging in again may be needed.")


# --- status -------------------------------------------------------------------

STATE_LABELS = {
    FeatureStatus.ACTIVE: lambda: _("running"),
    FeatureStatus.INACTIVE: lambda: _("not running"),
    FeatureStatus.ERROR: lambda: _("error"),
    FeatureStatus.OUT_OF_DATE: lambda: _("GNOME version not supported"),
    FeatureStatus.NEEDS_LOGIN: lambda: _("starts after logging in again"),
    FeatureStatus.UPDATE_PENDING: lambda: _("updated; new version after logging in again"),
    FeatureStatus.NOT_INSTALLED: lambda: _("not installed"),
    FeatureStatus.EXTENSIONS_DISABLED: lambda: _("GNOME extensions are turned off"),
    FeatureStatus.NO_SHELL: lambda: _("unknown (GNOME Shell not reachable)"),
}


def _feature_status(shell, module):
    uuid = UUIDS[module]
    status = shell.status(uuid)
    enabled = shell.is_enabled(uuid)
    running = None
    if shell.shell_available and status.state not in (FeatureStatus.NOT_INSTALLED,
                                                      FeatureStatus.NO_SHELL):
        running = status.state == FeatureStatus.ACTIVE
    login = status.state in (FeatureStatus.NEEDS_LOGIN, FeatureStatus.UPDATE_PENDING) or \
        (running is not None and running != enabled and status.state != FeatureStatus.ERROR
         and not shell.extensions_globally_disabled())
    return {
        "id": module,
        "uuid": uuid,
        "enabled": enabled,
        "state": status.state,
        "running": running,
        "error": status.error or None,
        "user-copy": status.user_copy,
        "login-required": login,
        "conflicts": [{"uuid": c.uuid, "name": c.name, "certain": c.certain}
                      for c in shell.conflicts(module)],
    }


def _session_info(shell):
    return {
        "bus": bool(shell.bus_available),
        "gnome-shell": shell.shell_available,
        "gnome-shell-version": shell.shell_version if shell.shell_available else None,
        "extensions-enabled": not shell.extensions_globally_disabled(),
    }


def cmd_status(args, session, out):
    shell = session.shell
    session.store  # noqa: B018
    items = [_feature_status(shell, m) for m in IDS]
    storage = control.storage()
    out.document("status", session=_session_info(shell),
                 settings_storage={"backend": storage.backend, "persistent": storage.persistent},
                 features=items)
    if out.as_json:
        return EXIT_OK
    if shell.shell_available:
        out.line(_("GNOME Shell {}: the state of the running session is shown.").format(
            shell.shell_version or "?"))
    else:
        out.line(_("GNOME Shell is not reachable: only the saved settings are known."))
    if shell.extensions_globally_disabled():
        out.line(_("GNOME extensions are turned off; no feature runs until they are turned on."))
    if not storage.persistent:
        out.line(storage.reason)
    out.line()
    rows = [(_("FEATURE"), _("SAVED"), _("IN THIS SESSION"))]
    notes = []
    for item in items:
        rows.append((item["id"], _("enabled") if item["enabled"] else _("disabled"),
                     STATE_LABELS[item["state"]]()))
        if item["error"]:
            notes.append(f"{item['id']}: {item['error']}")
        if item["user-copy"]:
            notes.append(_("{}: a copy in your home folder is used instead of the installed "
                           "one: {}").format(item["id"], item["user-copy"]))
        if item["login-required"] and item["state"] not in (FeatureStatus.NEEDS_LOGIN,
                                                            FeatureStatus.UPDATE_PENDING):
            notes.append(_("{}: the saved setting differs from the session; it applies after "
                           "logging in again.").format(item["id"]))
        for c in item["conflicts"]:
            notes.append((_("{}: “{}” provides the same; using both causes problems.")
                          if c["certain"] else _("{}: “{}” may provide the same."))
                         .format(item["id"], c["name"]))
    for row in _table(rows):
        out.line(row)
    if notes:
        out.line()
        for n in notes:
            out.line(n)
    return EXIT_OK


# --- enable / disable -------------------------------------------------------

def _modules(args):
    if getattr(args, "all", False):
        if args.modules:
            raise Failure(_("Give feature names or --all, not both."), EXIT_USAGE)
        return list(IDS)
    if not args.modules:
        raise Failure(_("Name at least one feature, or use --all. Features: {}").format(
            ", ".join(IDS)), EXIT_USAGE)
    unknown = [m for m in args.modules if m not in UUIDS]
    if unknown:
        raise Failure(_("Unknown feature: {}. Features: {}").format(
            ", ".join(unknown), ", ".join(IDS)), EXIT_USAGE)
    return list(dict.fromkeys(args.modules))


def cmd_switch(args, session, out, enabled):
    modules = _modules(args)
    session.writable()
    shell = session.shell
    results = []
    for module in modules:
        uuid = UUIDS[module]
        status = shell.status(uuid)
        entry = {"id": module, "result": None, "error": None}
        if enabled and status.state == FeatureStatus.NOT_INSTALLED:
            entry["result"] = "failed"
            entry["error"] = _("not installed")
        else:
            try:
                entry["result"] = shell.set_enabled(uuid, enabled)
            except GLib.Error as e:
                entry["result"] = "failed"
                entry["error"] = e.message
        results.append(entry)
    # What was only written must read back as written.
    session.store.sync()
    for entry in results:
        if entry["result"] == SAVED and shell.is_enabled(UUIDS[entry["id"]]) != enabled:
            entry["result"] = "failed"
            entry["error"] = _("the setting could not be saved")
    command = "enable" if enabled else "disable"
    out.document(command, session=_session_info(shell), results=results)
    for entry in results:
        name = entry["id"]
        if entry["result"] == APPLIED:
            out.line(_("{}: enabled").format(name) if enabled else _("{}: disabled").format(name))
        elif entry["result"] == UNCHANGED and shell.shell_available:
            out.line(_("{}: already enabled").format(name) if enabled
                     else _("{}: already disabled").format(name))
        elif entry["result"] == UNCHANGED:
            out.line(_("{}: already enabled in the saved settings").format(name) if enabled
                     else _("{}: already disabled in the saved settings").format(name))
        elif entry["result"] == SAVED:
            out.line(f"{name}: {_unconfirmed_message()}")
        else:
            out.note(_("{}: failed: {}").format(name, entry["error"]))
    if not out.as_json and enabled and shell.extensions_globally_disabled():
        out.note(_("GNOME extensions are turned off; enabled features start once they are "
                   "turned on (gsettings set org.gnome.shell disable-user-extensions false)."))
    if any(e["result"] == "failed" for e in results):
        return EXIT_FAILED
    if any(e["result"] == SAVED for e in results):
        return EXIT_UNCONFIRMED
    return EXIT_OK


# --- presets ------------------------------------------------------------------

def _saved_id(saved):
    return os.path.basename(saved.directory)


def _find_saved(name):
    saved = presets.list_saved()
    by_id = [p for p in saved if _saved_id(p) == name]
    if by_id:
        return by_id[0]
    matches = [p for p in saved if p.name == name] or \
        [p for p in saved if p.name.casefold() == name.casefold()]
    if not matches:
        raise Failure(_("No saved preset is called “{}”. See deskence preset list.").format(name))
    if len(matches) > 1:
        raise Failure(_("Several saved presets are called “{}”; use one of their IDs: {}")
                      .format(name, ", ".join(_saved_id(p) for p in matches)))
    return matches[0]


def _describe_plan(out, plan):
    for change in plan.changes:
        out.line(f"  {presets.module_title(change.module)}: {change.name}: "
                 f"{_short(change.old)} → {_short(change.new)}")
    for module, on in plan.features.items():
        out.line("  " + (_("Feature {}: enable") if on else _("Feature {}: disable")).format(module))
    if plan.icon:
        out.line("  " + _("Dock: the custom applications button image"))
    for text in plan.warnings:
        out.note(_("Warning: {}").format(text))
    for text in plan.skipped:
        out.note(_("Skipped: {}").format(text))


def _plan_json(plan):
    return {
        "changes": [{"module": c.module, "setting": c.name, "old": c.old, "new": c.new}
                    for c in plan.changes],
        "features": dict(plan.features),
        "image": bool(plan.icon),
        "warnings": list(plan.warnings),
        "skipped": list(plan.skipped),
    }


def _apply_plan(session, plan, out):
    """Applies a preset plan with the same code as the settings window;
    returns the exit status."""
    from . import appsicon
    session.feature_results = {}
    grid = appgrid.AppGrid()
    try:
        presets.apply_plan(plan, session.store, features=session.features(),
                           set_feature=session.set_feature, import_icon=appsicon.import_icon,
                           backup_path=presets.backup_path(),
                           setters=control.preset_setters(grid, session.set_feature))
    except presets.ApplyError as e:
        message = _("The preset was not applied: {}.").format(e.error)
        if e.kept:
            message += " " + _("These changes could not be put back: {}.").format(
                ", ".join(e.kept))
        else:
            message += " " + _("The previous settings were restored.")
        raise Failure(message) from e
    except (OSError, appsicon.InvalidIcon, ValueError, GLib.Error) as e:
        raise Failure(_("The preset was not applied; nothing was changed. {}").format(e)) from e
    wrong = control.verify(session.store, {(c.schema, c.key): c.new for c in plan.changes
                                           if (c.schema, c.key) != (presets.APP_GRID,
                                                                    "sort-mode")})
    if wrong:
        raise Failure(_("The preset was applied only in part; these settings were not saved: "
                        "{}. Undo it with: deskence preset undo").format(
                            ", ".join(f"{s} {k}" for s, k in wrong)))
    unconfirmed = [m for m, r in session.feature_results.items() if r == SAVED]
    if unconfirmed:
        out.note(_("Features {}: {}").format(", ".join(unconfirmed), _unconfirmed_message()))
        return EXIT_UNCONFIRMED
    return EXIT_OK


def cmd_preset_list(args, session, out):
    saved = presets.list_saved()
    items = [{"id": _saved_id(p), "name": p.name, "created": p.created or None,
              "pinned-apps": "pinned-apps" in p.data,
              "folder-stacks": "folder-stacks" in p.data,
              "images": bool(p.assets)} for p in saved]
    out.document("preset list", presets=items)
    if not out.as_json:
        if not items:
            out.line(_("No saved presets."))
            return EXIT_OK
        rows = [(_("NAME"), _("ID"), _("CREATED"))]
        rows += [(i["name"], i["id"], (i["created"] or "")[:19].replace("T", " "))
                 for i in items]
        for row in _table(rows):
            out.line(row)
    return EXIT_OK


def _show_plan(out, plan, title):
    if plan.empty:
        out.line(_("Your settings already match the preset “{}”.").format(title))
    else:
        count = len(plan.changes) + len(plan.features) + (1 if plan.icon else 0)
        out.line(ngettext("Preset “{}” changes {} setting:", "Preset “{}” changes {} settings:",
                          count).format(title, count))
    _describe_plan(out, plan)


def cmd_preset_apply(args, session, out):
    saved = _find_saved(args.name)
    plan = presets.plan_import(saved.data, session.store,
                               control.import_context(session.features()), saved.assets)
    _show_plan(out, plan, saved.name)
    if plan.empty or args.dry_run:
        out.document("preset apply", name=saved.name, id=_saved_id(saved), dry_run=args.dry_run,
                     plan=_plan_json(plan), applied=False)
        if args.dry_run and not plan.empty:
            out.line(_("Nothing was changed (--dry-run)."))
        return EXIT_OK
    _confirm(args, out, _("Apply the preset?"))
    session.writable()
    code = _apply_plan(session, plan, out)
    out.document("preset apply", name=saved.name, id=_saved_id(saved), dry_run=False,
                 plan=_plan_json(plan), applied=True, confirmed=code == EXIT_OK)
    out.line(_("Preset “{}” applied. Undo it with: deskence preset undo").format(saved.name))
    return code


def cmd_preset_import(args, session, out):
    with tempfile.TemporaryDirectory(prefix="deskence-import-") as work:
        try:
            data, assets = presets.read_file(args.file, work)
        except presets.PresetError as e:
            raise Failure(_("Cannot import {}: {}").format(args.file, e)) from e
        stem = os.path.splitext(os.path.basename(args.file))[0]
        name = args.name if args.name is not None else data.get("name")
        if not isinstance(name, str) or not name.strip():
            name = stem
        name = name.strip()[:presets.MAX_NAME_LENGTH]
        existing = [p for p in presets.list_saved() if p.name.casefold() == name.casefold()]
        if existing and not args.replace:
            raise Failure(_("A saved preset is already called “{}”. Choose another name with "
                            "--name, or replace it with --replace.").format(name))
        replaces = [_saved_id(p) for p in existing]
        # Only what was read and checked is kept.
        data = dict(data, name=name)
        data.pop("assets", None)
        files = {}
        if assets:
            member = f"assets/{presets.ICON_ASSET}.png"
            data["assets"] = {presets.ICON_ASSET: member}
            files[member] = assets[presets.ICON_ASSET]
        plan = presets.plan_import(data, session.store,
                                   control.import_context(session.features()), assets)

        def save():
            target = presets.save(data, files)
            for old in existing:
                presets.delete(old)
            return os.path.basename(target)

        if args.apply:
            _show_plan(out, plan, name)
        else:
            for text in plan.warnings:
                out.note(_("Warning: {}").format(text))
            for text in plan.skipped:
                out.note(_("Skipped: {}").format(text))
        if args.dry_run:
            out.document("preset import", name=name, dry_run=True, replaces=replaces,
                         plan=_plan_json(plan), imported=False, applied=False)
            out.line(_("The preset “{}” is valid and would be saved; nothing was changed "
                       "(--dry-run).").format(name))
            return EXIT_OK
        if not args.apply or plan.empty:
            saved_id = save()
            out.document("preset import", name=name, id=saved_id, dry_run=False,
                         replaces=replaces, plan=_plan_json(plan), imported=True, applied=False)
            out.line(_("Preset “{}” saved as {}. Apply it with: deskence preset apply {}")
                     .format(name, saved_id, saved_id))
            return EXIT_OK
        _confirm(args, out, _("Save and apply the preset?"))
        session.writable()
        saved_id = save()
        code = _apply_plan(session, plan, out)
        out.document("preset import", name=name, id=saved_id, dry_run=False, replaces=replaces,
                     plan=_plan_json(plan), imported=True, applied=True,
                     confirmed=code == EXIT_OK)
        out.line(_("Preset “{}” saved as {} and applied. Undo it with: deskence preset undo")
                 .format(name, saved_id))
        return code


def cmd_preset_export(args, session, out):
    path = os.path.abspath(args.file)
    if os.path.isdir(path):
        raise Failure(_("{} is a folder; give a file name.").format(args.file))
    if os.path.lexists(path) and not args.force:
        raise Failure(_("{} already exists. Use --force to replace it.").format(args.file))
    preset, files = presets.export_preset(
        session.store, args.name or _("Deskence Settings"), session.features(),
        pinned=args.pinned, stacks=args.stacks, assets=args.images)
    try:
        presets.write_preset(path, preset, files or None)
    except OSError as e:
        raise Failure(_("Cannot write {}: {}").format(args.file, e.strerror or e)) from e
    out.document("preset export", file=path, archive=bool(files))
    out.line((_("Settings exported to {} (an archive with images).") if files
              else _("Settings exported to {}.")).format(path))
    if args.images and not files:
        out.note(_("No custom image is in use, so the file is plain JSON."))
    return EXIT_OK


def cmd_preset_undo(args, session, out):
    record = presets.load_undo(presets.backup_path())
    if record is None:
        raise Failure(_("There is no applied preset to undo."))
    plan = presets.plan_undo(record, session.store, session.features())
    changed = plan.conflicts
    restored = [g.label for g in plan.groups if not g.conflict] + \
        [presets.module_title(m) for m, _b, c in plan.features if not c]
    if plan.legacy is not None:
        out.line(_("The settings return to how they were right before the last import."))
    elif plan.empty:
        out.line(_("The preset changed nothing that could be undone."))
    else:
        out.line(_("Undoing “{}” restores:").format(plan.name))
        for label in restored + (changed if args.include_changed else []):
            out.line(f"  {label}")
        if changed and not args.include_changed:
            out.note(_("Changed after the preset was applied, so left as they are (add "
                       "--include-changed to undo them too): {}").format(", ".join(changed)))
    if args.dry_run:
        out.document("preset undo", dry_run=True, undone=False, restores=restored,
                     changed_since=changed)
        out.line(_("Nothing was changed (--dry-run)."))
        return EXIT_OK
    if not plan.empty:
        _confirm(args, out, _("Undo the preset?"))
        session.writable()
        session.feature_results = {}
        grid = appgrid.AppGrid()
        try:
            left = presets.undo(plan, session.store, session.set_feature,
                                control.preset_setters(grid, session.set_feature),
                                include_conflicts=args.include_changed)
        except (OSError, ValueError, GLib.Error) as e:
            raise Failure(_("The preset was undone only in part: {}").format(e)) from e
    else:
        left = []
    try:
        os.unlink(presets.backup_path())
    except OSError:
        pass
    out.document("preset undo", dry_run=False, undone=True, restores=restored,
                 changed_since=changed, left=left)
    out.line(_("Previous settings restored."))
    unconfirmed = [m for m, r in getattr(session, "feature_results", {}).items() if r == SAVED]
    if unconfirmed:
        out.note(_("Features {}: {}").format(", ".join(unconfirmed), _unconfirmed_message()))
        return EXIT_UNCONFIRMED
    return EXIT_OK


# --- reset --------------------------------------------------------------------

def cmd_reset(args, session, out):
    if args.all and args.scopes:
        raise Failure(_("Give what to restore or --all, not both."), EXIT_USAGE)
    if not args.all and not args.scopes:
        raise Failure(_("Name what to restore, or use --all. Choices: {}").format(
            ", ".join(control.RESET_SCOPES)), EXIT_USAGE)
    unknown = [s for s in args.scopes if s not in control.RESET_SCOPES]
    if unknown:
        raise Failure(_("Unknown choice: {}. Choices: {}").format(
            ", ".join(unknown), ", ".join(control.RESET_SCOPES)), EXIT_USAGE)
    scopes = ["all"] if args.all else list(dict.fromkeys(args.scopes))
    store = session.store
    enabled = session.features()
    plans = [control.plan_reset(store, scope, enabled) for scope in scopes]

    def describe():
        return [{"scope": p.scope,
                 "settings": [{"schema": s, "key": k, "value": v} for s, k, v in p.changes],
                 "custom-order": p.custom_order,
                 "disables-feature": ["app-grid"] if p.disables_sorting else []}
                for p in plans]

    if all(p.empty for p in plans):
        out.document("reset", dry_run=args.dry_run, plans=describe(), reset=False)
        out.line(_("Everything is at its default already; nothing to restore."))
        return EXIT_OK
    for plan in plans:
        if plan.empty:
            continue
        out.line(_("Restored to the default ({}):").format(
            _("all of Deskence") if plan.scope == "all" else plan.scope))
        for schema, key, value in plan.changes:
            out.line(f"  {schema} {key}: {_short(value)}")
        if plan.custom_order:
            out.line("  " + _("The applications view returns to your own order."))
        if plan.disables_sorting:
            out.line("  " + _("The app-grid feature (alphabetical order) is turned off."))
    out.line(_("Not changed: other enabled features, pinned applications, files on the "
               "desktop, custom images, saved presets and the clipboard history."))
    if args.dry_run:
        out.document("reset", dry_run=True, plans=describe(), reset=False)
        out.line(_("Nothing was changed (--dry-run)."))
        return EXIT_OK
    _confirm(args, out, _("Restore these settings?"))
    session.writable()
    session.feature_results = {}
    grid = appgrid.AppGrid()
    planned = describe()
    for plan in plans:
        control.reset(store, plan, grid, session.set_feature)
    left = [f"{s} {k}" for p in plans for s, k, _v in p.changes
            if store.settings(s).get_user_value(k) is not None]
    out.document("reset", dry_run=False, plans=planned, reset=not left, failed=left)
    if left:
        raise Failure(_("Some settings could not be restored: {}").format(", ".join(left)))
    out.line(_("Default settings restored."))
    unconfirmed = [m for m, r in session.feature_results.items() if r == SAVED]
    if unconfirmed:
        out.note(_("Features {}: {}").format(", ".join(unconfirmed), _unconfirmed_message()))
        return EXIT_UNCONFIRMED
    return EXIT_OK


# --- diagnostics --------------------------------------------------------------

def cmd_diagnostics(args, session, out):
    report = diagnostics.collect(session.version, session.shell, session.store)
    if out.as_json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(diagnostics.to_text(report))
    return EXIT_OK


# --- Command line -------------------------------------------------------------

class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        print(_("{}: error: {}").format(self.prog, message), file=sys.stderr)
        sys.exit(EXIT_USAGE)


def build_parser(version):
    features_text = ", ".join(IDS)
    parser = Parser(
        prog="deskence",
        description=_("Settings of Deskence from the command line. Without a command, the "
                      "settings window opens (deskence [--page PAGE])."),
        epilog=_("Features: {}. Exit status: 0 done, 1 failed, 2 invalid command line, "
                 "3 not confirmed, 4 saved but not confirmed in the running GNOME session. "
                 "See man deskence.").format(features_text))
    parser.add_argument("--version", action="version", version=f"deskence {version}")
    commands = parser.add_subparsers(dest="command", metavar=_("COMMAND"), parser_class=Parser)

    def command(name, help_text, func, json_option=True):
        p = commands.add_parser(name, help=help_text, description=help_text)
        p.set_defaults(func=func)
        if json_option:
            p.add_argument("--json", action="store_true",
                           help=_("print a JSON document instead of text"))
        return p

    command("status", _("show the saved and the running state of each feature"), cmd_status)
    for name, enabled, text in (
            ("enable", True, _("turn features on")),
            ("disable", False, _("turn features off; their settings are kept"))):
        p = command(name, text, lambda a, s, o, e=enabled: cmd_switch(a, s, o, e))
        p.add_argument("modules", nargs="*", metavar=_("FEATURE"),
                       help=_("one of: {}").format(features_text))
        p.add_argument("--all", action="store_true",
                       help=_("all Deskence features (never other extensions)"))

    preset = commands.add_parser("preset", help=_("list, apply, import and export presets"),
                                 description=_("Presets are saved in {}.").format(
                                     presets.presets_directory()))
    preset_commands = preset.add_subparsers(dest="preset_command", metavar=_("ACTION"),
                                            parser_class=Parser, required=True)

    def preset_command(name, help_text, func):
        p = preset_commands.add_parser(name, help=help_text, description=help_text)
        p.set_defaults(func=func, preset=preset)
        p.add_argument("--json", action="store_true",
                       help=_("print a JSON document instead of text"))
        return p

    def confirming(p):
        p.add_argument("--dry-run", action="store_true",
                       help=_("only show what would change"))
        p.add_argument("-y", "--yes", action="store_true",
                       help=_("do not ask for confirmation"))

    preset_command("list", _("show the saved presets"), cmd_preset_list)
    p = preset_command("apply", _("apply a saved preset"), cmd_preset_apply)
    p.add_argument("name", metavar=_("NAME"), help=_("name or ID of a saved preset"))
    confirming(p)
    p = preset_command("import", _("check a preset file and save it among the presets"),
                       cmd_preset_import)
    p.add_argument("file", metavar=_("FILE"), help=_("a .json preset or a .deskence archive"))
    p.add_argument("--name", help=_("save it under this name"))
    p.add_argument("--replace", action="store_true",
                   help=_("replace a saved preset of the same name"))
    p.add_argument("--apply", action="store_true", help=_("also apply it"))
    confirming(p)
    p = preset_command("export", _("write the current settings to a file"), cmd_preset_export)
    p.add_argument("file", metavar=_("FILE"))
    p.add_argument("--name", help=_("name stored in the preset"))
    p.add_argument("--pinned", action="store_true", help=_("include pinned applications"))
    p.add_argument("--stacks", action="store_true", help=_("include folders in the dock"))
    p.add_argument("--images", action="store_true",
                   help=_("include custom images (writes an archive)"))
    p.add_argument("--force", action="store_true", help=_("replace an existing file"))
    p = preset_command("undo", _("undo the last applied preset"), cmd_preset_undo)
    p.add_argument("--include-changed", action="store_true",
                   help=_("also undo settings changed after the preset was applied"))
    confirming(p)

    p = command("reset", _("restore default settings"), cmd_reset)
    p.add_argument("scopes", nargs="*", metavar=_("PART"),
                   help=_("one of: {}").format(", ".join(control.RESET_SCOPES)))
    p.add_argument("--all", action="store_true",
                   help=_("all Deskence settings; also turns off the app-grid feature"))
    confirming(p)

    command("diagnostics", _("show a report for bug reports (nothing is sent)"),
            cmd_diagnostics)
    return parser


def main(argv, version, pkgdatadir):
    parser = build_parser(version)
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else EXIT_USAGE
    out = Output(getattr(args, "json", False))
    session = Session(version, pkgdatadir)
    try:
        return args.func(args, session, out)
    except Failure as e:
        if str(e):
            if out.as_json:
                command = " ".join(c for c in (args.command,
                                               getattr(args, "preset_command", None)) if c)
                json.dump({"format": FORMAT_ID, "version": FORMAT_VERSION,
                           "command": command, "error": str(e), "exit-status": e.code},
                          sys.stdout, ensure_ascii=False, indent=2)
                sys.stdout.write("\n")
            print(_("deskence: {}").format(e), file=sys.stderr)
        return e.code
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 130

