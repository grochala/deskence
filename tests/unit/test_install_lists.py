# SPDX-License-Identifier: GPL-3.0-or-later
"""Every module of an extension is installed: a file missing from its
meson.build only shows up as an ImportError in GNOME Shell."""
import glob
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_every_extension_file_is_installed():
    for directory in glob.glob(os.path.join(ROOT, "extensions", "*", "")):
        with open(os.path.join(directory, "meson.build"), encoding="utf-8") as f:
            build = f.read()
        for path in glob.glob(os.path.join(directory, "*.js")) + \
                glob.glob(os.path.join(directory, "*.css")):
            assert f"'{os.path.basename(path)}'" in build, path
