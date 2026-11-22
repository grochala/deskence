# SPDX-License-Identifier: GPL-3.0-or-later
"""Main window: sidebar navigation, searching the settings and the pages.

The search (search.py) reads the rows of the pages when it opens, so it
finds what the window shows, in its language. Choosing a result opens the
page, expands a collapsed row, scrolls to the row, highlights it for a
moment and gives it the keyboard focus. A row that is hidden until another
option is turned on, or dimmed because its feature is off, is not changed:
the window points at the switch that makes it available and says so.
Searching never turns anything on.
"""

from gettext import gettext as _

from gi.repository import Adw, Gdk, Gio, GLib, Graphene, Gtk

from . import search
from .general import GeneralPage
from .pages import (FEATURE_UUIDS, UI, AppGridPage, ClipboardPage, DesktopIconsPage, DockPage,
                    FeatureController, TopBarPage, WindowsPage)
from .shell import FeatureStatus, log_out

HIGHLIGHT_CLASS = "deskence-search-highlight"
HIGHLIGHT_MS = 1600
CSS = f"""
row.{HIGHLIGHT_CLASS} {{
  background-color: alpha(@accent_bg_color, 0.25);
  transition: background-color 250ms ease-out;
}}
"""

PAGES = (
    ("general", GeneralPage),
    ("dock", DockPage),
    ("desktop-icons", DesktopIconsPage),
    ("app-grid", AppGridPage),
    ("top-bar", TopBarPage),
    ("windows", WindowsPage),
    ("clipboard", ClipboardPage),
)


@Gtk.Template(resource_path=UI + "window.ui")
class Window(Adw.ApplicationWindow):
    __gtype_name__ = "DeskenceWindow"

    split_view = Gtk.Template.Child()
    sidebar_list = Gtk.Template.Child()
    sidebar_stack = Gtk.Template.Child()
    search_button = Gtk.Template.Child()
    search_bar = Gtk.Template.Child()
    search_entry = Gtk.Template.Child()
    results_list = Gtk.Template.Child()
    content_page = Gtk.Template.Child()
    stack = Gtk.Template.Child()
    banner = Gtk.Template.Child()
    toast_overlay = Gtk.Template.Child()

    def __init__(self, app, shell):
        super().__init__(application=app)
        self.shell = shell
        self.pages = {}
        for name, cls in PAGES:
            page = cls(shell)
            self.pages[name] = page
            self.stack.add_named(page, name)
            row = Adw.ActionRow(title=page.get_title(), activatable=True)
            row.add_prefix(Gtk.Image.new_from_icon_name(page.get_icon_name()))
            row.page_name = name
            self.sidebar_list.append(row)
        self.sidebar_list.connect("row-activated", self._on_row_activated)
        self._setup_search()
        self.banner.connect("button-clicked", lambda b: log_out())
        shell.connect("changed", lambda *a: self._sync_banner())
        self._sync_banner()
        self.show_page("general")

    # --- Search -------------------------------------------------------------

    def _setup_search(self):
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._entries = []
        self._highlighted = None
        self._highlight_id = 0
        self.search_bar.connect_entry(self.search_entry)
        self.search_bar.connect("notify::search-mode-enabled", self._on_search_mode)
        self.search_entry.connect("search-changed", lambda e: self._show_results())
        self.search_entry.connect("activate", lambda e: self._open_first())
        self.results_list.connect("row-activated", lambda l, row: self._reveal(row.entry))

        # Down from the entry goes to the results; Escape in the results
        # closes the search like it does in the entry.
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_entry_key)
        self.search_entry.add_controller(keys)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_results_key)
        self.results_list.add_controller(keys)

        action = Gio.SimpleAction.new("search", None)
        action.connect("activate", lambda *a: self.start_search())
        self.add_action(action)
        self.get_application().set_accels_for_action("win.search", ["<Control>f"])

    def start_search(self):
        self.split_view.set_show_content(False)
        self.search_bar.set_search_mode(True)
        self.search_entry.grab_focus()

    def _on_search_mode(self, bar, _pspec):
        if bar.get_search_mode():
            self._entries = self._index()
            self._show_results()
        else:
            self.search_entry.set_text("")
            self.sidebar_stack.set_visible_child_name("pages")

    def _on_entry_key(self, _c, keyval, _code, _state):
        if keyval == Gdk.KEY_Down:
            first = self.results_list.get_row_at_index(0)
            if first is not None and self.sidebar_stack.get_visible_child_name() == "results":
                first.grab_focus()
                return True
        return False

    def _on_results_key(self, _c, keyval, _code, state):
        if keyval == Gdk.KEY_Escape and not state & Gtk.accelerator_get_default_mod_mask():
            self.search_bar.set_search_mode(False)
            self.sidebar_list.grab_focus()
            return True
        return False

    def _index(self):
        """Entries for every row of every page, read from the widgets."""
        table = search.keywords()
        entries = []
        order = 0
        for name, page in self.pages.items():
            page_keywords = search.keyword_list(name, table)
            for row in _descendants(page):
                if not isinstance(row, Adw.PreferencesRow):
                    continue
                row_id = Gtk.Buildable.get_buildable_id(row)
                if not (row_id or getattr(row, "searchable", False)) or \
                        f"{name}:{row_id}" in search.EXCLUDED:
                    continue
                group = _ancestor(row, Adw.PreferencesGroup)
                order += 1
                entries.append(search.Entry(
                    page=name, page_title=page.get_title(),
                    group=group.get_title() or "" if group else "",
                    title=_plain(row.get_title(), row.get_use_underline()),
                    subtitle=row.get_subtitle() or "" if isinstance(row, Adw.ActionRow) else "",
                    description=group.get_description() or "" if group else "",
                    keywords=page_keywords + search.keyword_list(f"{name}:{row_id}", table),
                    target=row, order=order))
        return entries

    def _show_results(self):
        query = self.search_entry.get_text()
        while (row := self.results_list.get_row_at_index(0)) is not None:
            self.results_list.remove(row)
        if not query.strip():
            self.sidebar_stack.set_visible_child_name("pages")
            return
        found = search.search(self._entries, query)
        for entry in found:
            where = " › ".join(t for t in (entry.page_title, entry.group) if t)
            row = Adw.ActionRow(title=entry.title, subtitle=where, activatable=True,
                                use_markup=False)
            row.add_prefix(Gtk.Image.new_from_icon_name(self.pages[entry.page].get_icon_name()))
            row.entry = entry
            self.results_list.append(row)
        self.sidebar_stack.set_visible_child_name("results" if found else "empty")

    def _open_first(self):
        row = self.results_list.get_row_at_index(0)
        if row is not None and self.sidebar_stack.get_visible_child_name() == "results":
            self._reveal(row.entry)

    def _reveal(self, entry):
        """Shows the row of a result, or what makes it available."""
        row = entry.target
        # In a narrow window the content slides in first; its rows are only
        # laid out once that is done.
        sliding = self.split_view.get_collapsed() and not self.split_view.get_show_content()
        self.show_page(entry.page, reveal=True)
        for expander in _ancestors(row, Adw.ExpanderRow):
            expander.set_expanded(True)
        target, hint = row, None
        if not row.get_visible():
            # Shown once an option before it is turned on.
            switch = _previous_visible_row(row)
            if switch is not None:
                target = switch
                hint = _("Turn on “{}” to change “{}”.").format(
                    _plain(switch.get_title(), switch.get_use_underline()), entry.title)
        elif not row.is_sensitive():
            # What turned it off: the row itself (an option before it), or a
            # group (its feature is off, or something the group explains).
            cause = row
            while cause is not None and cause.get_sensitive():
                cause = cause.get_parent()
            controller = self._controller_for(entry.page, cause)
            switch = _previous_visible_row(row)
            if cause is row and isinstance(switch, Adw.SwitchRow):
                target = switch
                hint = _("Turn on “{}” to change “{}”.").format(
                    _plain(switch.get_title(), switch.get_use_underline()), entry.title)
            elif controller is not None and controller.switch_row is not None:
                target = controller.switch_row
                hint = _("“{}” is available after turning on “{}”.").format(
                    entry.title, _plain(target.get_title(), target.get_use_underline()))
            else:
                group = _ancestor(row, Adw.PreferencesGroup)
                reason = group.get_description() if group else ""
                hint = _("“{}” is not available now.").format(entry.title) + \
                    (f" {reason}" if reason else "")
        if sliding:
            handler = None

            def shown(_page):
                self.content_page.disconnect(handler)
                GLib.idle_add(self._focus, target)
            handler = self.content_page.connect("shown", shown)
        else:
            GLib.idle_add(self._focus, target)
        if hint:
            self.toast(hint)

    def _controller_for(self, page_name, widget):
        """The feature switch that dimmed widget, if any."""
        page = self.pages[page_name]
        for value in vars(page).values():
            if isinstance(value, FeatureController) and widget is not None and any(
                    widget is dependent for dependent in value.dependent):
                return value
        return None

    def _focus(self, target):
        if target.is_sensitive() and target.get_focusable():
            target.grab_focus()
        # Once the focus has been scrolled to and the page laid out: a third
        # from the top, clear of toasts at the bottom.
        GLib.timeout_add(100, self._place, target)
        if self._highlighted is not None:
            self._highlighted.remove_css_class(HIGHLIGHT_CLASS)
        if self._highlight_id:
            GLib.source_remove(self._highlight_id)
        target.add_css_class(HIGHLIGHT_CLASS)
        self._highlighted = target

        def done():
            target.remove_css_class(HIGHLIGHT_CLASS)
            self._highlighted = None
            self._highlight_id = 0
            return GLib.SOURCE_REMOVE
        self._highlight_id = GLib.timeout_add(HIGHLIGHT_MS, done)
        return GLib.SOURCE_REMOVE

    def _place(self, target):
        scrolled = _ancestor(target, Gtk.ScrolledWindow)
        if scrolled is not None and scrolled.get_child() is not None:
            ok, point = target.compute_point(scrolled.get_child(), Graphene.Point())
            adjustment = scrolled.get_vadjustment()
            if ok:
                # The point is in the visible part of the viewport; the
                # contents start at the current scroll offset.
                top = point.y + adjustment.get_value()
                adjustment.set_value(min(max(top - adjustment.get_page_size() / 3, 0),
                                         adjustment.get_upper() - adjustment.get_page_size()))
        return GLib.SOURCE_REMOVE

    def toast(self, title, button_label=None, callback=None):
        toast = Adw.Toast(title=title, use_markup=False)
        if button_label and callback:
            toast.set_button_label(button_label)
            toast.connect("button-clicked", callback)
        self.toast_overlay.add_toast(toast)

    def _on_row_activated(self, listbox, row):
        self.show_page(row.page_name)
        self.split_view.set_show_content(True)

    def show_page(self, name, reveal=False):
        """reveal: also show the page when the window is too narrow for the
        sidebar and the page side by side (a page asked for by name)."""
        if name not in self.pages:
            return
        page = self.pages[name]
        self.stack.set_visible_child(page)
        self.content_page.set_title(page.get_title())
        for row in self.sidebar_list:
            if row.page_name == name:
                self.sidebar_list.select_row(row)
        if reveal:
            self.split_view.set_show_content(True)

    def _sync_banner(self):
        states = {self.shell.status(uuid).state
                  for uuid in FEATURE_UUIDS.values() if self.shell.is_enabled(uuid)}
        if FeatureStatus.UPDATE_PENDING in states:
            self.banner.set_title(_("An update was installed. Log out and log in again to use it."))
            self.banner.set_revealed(True)
        elif FeatureStatus.NEEDS_LOGIN in states:
            self.banner.set_title(_("Log out and log in again to start the enabled features."))
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)


def _descendants(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _descendants(child)
        child = child.get_next_sibling()


def _ancestors(widget, kind):
    parent = widget.get_parent()
    while parent is not None:
        if isinstance(parent, kind):
            yield parent
        parent = parent.get_parent()


def _ancestor(widget, kind):
    return next(_ancestors(widget, kind), None)


def _previous_visible_row(row):
    sibling = row.get_prev_sibling()
    while sibling is not None:
        if isinstance(sibling, Adw.PreferencesRow) and sibling.get_visible():
            return sibling
        sibling = sibling.get_prev_sibling()
    return None


def _plain(title, mnemonic):
    """A title without its mnemonic underscore."""
    return title.replace("_", "", 1) if mnemonic and title else title or ""
