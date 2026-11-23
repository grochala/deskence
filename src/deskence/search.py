# SPDX-License-Identifier: GPL-3.0-or-later
"""Searching the settings window.

What can be found is read from the window itself (window.py builds the
entries from the rows of the pages: their titles and descriptions, the
group and the page they are in), so the search always matches what the
window shows, in the language it is shown in. KEYWORDS adds translatable
words for rows whose title does not contain what people search for. Only
rows defined in the page templates (and rows that ask for it) are entries;
rows showing user data, such as saved presets or folders in the dock, are
not, and neither are the clipboard history or the contents of presets.

Matching ignores case and diacritics ("przezroczystosc" finds
"przezroczystość") and every word of the query has to be found; a longer
word also matches by its beginning, so inflected forms are found
("usypianie" finds "Nie usypiaj").

Without GTK, so it can be tested.
"""

import unicodedata
from dataclasses import dataclass, field
from gettext import gettext as _

# Letters NFKD does not split into a base letter and a mark.
_EXTRA = str.maketrans({"ł": "l", "Ł": "l", "ø": "o", "Ø": "o", "đ": "d", "Đ": "d",
                        "ß": "ss", "æ": "ae", "œ": "oe"})


def fold(text):
    """Text for comparing: lower case, without diacritics."""
    text = (text or "").translate(_EXTRA)
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


def keywords():
    """Extra words to find rows by, keyed "page:row id" (or "page" for the
    page itself). Evaluated when searching, in the current language."""
    return {
        # Translators: words to search the settings by, separated by
        # commas; translate them as people would search, not literally.
        "dock": _("dock, taskbar, launcher, panel"),
        "dock:magnify_row": _("zoom, enlarge, magnification"),
        "dock:hide_row": _("autohide, auto-hide, intellihide, hiding"),
        "dock:show_stacks_row": _("stacks, folders, downloads"),
        "dock:previews_row": _("thumbnails, windows"),
        "dock:counts_row": _("badges, unread, notifications, messages"),
        "dock:progress_row": _("download, progress bar"),
        "desktop-icons": _("desktop, files, icons"),
        "app-grid": _("app grid, applications, launcher, menu"),
        "app-grid:sort_row": _("sorting, alphabetical, order, arrange"),
        "app-grid:folder_color_switch": _("folders, tiles, groups"),
        "app-grid:hover_color_switch": _("hover, highlight, pointer"),
        "top-bar": _("tray, indicators, status icons, notification area"),
        "top-bar:awake_row": _("suspend, sleep, caffeine, inhibit, awake"),
        "top-bar:screen_row": _("screen saver, blank screen, lock"),
        "windows": _("title bar, buttons, minimize, maximize"),
        "clipboard": _("copy, paste, clipboard, history"),
        "general:shortcuts_row": _("keyboard, hotkeys, keys, shortcuts"),
        "general:report_show_row": _("bug, diagnostics, report, problem"),
        "general:export_row": _("backup, presets, transfer"),
        # Also in English, to find the way back from a language one cannot
        # read.
        "general:language_row": _("language, translation") + ", language, English",
    }


# Rows that are not settings.
EXCLUDED = {"general:no_presets_row", "general:language_restart_row"}


@dataclass
class Entry:
    page: str          # name of the page ("dock")
    page_title: str
    group: str         # title of the group, may be empty
    title: str
    subtitle: str = ""
    description: str = ""   # of the group
    keywords: list = field(default_factory=list)
    target: object = None   # the row in the window
    order: int = 0          # position in the window


def keyword_list(key, table=None):
    text = (table if table is not None else keywords()).get(key, "")
    return [w.strip() for w in text.split(",") if w.strip()]


def _score(entry, words):
    title = fold(entry.title)
    rest = fold(" ".join([entry.subtitle, entry.group, entry.description, entry.page_title,
                          *entry.keywords]))
    total = 0
    for word in words:
        if title.startswith(word) or f" {word}" in f" {title}":
            total += 4
        elif word in title:
            total += 3
        elif word in rest:
            total += 1
        else:
            stem = word[:max(5, len(word) - 3)]
            if len(word) > 5 and stem in title:
                total += 2
            elif len(word) > 5 and stem in rest:
                total += 1
            else:
                return None
    return total


def search(entries, query):
    """The entries matching every word of query, best first."""
    words = fold(query).split()
    if not words:
        return []
    scored = [(score, entry) for entry in entries
              if (score := _score(entry, words)) is not None]
    scored.sort(key=lambda item: (-item[0], item[1].order))
    return [entry for _score_, entry in scored]
