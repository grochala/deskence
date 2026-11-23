# SPDX-License-Identifier: GPL-3.0-or-later
"""The General page: presets, moving settings and restoring defaults."""

import os
import shutil
import tempfile
from gettext import gettext as _
from gettext import ngettext

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import appgrid, appsicon, control, diagnostics, languages, presets
from .shortcuts import ShortcutsDialog
from .pages import FEATURE_UUIDS, UI, confirm


def _filters(*kinds):
    store = Gio.ListStore.new(Gtk.FileFilter)
    for kind in kinds:
        if kind == "json":
            f = Gtk.FileFilter(name=_("Presets (JSON)"))
            f.add_suffix("json")
        elif kind == "archive":
            f = Gtk.FileFilter(name=_("Presets With Images"))
            f.add_suffix(presets.ARCHIVE_SUFFIX[1:])
        else:
            f = Gtk.FileFilter(name=_("All Presets"))
            f.add_suffix("json")
            f.add_suffix(presets.ARCHIVE_SUFFIX[1:])
        store.append(f)
    return store


class PresetOptions(Adw.PreferencesGroup):
    """What a saved or exported preset includes besides the settings."""

    def __init__(self, name=None):
        super().__init__()
        self.name_row = None
        if name is not None:
            self.name_row = Adw.EntryRow(title=_("Name"), text=name)
            self.add(self.name_row)
        self.pinned_row = Adw.SwitchRow(title=_("Pinned Applications"))
        self.stacks_row = Adw.SwitchRow(title=_("Folders in the Dock"))
        self.assets_row = Adw.SwitchRow(
            title=_("Custom Images"),
            subtitle=_("Saved in an archive together with the settings"))
        for row in (self.pinned_row, self.stacks_row, self.assets_row):
            self.add(row)


@Gtk.Template(resource_path=UI + "general-page.ui")
class GeneralPage(Adw.PreferencesPage):
    __gtype_name__ = "DeskenceGeneralPage"

    startup_group = Gtk.Template.Child()
    desktop_at_login_row = Gtk.Template.Child()
    language_row = Gtk.Template.Child()
    language_restart_row = Gtk.Template.Child()
    language_restart_button = Gtk.Template.Child()
    presets_group = Gtk.Template.Child()
    no_presets_row = Gtk.Template.Child()
    save_row = Gtk.Template.Child()
    export_row = Gtk.Template.Child()
    import_row = Gtk.Template.Child()
    undo_row = Gtk.Template.Child()
    shortcuts_row = Gtk.Template.Child()
    report_show_row = Gtk.Template.Child()
    report_copy_row = Gtk.Template.Child()
    report_save_row = Gtk.Template.Child()
    reset_row = Gtk.Template.Child()

    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.store = presets.SettingsStore()
        self.appgrid = appgrid.AppGrid()
        self._rows = []
        self.settings = Gio.Settings.new(presets.SCHEMA)
        self.settings.bind("show-desktop-at-login", self.desktop_at_login_row, "active",
                           Gio.SettingsBindFlags.DEFAULT)
        shell.connect("changed", lambda *a: self._sync_startup())
        self._sync_startup()
        self._setup_language()
        self.save_row.connect("activated", lambda r: self._ask_save())
        self.export_row.connect("activated", lambda r: self._ask_export())
        self.import_row.connect("activated", lambda r: self._choose_import())
        self.undo_row.connect("activated", lambda r: self._ask_undo())
        self.shortcuts_row.connect("activated",
                                   lambda r: ShortcutsDialog(self.shell).present(self))
        self.report_show_row.connect("activated", lambda r: self._show_report())
        self.report_copy_row.connect("activated", lambda r: self._copy_report())
        self.report_save_row.connect("activated", lambda r: self._save_report())
        self.reset_row.connect("activated", lambda r: confirm(
            self, _("Restore Default Deskence Settings?"),
            _("All Deskence settings return to their defaults and the applications view "
              "returns to your own order. Folders in the dock are removed from it; the "
              "folders themselves are not touched. Enabled features, pinned applications, "
              "title bar buttons, saved presets and the clipboard history do not change."),
            _("_Restore"), self._reset))
        self._fill()
        # Presets saved, imported or applied elsewhere (the command line).
        self._fill_id = 0
        self._monitors = []
        for path, directory in ((presets.presets_directory(), True),
                                (presets.backup_path(), False)):
            try:
                file = Gio.File.new_for_path(path)
                monitor = file.monitor_directory(Gio.FileMonitorFlags.NONE, None) \
                    if directory else file.monitor_file(Gio.FileMonitorFlags.NONE, None)
            except GLib.Error:
                continue
            monitor.connect("changed", lambda *a: self._queue_fill())
            self._monitors.append(monitor)

    def _queue_fill(self):
        if not self._fill_id:
            self._fill_id = GLib.timeout_add(300, self._fill_later)

    def _fill_later(self):
        self._fill_id = 0
        self._fill()
        return GLib.SOURCE_REMOVE

    def _sync_startup(self):
        # Applied by the dock extension when the session starts.
        dock = self.shell.is_enabled(FEATURE_UUIDS["dock"])
        self.startup_group.set_sensitive(dock)
        self.startup_group.set_description(
            None if dock else _("Available while the Deskence dock is turned on."))

    # --- Language -------------------------------------------------------

    def _setup_language(self):
        # Every language in its own name, so that a wrong choice can be
        # undone without reading it.
        self._syncing_language = False
        self._language_codes = [languages.SYSTEM] + languages.available()
        names = [_("Same as the System")] + [languages.native_name(c)
                                            for c in self._language_codes[1:]]
        self.language_row.set_model(Gtk.StringList.new(names))
        self._sync_language()
        self.language_row.connect("notify::selected", lambda *a: self._language_chosen())
        # Also restored defaults, imported presets and the command line.
        self.settings.connect("changed::" + languages.KEY, lambda *a: self._sync_language())
        self.language_restart_button.connect(
            "clicked", lambda b: self.get_root().get_application().restart("general"))

    def _sync_language(self):
        value = self.settings.get_string(languages.KEY)
        # A code without a translation here is shown as what it means:
        # English.
        shown = value if value in self._language_codes else languages.effective(value)
        index = self._language_codes.index(shown or languages.SYSTEM)
        if self.language_row.get_selected() != index:
            self._syncing_language = True
            self.language_row.set_selected(index)
            self._syncing_language = False
        self.language_restart_row.set_visible(languages.effective(value) != languages.active())

    def _language_chosen(self):
        if self._syncing_language:
            return
        code = self._language_codes[self.language_row.get_selected()]
        if code == languages.SYSTEM:
            self.settings.reset(languages.KEY)
        elif self.settings.get_string(languages.KEY) != code:
            self.settings.set_string(languages.KEY, code)

    # --- Helpers --------------------------------------------------------

    def _toast(self, title, undo=False):
        root = self.get_root()
        if root is not None and hasattr(root, "toast"):
            root.toast(title, _("_Undo") if undo else None, self._undo if undo else None)

    def _error(self, heading, message):
        dialog = Adw.AlertDialog(heading=heading, body=message)
        dialog.add_response("close", _("_Close"))
        dialog.present(self)

    def _features(self):
        return control.enabled_features(self.shell)

    def _set_feature(self, module, enabled):
        self.shell.set_enabled(FEATURE_UUIDS[module], enabled)

    def _setters(self):
        return control.preset_setters(self.appgrid, self._set_feature)

    def _context(self):
        monitors = Gdk.Display.get_default().get_monitors()
        connectors = [monitors.get_item(i).get_connector() or ""
                      for i in range(monitors.get_n_items())]
        return control.import_context(self._features(), [c for c in connectors if c])

    # --- Saved presets ----------------------------------------------------

    def _fill(self):
        for row in self._rows:
            self.presets_group.remove(row)
        self._rows = []
        saved = presets.list_saved()
        self.no_presets_row.set_visible(not saved)
        for preset in saved:
            row = Adw.ActionRow(title=GLib.markup_escape_text(preset.name),
                                subtitle=self._describe(preset))
            apply = Gtk.Button(label=_("_Apply…"), use_underline=True, valign=Gtk.Align.CENTER)
            apply.connect("clicked", lambda b, p=preset: self._review(p.data, p.assets, p.name))
            row.add_suffix(apply)
            menu = Gio.Menu()
            for label, action in ((_("_Rename…"), "rename"), (_("_Export…"), "export"),
                                  (_("_Delete…"), "delete")):
                menu.append(label, f"preset.{action}")
            button = Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu,
                                    valign=Gtk.Align.CENTER, tooltip_text=_("More"))
            button.add_css_class("flat")
            group = Gio.SimpleActionGroup()
            for action, callback in (("rename", self._ask_rename), ("export", self._export_saved),
                                     ("delete", self._ask_delete)):
                a = Gio.SimpleAction.new(action, None)
                a.connect("activate", lambda _a, _p, c=callback, s=preset: c(s))
                group.add_action(a)
            button.insert_action_group("preset", group)
            row.add_suffix(button)
            self.presets_group.add(row)
            self._rows.append(row)
        self.undo_row.set_visible(os.path.isfile(presets.backup_path()))

    @staticmethod
    def _describe(preset):
        parts = []
        if "pinned-apps" in preset.data:
            parts.append(_("pinned applications"))
        if "folder-stacks" in preset.data:
            parts.append(_("folders in the dock"))
        if preset.assets:
            parts.append(_("images"))
        if not parts:
            return _("Settings")
        return _("Settings with {}").format(", ".join(parts))

    def _ask_save(self):
        options = PresetOptions(_("My Settings"))
        options.stacks_row.set_active(True)
        options.assets_row.set_active(True)
        dialog = Adw.AlertDialog(heading=_("Save Current Settings"), extra_child=options)
        dialog.add_response("cancel", _("_Cancel"))
        dialog.add_response("save", _("_Save"))
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")
        options.name_row.set_activates_default(True)

        def response(_d, result):
            if result == "save":
                self._save(options)
        dialog.connect("response", response)
        dialog.present(self)

    def _save(self, options):
        name = options.name_row.get_text().strip() or _("My Settings")
        preset, files = presets.export_preset(
            self.store, name, self._features(), pinned=options.pinned_row.get_active(),
            stacks=options.stacks_row.get_active(), assets=options.assets_row.get_active())
        try:
            presets.save(preset, files)
        except OSError as e:
            self._error(_("Cannot Save the Preset"), e.strerror or str(e))
            return
        self._fill()
        self._toast(_("Preset “{}” saved").format(name))

    def _ask_rename(self, preset):
        entry = Adw.EntryRow(title=_("Name"), text=preset.name, activates_default=True)
        group = Adw.PreferencesGroup()
        group.add(entry)
        dialog = Adw.AlertDialog(heading=_("Rename Preset"), extra_child=group)
        dialog.add_response("cancel", _("_Cancel"))
        dialog.add_response("rename", _("_Rename"))
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("rename")
        dialog.set_close_response("cancel")

        def response(_d, result):
            name = entry.get_text().strip()
            if result != "rename" or not name:
                return
            try:
                presets.rename(preset, name)
            except OSError as e:
                self._error(_("Cannot Rename the Preset"), e.strerror or str(e))
            self._fill()
        dialog.connect("response", response)
        dialog.present(self)

    def _ask_delete(self, preset):
        def delete():
            try:
                presets.delete(preset)
            except OSError as e:
                self._error(_("Cannot Delete the Preset"), e.strerror or str(e))
            self._fill()
        confirm(self, _("Delete Preset “{}”?").format(preset.name),
                _("The current settings do not change."), _("_Delete"), delete)

    def _export_saved(self, preset):
        archive = bool(preset.assets)
        self._choose_target(preset.name, archive,
                            lambda path: presets.export_saved(preset, path))

    # --- Export -----------------------------------------------------------

    def _ask_export(self):
        options = PresetOptions()
        options.stacks_row.set_active(True)
        dialog = Adw.AlertDialog(
            heading=_("Export Settings"),
            body=_("Settings are saved as a readable JSON file. With images, the file is an "
                   "archive with the settings and the images."),
            extra_child=options)
        dialog.add_response("cancel", _("_Cancel"))
        dialog.add_response("export", _("_Export…"))
        dialog.set_response_appearance("export", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("export")
        dialog.set_close_response("cancel")

        def response(_d, result):
            if result != "export":
                return
            preset, files = presets.export_preset(
                self.store, _("Deskence Settings"), self._features(),
                pinned=options.pinned_row.get_active(), stacks=options.stacks_row.get_active(),
                assets=options.assets_row.get_active())
            self._choose_target(_("Deskence Settings"), bool(files),
                                lambda path: presets.write_preset(path, preset, files or None))
        dialog.connect("response", response)
        dialog.present(self)

    def _choose_target(self, name, archive, write):
        suffix = presets.ARCHIVE_SUFFIX if archive else ".json"
        dialog = Gtk.FileDialog(title=_("Export Settings"), modal=True,
                                initial_name=name + suffix,
                                filters=_filters("archive" if archive else "json"))

        def done(d, result):
            try:
                file = d.save_finish(result)
            except GLib.Error:
                return
            path = file.get_path() if file else None
            if not path:
                self._error(_("Cannot Export"), _("Only local files can be used."))
                return
            if not path.endswith(suffix):
                path += suffix
            try:
                write(path)
            except OSError as e:
                self._error(_("Cannot Export"), e.strerror or str(e))
                return
            self._toast(_("Settings exported"))
        dialog.save(self.get_root(), None, done)

    # --- Import -----------------------------------------------------------

    def _choose_import(self):
        dialog = Gtk.FileDialog(title=_("Import Settings"), modal=True,
                                filters=_filters("all", "json", "archive"))

        def done(d, result):
            try:
                file = d.open_finish(result)
            except GLib.Error:
                return
            path = file.get_path() if file else None
            if not path:
                self._error(_("Cannot Import"), _("Only local files can be used."))
                return
            self._import_file(path)
        dialog.open(self.get_root(), None, done)

    def _import_file(self, path):
        work = tempfile.mkdtemp(prefix="import-", dir=self._work_dir())
        try:
            data, assets = presets.read_file(path, work)
        except presets.PresetError as e:
            shutil.rmtree(work, ignore_errors=True)
            self._error(_("Cannot Import"), str(e))
            return
        self._review(data, assets, data.get("name") or os.path.basename(path),
                     cleanup=lambda: shutil.rmtree(work, ignore_errors=True))

    @staticmethod
    def _work_dir():
        directory = os.path.join(GLib.get_user_cache_dir(), "deskence")
        os.makedirs(directory, exist_ok=True)
        return directory

    def _review(self, data, assets, name, cleanup=None):
        """Shows what a preset changes and applies it when confirmed."""
        plan = presets.plan_import(data, self.store, self._context(), assets)
        title = name if isinstance(name, str) else ""
        if plan.empty:
            if cleanup:
                cleanup()
            body = _("Your settings already match this preset.")
            if plan.skipped or plan.warnings:
                body += "\n\n" + "\n".join(plan.warnings + plan.skipped)
            dialog = Adw.AlertDialog(heading=_("Nothing to Change"), body=body)
            dialog.add_response("close", _("_Close"))
            dialog.present(self)
            return

        count = len(plan.changes) + len(plan.features) + (1 if plan.icon else 0)
        modules = ", ".join(presets.module_title(m) for m in plan.modules)
        body = ngettext("{} setting changes in: {}.", "{} settings change in: {}.",
                        count).format(count, modules)
        notes = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for text, css in ([(w, "warning") for w in plan.warnings] +
                          [(s, "dim-label") for s in plan.skipped]):
            label = Gtk.Label(label=text, wrap=True, xalign=0)
            label.add_css_class(css)
            notes.append(label)
        extra = None
        if plan.warnings or plan.skipped:
            extra = Gtk.ScrolledWindow(child=notes, propagate_natural_height=True,
                                       max_content_height=220,
                                       hscrollbar_policy=Gtk.PolicyType.NEVER)
        dialog = Adw.AlertDialog(heading=_("Apply “{}”?").format(title) if title
                                 else _("Apply Preset?"), body=body, extra_child=extra)
        dialog.add_response("cancel", _("_Cancel"))
        dialog.add_response("apply", _("_Apply"))
        dialog.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("apply")
        dialog.set_close_response("cancel")

        def response(_d, result):
            try:
                if result == "apply":
                    self._apply(plan)
            finally:
                if cleanup:
                    cleanup()
        dialog.connect("response", response)
        dialog.present(self)

    def _apply(self, plan):
        try:
            presets.apply_plan(plan, self.store, features=self._features(),
                               set_feature=self._set_feature, import_icon=appsicon.import_icon,
                               backup_path=presets.backup_path(), setters=self._setters())
        except presets.ApplyError as e:
            body = str(e.error) + "\n\n" + (
                _("These changes could not be put back: {}").format(", ".join(e.kept))
                if e.kept else _("Your previous settings were restored."))
            self._error(_("The Preset Was Not Applied"), body)
            self._fill()
            return
        except (OSError, appsicon.InvalidIcon, ValueError) as e:
            self._error(_("The Preset Was Not Applied"),
                        _("Nothing was changed.") + f"\n\n{e}")
            return
        self._fill()
        self._toast(_("Preset applied"), undo=True)

    def _ask_undo(self):
        self._undo(confirm_first=True)

    def _undo(self, *_args, confirm_first=False):
        """Undoes the last applied preset; settings changed since then are
        only undone when the user says so."""
        record = presets.load_undo(presets.backup_path())
        if record is None:
            self._error(_("Cannot Undo the Preset"), _("There is no applied preset to undo."))
            self._fill()
            return
        plan = presets.plan_undo(record, self.store, self._features())

        def run(include):
            try:
                presets.undo(plan, self.store, self._set_feature, self._setters(),
                             include_conflicts=include)
            except (OSError, ValueError) as e:
                self._error(_("Cannot Undo the Preset"), str(e))
                return
            try:
                os.unlink(presets.backup_path())
            except OSError:
                pass
            self._fill()
            self._toast(_("Previous settings restored"))

        changed = plan.conflicts
        if not changed:
            if confirm_first:
                confirm(self, _("Undo Last Applied Preset?"),
                        _("The settings the preset changed return to their values from "
                          "before it."), _("_Undo"), lambda: run(False), destructive=False)
            else:
                run(False)
            return
        dialog = Adw.AlertDialog(
            heading=_("Some Settings Changed Since"),
            body=_("These settings were changed after the preset was applied: {}. Undo "
                   "them too, or keep them as they are now?").format(", ".join(changed)))
        dialog.add_response("cancel", _("_Cancel"))
        dialog.add_response("keep", _("_Keep Them"))
        dialog.add_response("all", _("Undo _All"))
        dialog.set_response_appearance("keep", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("keep")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, r: run(r == "all") if r != "cancel" else None)
        dialog.present(self)

    # --- Bug reports ------------------------------------------------------

    def _report(self):
        toolkit = {"gtk": f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}."
                          f"{Gtk.get_micro_version()}",
                   "libadwaita": f"{Adw.get_major_version()}.{Adw.get_minor_version()}."
                                 f"{Adw.get_micro_version()}"}
        app = self.get_root().get_application()
        return diagnostics.to_text(diagnostics.collect(app.version, self.shell, self.store,
                                                       toolkit))

    def _show_report(self):
        text = self._report()
        view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                            top_margin=12, bottom_margin=12, left_margin=12, right_margin=12)
        view.get_buffer().set_text(text)
        view.update_property([Gtk.AccessibleProperty.LABEL], [_("Report")])
        copy = Gtk.Button(label=_("_Copy"), use_underline=True)
        copy.connect("clicked", lambda b: self._copy_report(text))
        save = Gtk.Button(label=_("_Save…"), use_underline=True)
        save.connect("clicked", lambda b: self._save_report(text))
        header = Adw.HeaderBar()
        header.pack_start(copy)
        header.pack_end(save)
        toolbar = Adw.ToolbarView(content=Gtk.ScrolledWindow(child=view, vexpand=True))
        toolbar.add_top_bar(header)
        dialog = Adw.Dialog(title=_("Information for Bug Reports"), child=toolbar,
                            content_width=640, content_height=560)
        dialog.present(self)

    def _copy_report(self, text=None):
        self.get_clipboard().set(text or self._report())
        self._toast(_("Diagnostics copied"))

    def _save_report(self, text=None):
        text = text or self._report()
        dialog = Gtk.FileDialog(title=_("Save Report"), modal=True,
                                initial_name="deskence-report.md")

        def done(d, result):
            try:
                file = d.save_finish(result)
            except GLib.Error:
                return
            try:
                file.replace_contents(text.encode(), None, False,
                                      Gio.FileCreateFlags.REPLACE_DESTINATION, None)
            except GLib.Error as e:
                self._error(_("Cannot Save the Report"), e.message)
                return
            self._toast(_("Report saved"))
        dialog.save(self.get_root(), None, done)

    # --- Defaults ---------------------------------------------------------

    def _reset(self):
        control.reset(self.store, control.plan_reset(self.store, "all", self._features()),
                      self.appgrid, self._set_feature)
        appsicon.remove_icons()
        self._toast(_("Default settings restored"))

