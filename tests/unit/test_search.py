# SPDX-License-Identifier: GPL-3.0-or-later
"""Searching the settings: matching, and finding the right row in the
current language.

The settings window builds its entries from its widgets; here the same
texts are read from the page templates and translated with the Polish
catalog compiled from po/pl.po, so the test searches what a Polish window
shows without starting GTK.
"""
import gettext
import os
import shutil
import subprocess
import xml.etree.ElementTree as ElementTree

import pytest

from deskence import search

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = os.path.join(ROOT, "src", "deskence", "ui")
PAGES = ("general", "dock", "desktop-icons", "app-grid", "top-bar", "windows", "clipboard")
ROW_CLASSES = {"AdwSwitchRow", "AdwActionRow", "AdwComboRow", "AdwSpinRow", "AdwButtonRow",
               "AdwExpanderRow", "AdwEntryRow"}


def _texts(element, translate):
    result = {}
    for prop in element.findall("property"):
        if prop.get("name") in ("title", "subtitle", "description") and prop.text:
            text = translate(prop.text) if prop.get("translatable") == "yes" else prop.text
            result[prop.get("name")] = text
    return result


def page_entries(translate):
    entries = []
    for page in PAGES:
        tree = ElementTree.parse(os.path.join(UI, f"{page}-page.ui"))
        template = tree.getroot().find("template")
        page_title = _texts(template, translate).get("title", page)

        def walk(element, group):
            for obj in element.iter("object"):
                if obj.get("class") == "AdwPreferencesGroup" and obj is not element:
                    texts = _texts(obj, translate)
                    walk_children(obj, (texts.get("title", ""), texts.get("description", "")))

        def walk_children(group_element, group):
            for obj in group_element.iter("object"):
                if obj.get("class") in ROW_CLASSES and obj.get("id"):
                    if f"{page}:{obj.get('id')}" in search.EXCLUDED:
                        continue
                    texts = _texts(obj, translate)
                    entries.append(search.Entry(
                        page=page, page_title=page_title, group=group[0],
                        title=texts.get("title", "").replace("_", "", 1),
                        subtitle=texts.get("subtitle", ""), description=group[1],
                        keywords=search.keyword_list(page) +
                        search.keyword_list(f"{page}:{obj.get('id')}"),
                        target=f"{page}:{obj.get('id')}", order=len(entries)))
        walk(template, None)
    return entries


@pytest.fixture(scope="module")
def polish(tmp_path_factory):
    msgfmt = shutil.which("msgfmt")
    if msgfmt is None:
        pytest.skip("msgfmt is not available")
    locale = tmp_path_factory.mktemp("locale")
    target = locale / "pl" / "LC_MESSAGES"
    target.mkdir(parents=True)
    subprocess.run([msgfmt, "-o", str(target / "deskence.mo"),
                    os.path.join(ROOT, "po", "pl.po")], check=True)
    old_language, old_domain = os.environ.get("LANGUAGE"), gettext.textdomain()
    os.environ["LANGUAGE"] = "pl"
    gettext.bindtextdomain("deskence", str(locale))
    gettext.textdomain("deskence")
    yield lambda text: gettext.dgettext("deskence", text)
    gettext.textdomain(old_domain)
    if old_language is None:
        del os.environ["LANGUAGE"]
    else:
        os.environ["LANGUAGE"] = old_language


def targets(entries, query):
    return [e.target for e in search.search(entries, query)]


def test_fold_ignores_case_and_diacritics():
    assert search.fold("Przezroczystość") == "przezroczystosc"
    assert search.fold("ŁÓDŹ") == "lodz"
    assert search.fold(None) == ""
    # Soft hyphens of translations do not stop a word from matching.
    assert search.fold("Anwendungs\u00adübersicht") == "anwendungsubersicht"


def test_every_word_must_match_and_titles_rank_first():
    entries = [
        search.Entry("dock", "Dock", "Appearance", "Background Transparency", order=1),
        search.Entry("dock", "Dock", "Appearance", "Background Color",
                     subtitle="Transparency of the dock is elsewhere", order=2),
        search.Entry("app-grid", "Applications View", "Background", "Transparency", order=3),
    ]
    found = search.search(entries, "transparency")
    assert [e.title for e in found][0] in ("Transparency", "Background Transparency")
    assert found[-1].title == "Background Color"
    # Ties keep the order of the window.
    assert [e.title for e in search.search(entries, "background transparency")] == \
        ["Background Transparency", "Background Color", "Transparency"]
    assert search.search(entries, "transparency nothing") == []
    assert search.search(entries, "   ") == []


def test_english(monkeypatch):
    monkeypatch.setenv("LANGUAGE", "en")
    entries = page_entries(lambda text: text)
    assert "dock:background_transparency_switch" in targets(entries, "transparency")
    assert targets(entries, "clipboard")[0].startswith("clipboard:")
    assert "app-grid:sort_row" in targets(entries, "sorting")[:2]
    assert "top-bar:awake_row" in targets(entries, "suspend")[:2]
    assert "dock:counts_row" in targets(entries, "unread")


def test_polish_queries_find_the_right_rows(polish):
    entries = page_entries(polish)
    assert any(e.title == "Własna przezroczystość tła" for e in entries)   # really Polish
    assert "dock:background_transparency_switch" in targets(entries, "przezroczystość")
    assert "dock:background_transparency_switch" in targets(entries, "przezroczystosc")
    assert targets(entries, "schowek")[0].startswith("clipboard:")
    assert "desktop-icons:enable_row" in targets(entries, "ikony")
    assert "top-bar:awake_row" in targets(entries, "usypianie")[:3]
    assert "app-grid:sort_row" in targets(entries, "sortowanie")[:2]
    assert targets(entries, "zzzz nic") == []


def test_settings_of_disabled_features_are_found(polish):
    # The index takes every row; whether its feature is on only matters
    # when the result is opened (window.py).
    entries = page_entries(polish)
    assert "clipboard:paste_row" in targets(entries, "wklejaj")


def test_keywords_point_at_existing_rows():
    ids = {}
    for page in PAGES:
        tree = ElementTree.parse(os.path.join(UI, f"{page}-page.ui"))
        ids[page] = {o.get("id") for o in tree.iter("object") if o.get("id")}
    for key in search.keywords():
        page, _sep, row = key.partition(":")
        assert page in ids, key
        assert not row or row in ids[page], key
    for key in search.EXCLUDED:
        page, _sep, row = key.partition(":")
        assert row in ids[page], key
