# SPDX-License-Identifier: GPL-3.0-or-later
"""File clipboard formats shared with Files (Nautilus).

GNOME applications exchange copied and cut files as
"x-special/gnome-copied-files": the operation on the first line, then one
URI per line. text/uri-list is offered too for other applications.
"""

GNOME_COPIED_FILES = "x-special/gnome-copied-files"
URI_LIST = "text/uri-list"
TEXT_PLAIN = "text/plain;charset=utf-8"


def encode_gnome_copied_files(uris, cut):
    lines = ["cut" if cut else "copy"] + list(uris)
    return "\n".join(lines).encode("utf-8")


def decode_gnome_copied_files(data):
    """Return (cut, uris) or None for malformed data."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n")]
    lines = [line for line in lines if line]
    if not lines or lines[0] not in ("copy", "cut"):
        return None
    uris = [line for line in lines[1:] if "://" in line or line.startswith("file:")]
    if not uris:
        return None
    return lines[0] == "cut", uris


def encode_uri_list(uris):
    return "".join(uri + "\r\n" for uri in uris).encode("utf-8")


def decode_uri_list(data):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.startswith("#")]
