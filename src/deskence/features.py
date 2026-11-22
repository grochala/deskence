# SPDX-License-Identifier: GPL-3.0-or-later
"""The features of Deskence: one GNOME Shell extension each.

The identifiers are stable: presets store them, the command line takes
them, and the settings window, conflict detection and diagnostics use the
same list. The order is the order shown to the user.
"""

UUIDS = {
    "dock": "dock@deskence.github.io",
    "desktop-icons": "desktop-icons@deskence.github.io",
    "tray": "tray@deskence.github.io",
    "app-grid": "app-grid@deskence.github.io",
    "clipboard": "clipboard@deskence.github.io",
    "keep-awake": "keep-awake@deskence.github.io",
}

IDS = tuple(UUIDS)
