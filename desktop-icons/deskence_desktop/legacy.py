# SPDX-License-Identifier: GPL-3.0-or-later
"""Compatibility with Better GNOME Desktop, the former name of Deskence.

After an update from Better GNOME Desktop (0.3.0 and older), GNOME Shell
keeps running the former desktop icons extension until the next login. That
extension starts this helper by its former path, a compatibility symlink
(/usr/libexec/better-gnome-desktop-icons), and only knows the former
protocol: the window title tag and the environment variable announcing the
areas pipe. Started
under that name, the helper speaks the former protocol; otherwise the
current one. To be removed together with the symlink.
"""

import os
import sys

HELPER_NAME = "better-gnome-desktop-icons"
TITLE_TAG = "@bettergnome-desktop:"
AREAS_ENV = "BETTERGNOME_DESKTOP_AREAS"

ACTIVE = os.path.basename(sys.argv[0] if sys.argv else "") == HELPER_NAME
