# SPDX-License-Identifier: GPL-3.0-or-later
"""Detection of other extensions that provide the same features.

Known extensions are matched by UUID. Other extensions are matched by name
as "may conflict", so the user can decide. Nothing is ever disabled without
the user asking for it.
"""

from dataclasses import dataclass

from . import features

# Extension states from GNOME Shell (misc/extensionUtils.js).
STATE_ACTIVE = 1
STATE_INACTIVE = 2
STATE_ERROR = 3
STATE_OUT_OF_DATE = 4
STATE_INITIALIZED = 6
STATE_DEACTIVATING = 7
STATE_ACTIVATING = 8

OUR_UUIDS = features.UUIDS

# Our extensions under the former name, Better GNOME Desktop. Right after an
# update they keep running until the next login, while GNOME Shell does not
# know the new ones yet; that is expected. Once it knows the new one, a
# former one still running (a copy in the user's extension folder) is a
# conflict.
LEGACY_UUIDS = {
    "dock": "dock@bettergnome.github.io",
    "desktop-icons": "desktop-icons@bettergnome.github.io",
    "tray": "tray@bettergnome.github.io",
}

KNOWN = {
    "dock": {
        "dash-to-dock@micxgx.gmail.com",
        "ubuntu-dock@ubuntu.com",
        "dash-to-panel@jderose9.github.com",
        "dash2dock-lite@icedman.github.com",
        "dock-from-dash@fthx",
        "zorin-taskbar@zorinos.com",
    },
    "desktop-icons": {
        "ding@rastersoft.com",
        "gtk4-ding@smedius.gitlab.com",
        "desktop-icons@csoriano",
        "desktopicons-neo@darkdemon",
    },
    "tray": {
        "appindicatorsupport@rgcjonas.gmail.com",
        "ubuntu-appindicators@ubuntu.com",
        "TopIcons@phocean.net",
        "topIconsFix@aleskva@devnullmail.com",
        "trayIconsReloaded@selfmade.pl",
    },
    "app-grid": {
        "AlphabeticalAppGrid@stuarthayhurst",
    },
    "clipboard": {
        "clipboard-indicator@tudmotu.com",
        "pano@elhan.io",
        "clipboard-history@alexsaveau.dev",
        "gnome-clipboard@b00f.github.io",
    },
    "keep-awake": {
        "caffeine@patapon.info",
        "espresso@coadmunkee.github.com",
    },
}

KEYWORDS = {
    "dock": ("dock", "taskbar", "dash to panel"),
    "desktop-icons": ("desktop icons", "desktop-icons", "icons on desktop"),
    "tray": ("appindicator", "app indicator", "tray icon", "topicons", "statusnotifier",
             "kstatusnotifier"),
    "app-grid": ("alphabetical", "app grid sort"),
    "clipboard": ("clipboard",),
    "keep-awake": ("caffeine", "keep awake", "inhibit suspend", "stay awake"),
}


@dataclass(frozen=True)
class Conflict:
    uuid: str
    name: str
    certain: bool


def is_running(info):
    return info.get("state") in (STATE_ACTIVE, STATE_ACTIVATING)


def find_conflicts(feature, extensions):
    """extensions: {uuid: info dict as returned by ListExtensions}."""
    result = []
    ours = set(OUR_UUIDS.values())
    for uuid, info in sorted(extensions.items()):
        if uuid in ours or not is_running(info):
            continue
        name = str(info.get("name", uuid))
        if uuid in LEGACY_UUIDS.values():
            if uuid == LEGACY_UUIDS.get(feature) and OUR_UUIDS[feature] in extensions:
                result.append(Conflict(uuid, name, True))
            continue
        if uuid in KNOWN[feature]:
            result.append(Conflict(uuid, name, True))
            continue
        text = f"{uuid} {name}".lower()
        if any(word in text for word in KEYWORDS[feature]):
            result.append(Conflict(uuid, name, False))
    return result
