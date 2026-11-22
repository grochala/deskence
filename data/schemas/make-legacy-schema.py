#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes the settings schema with the ID and path of Better GNOME Desktop.

Deskence reads the settings stored by Better GNOME Desktop (0.3.0 and older)
through this copy, compiled into the package data folder, to take them over
(src/deskence/rename.py). It is never installed among the system schemas.

    make-legacy-schema.py INPUT OUTPUT
"""

import sys

REPLACEMENTS = [
    ("io.github.deskence.Deskence", "io.github.bettergnome.Desktop"),
    ("/io/github/deskence/deskence/", "/io/github/bettergnome/desktop/"),
]

source, target = sys.argv[1:3]
with open(source, encoding="utf-8") as f:
    text = f.read()
for new, old in REPLACEMENTS:
    if new not in text:
        sys.exit(f"{source}: {new} not found")
    text = text.replace(new, old)
# Only the IDs, paths and keys matter here; no translations.
text = text.replace(' gettext-domain="deskence"', "")
with open(target, "w", encoding="utf-8") as f:
    f.write(text)
