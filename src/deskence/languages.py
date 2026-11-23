# SPDX-License-Identifier: GPL-3.0-or-later
"""The language of the Deskence application: its settings window and its
command line.

The "language" setting holds the code of a translation shipped with
Deskence ("pl"), "en" for the English original texts, or "" to follow the
system. The list of languages is read from the installed translations
(LOCALEDIR/<code>/LC_MESSAGES/deskence.mo), so it grows with them; each
translation names its own language (LANGUAGE_NAME).

apply() runs in the launcher before anything is translated. It only
changes this process: LANGUAGE in its environment, read by Python's gettext
and by the C library (GtkBuilder, GTK and libadwaita texts) whenever a text
is translated. The C library ignores LANGUAGE under the C locale, so then
LC_MESSAGES is set as well, to a UTF-8 locale that is installed; in the
environment, since GTK sets the locale again from it when it starts.
Nothing of the system or of other applications changes; programs started
from the window get the environment the application was started with
(original_environment()).

The GNOME Shell extensions and the desktop icons stay in the language of
GNOME Shell (the system's): GJS translates through the locale of the whole
GNOME Shell process, which must not be changed for one extension.

A saved code that is not valid or whose translation is no longer installed
falls back to English, and texts missing from a translation are shown in
English, as gettext does.
"""

import gettext
import locale
import os
import re

DOMAIN = "deskence"
SCHEMA = "io.github.deskence.Deskence"
KEY = "language"
ENGLISH = "en"
SYSTEM = ""
# Language codes as directory names of translations: "pl", "pt_BR",
# "sr@latin". Anything else (a path, an empty string) is never looked up.
CODE = re.compile(r"[a-z]{2,3}(?:_[A-Z]{2})?(?:@[a-z]+)?")


def C_(context, text):
    """Marks text for translation in context, translated later."""
    return context, text


# Translators: the name of your language, in your language (for example
# "Polski", "Deutsch"). It is shown in the list of languages of Deskence,
# so that it can be found whatever language is shown.
LANGUAGE_NAME = C_("Name of this language, in this language", "English")

_localedir = None
# Variables apply() changed, with their values before; None: not set.
_original = {}
# The language apply() chose, None: the system's.
_active = None


def available(localedir=None):
    """Codes of the translations shipped with Deskence and English, sorted."""
    localedir = localedir or _localedir
    codes = {ENGLISH}
    try:
        # os.listdir(None) would list the current directory.
        names = os.listdir(localedir) if localedir else []
    except OSError:
        names = []
    for name in names:
        if CODE.fullmatch(name) and os.path.isfile(
                os.path.join(localedir, name, "LC_MESSAGES", DOMAIN + ".mo")):
            codes.add(name)
    return sorted(codes)


def native_name(code, localedir=None):
    """The name of the language in itself, as its translation gives it;
    the code when the translation does not."""
    if code == ENGLISH:
        return "English"
    try:
        translation = gettext.translation(DOMAIN, localedir or _localedir, languages=[code])
    except OSError:
        return code
    name = translation.pgettext(*LANGUAGE_NAME)
    return code if name == LANGUAGE_NAME[1] else name


def resolve(value, codes):
    """The language to use for the setting value: None for the system's,
    English when the value is not one of codes."""
    if not value:
        return None
    if CODE.fullmatch(value) and value in codes:
        return value
    return ENGLISH


def read_setting():
    """The saved value, "" when the settings cannot be read (the schema is
    not installed, an old schema without the key)."""
    try:
        from gi.repository import Gio
        source = Gio.SettingsSchemaSource.get_default()
        schema = source.lookup(SCHEMA, True) if source else None
        if schema is None or not schema.has_key(KEY):
            return SYSTEM
        return Gio.Settings.new(SCHEMA).get_string(KEY)
    except Exception:  # noqa: BLE001 - never stop the application starting
        return SYSTEM


def _setenv(name, value):
    _original.setdefault(name, os.environ.get(name))
    os.environ[name] = value


def _messages_locale(code):
    """Makes LANGUAGE count for the C library under the C locale. LC_ALL
    would override LC_MESSAGES; it is left as it is."""
    try:
        current = locale.setlocale(locale.LC_MESSAGES)
    except locale.Error:
        return
    if current not in ("C", "POSIX", "C.UTF-8", "C.utf8") or os.environ.get("LC_ALL"):
        return
    region = code.split("@")[0]
    if "_" not in region:
        region = f"{region}_{region.upper()}"
    for candidate in (f"{region}.UTF-8", "en_US.UTF-8", "en_GB.UTF-8"):
        try:
            locale.setlocale(locale.LC_MESSAGES, candidate)
        except locale.Error:
            continue
        _setenv("LC_MESSAGES", candidate)
        return


def apply(localedir, value=None):
    """Uses the language of the setting (or value) in this process."""
    global _localedir, _active
    _localedir = localedir
    if value is None:
        value = read_setting()
    _active = resolve(value, available(localedir))
    if _active is None:
        return None
    _setenv("LANGUAGE", _active)
    _messages_locale(_active)
    return _active


def active():
    """The language apply() chose, None for the system's."""
    return _active


def effective(value):
    """What the application would use after a restart with value."""
    return resolve(value, available())


def original_environment():
    """The variables apply() changed, with the values the application was
    started with (None: not set), for programs started from it."""
    return dict(_original)


def child_environment():
    """The whole environment for a program started from the application."""
    env = dict(os.environ)
    for name, value in _original.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    return env
