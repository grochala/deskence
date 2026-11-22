# SPDX-License-Identifier: GPL-3.0-or-later
"""Icon of the dock's applications button.

A custom image is copied into the user data folder of Deskence, so moving or deleting the original does not break the dock. The copy is a
square PNG with the image centered (GNOME Shell stretches icons to a
square), at most SIDE pixels. Its name contains a hash of its content: GNOME
Shell caches images by file name, and a new name makes it load the new image.
"""

import hashlib
import os
import re

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib  # noqa: E402

MAX_BYTES = 4 * 1024 * 1024
PREFIX = "apps-button-icon-"
FORMATS = ("png", "svg", "jpeg", "webp")
# Enough for 64 px dock icons at 300 % scale.
SIDE = 256


class InvalidIcon(Exception):
    pass


def icon_directory():
    return os.path.join(GLib.get_user_data_dir(), "deskence")


def legacy_icon_directory():
    """Data folder used before the rename to Deskence (0.4.0)."""
    return os.path.join(GLib.get_user_data_dir(), "better-gnome-desktop")


def is_icon_copy(path):
    """Whether path names a copy made by import_icon()."""
    return re.fullmatch(re.escape(PREFIX) + r"[0-9a-f]{16}\.png", os.path.basename(path)) is not None


def import_icon(source, directory=None):
    """Validate an image and copy it into the data folder.

    Returns the path of the copy. Raises InvalidIcon for files that are not
    readable images of a supported format; earlier copies are removed only
    after the new one was written.
    """
    directory = directory or icon_directory()
    try:
        with open(source, "rb") as f:
            data = f.read(MAX_BYTES + 1)
    except OSError as e:
        raise InvalidIcon(e.strerror or str(e)) from e
    if len(data) > MAX_BYTES:
        raise InvalidIcon("too-large")

    loader = GdkPixbuf.PixbufLoader()

    def size_prepared(_loader, width, height):
        # Vector images are drawn at full size; others are only shrunk.
        fmt = _loader.get_format()
        is_svg = fmt is not None and fmt.get_name() == "svg"
        longest = max(width, height, 1)
        factor = SIDE / longest if is_svg or longest > SIDE else 1
        _loader.set_size(max(1, round(width * factor)), max(1, round(height * factor)))
    loader.connect("size-prepared", size_prepared)
    try:
        loader.write(data)
        loader.close()
    except GLib.Error as e:
        raise InvalidIcon(e.message) from e
    fmt = loader.get_format()
    image = loader.get_pixbuf()
    if image is None or fmt is None or fmt.get_name() not in FORMATS:
        raise InvalidIcon("format")

    png = _square_png(image)
    name = PREFIX + hashlib.sha256(png).hexdigest()[:16] + ".png"
    target = os.path.join(directory, name)
    os.makedirs(directory, exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "wb") as f:
        f.write(png)
    os.replace(tmp, target)
    remove_icons(directory, keep=target)
    return target


def _square_png(image):
    """PNG bytes of the image centered on a transparent square."""
    width, height = image.get_width(), image.get_height()
    side = max(width, height)
    square = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, side, side)
    square.fill(0)
    image = image.add_alpha(False, 0, 0, 0)
    image.copy_area(0, 0, width, height, square, (side - width) // 2, (side - height) // 2)
    ok, data = square.save_to_bufferv("png", [], [])
    if not ok:
        raise InvalidIcon("format")
    return bytes(data)


def remove_icons(directory=None, keep=None):
    """Delete copies made by import_icon(), except keep."""
    directory = directory or icon_directory()
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        path = os.path.join(directory, name)
        if name.startswith(PREFIX) and path != keep:
            try:
                os.remove(path)
            except OSError:
                pass


def distribution_logo_names(os_info):
    """Icon names that may hold the distribution logo, most specific first.

    Same order as extensions/dock/logic.js distributionLogoNames().
    """
    names = []
    logo = (os_info.get("LOGO") or "").strip()
    if logo:
        names.append(logo)
    os_id = (os_info.get("ID") or "").strip().lower()
    if os_id and re.fullmatch(r"[a-z0-9._-]+", os_id):
        names += [f"{os_id}-logo-icon", f"emblem-{os_id}", f"{os_id}-logo"]
    names.append("distributor-logo")
    return list(dict.fromkeys(names))


def distribution_logo(icon_theme):
    """Name of the installed distribution logo icon, or None."""
    os_info = {"LOGO": GLib.get_os_info("LOGO"), "ID": GLib.get_os_info("ID")}
    return next((n for n in distribution_logo_names(os_info) if icon_theme.has_icon(n)), None)
