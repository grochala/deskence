# SPDX-License-Identifier: GPL-3.0-or-later
"""Migration of stored settings between releases.

Each step upgrades from version N-1 to N and only touches keys of Deskence.
Values the user set explicitly are converted, never reset. Settings of
Better GNOME Desktop, the former name, are copied over first (rename.py) and
then go through the same steps.
"""

import os
import re
import shutil

CURRENT_VERSION = 5


def _to_1(root):
    # 0 -> 1: first release with a settings version; nothing to convert.
    pass


def _to_2(root):
    """1 -> 2 (0.2.0).

    The applications button became a fixed part of the dock, outside the
    scrollable list; "apps-button-position" keeps its meaning ("start" is
    left or top, "end" right or bottom) in both dock lengths, so it needs no
    conversion. A custom button image chosen by a development build may be
    a copy that is not square, which GNOME Shell would stretch: it is
    imported again in the current form. A custom image that no longer exists
    falls back to the default icon explicitly.
    """
    dock = root.get_child("dock")
    path = dock.get_string("apps-button-custom-icon")
    if not path:
        return
    name = os.path.basename(path)
    from . import appsicon
    if re.fullmatch(re.escape(appsicon.PREFIX) + r"[0-9a-f]{16}\.png", name):
        return
    if not os.path.isfile(path):
        if dock.get_string("apps-button-icon") == "custom":
            dock.set_string("apps-button-icon", "default")
        dock.set_string("apps-button-custom-icon", "")
        return
    try:
        dock.set_string("apps-button-custom-icon", appsicon.import_icon(path))
    except (appsicon.InvalidIcon, OSError):
        if dock.get_string("apps-button-icon") == "custom":
            dock.set_string("apps-button-icon", "default")
        dock.set_string("apps-button-custom-icon", "")


def _to_3(root):
    """2 -> 3 (0.3.0).

    In a whole-edge dock the application list now always starts at the top
    (vertical) or left (horizontal) end, whatever end the applications
    button is at; "apps-button-position" still only places the button, so
    it is kept as it is and there is no key that aligns the list. The
    applications view got its own background color ("app-grid-custom-color",
    "app-grid-color"), off by default: its transparency keys and the dock
    background keys keep their values and stay independent of it.
    """
    dock = root.get_child("dock")
    # Nothing is converted; reading the keys checks that they exist.
    for key in ("apps-button-position", "app-grid-custom-transparency"):
        dock.get_value(key)


def _to_4(root, legacy_directory=None, directory=None):
    """3 -> 4 (0.4.0): the project was renamed to Deskence.

    The settings themselves were copied from the former schema before this
    runs (rename.py). A custom applications button image copied into the
    former data folder (better-gnome-desktop) is copied into the new one
    (deskence) and the key follows it once the copy is complete. The former
    file stays: the former settings still point at it. Until this runs the
    former path keeps working, as the dock reads whatever path the key
    holds; if the copy fails the key is kept.
    """
    from . import appsicon
    legacy_directory = legacy_directory or appsicon.legacy_icon_directory()
    directory = directory or appsicon.icon_directory()
    dock = root.get_child("dock")
    path = dock.get_string("apps-button-custom-icon")
    if not path or os.path.dirname(path) != legacy_directory or \
            not appsicon.is_icon_copy(path) or not os.path.isfile(path):
        return
    target = os.path.join(directory, os.path.basename(path))
    try:
        os.makedirs(directory, exist_ok=True)
        shutil.copyfile(path, target + ".tmp")
        os.replace(target + ".tmp", target)
        with open(path, "rb") as a, open(target, "rb") as b:
            if a.read() != b.read():
                return
    except OSError:
        return
    dock.set_string("apps-button-custom-icon", target)


def _to_5(root):
    """4 -> 5 (0.6.0).

    New settings only: folders in the dock, window peeking, the order of the
    applications view, the clipboard history and keeping the computer awake.
    They start at their defaults; the applications view keeps the custom
    arrangement GNOME already has (sort-mode "custom"), so nothing the user
    arranged changes. The applications view colors stay in the dock schema
    (app-grid-*) where they were: only the page showing them moved.
    """
    root.get_child("dock").get_value("app-grid-custom-color")


STEPS = {1: _to_1, 2: _to_2, 3: _to_3, 4: _to_4, 5: _to_5}


def migrate(root):
    """root: Gio.Settings for io.github.deskence.Deskence."""
    version = root.get_uint("settings-version")
    if version >= CURRENT_VERSION:
        return False
    for target in range(version + 1, CURRENT_VERSION + 1):
        STEPS[target](root)
    root.set_uint("settings-version", CURRENT_VERSION)
    return True
