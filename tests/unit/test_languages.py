# SPDX-License-Identifier: GPL-3.0-or-later
import os
import shutil
import subprocess

import pytest

from deskence import languages

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def localedir(tmp_path):
    """Installed translations: Polish (compiled from po/pl.po), a directory
    of another program, a stray file and a name that is not a code."""
    pl = tmp_path / "pl" / "LC_MESSAGES"
    pl.mkdir(parents=True)
    if shutil.which("msgfmt") is None:
        pytest.skip("msgfmt is not installed")
    subprocess.run(["msgfmt", "-o", str(pl / "deskence.mo"),
                    os.path.join(ROOT, "po", "pl.po")], check=True)
    (tmp_path / "de" / "LC_MESSAGES").mkdir(parents=True)
    (tmp_path / "de" / "LC_MESSAGES" / "other.mo").write_bytes(b"")
    (tmp_path / "README").write_text("")
    bad = tmp_path / "..evil" / "LC_MESSAGES"
    bad.mkdir(parents=True)
    (bad / "deskence.mo").write_bytes(b"")
    return str(tmp_path)


@pytest.fixture
def environment(monkeypatch):
    """apply() state and LANGUAGE are put back after each test."""
    monkeypatch.setattr(languages, "_localedir", None)
    monkeypatch.setattr(languages, "_original", {})
    monkeypatch.setattr(languages, "_active", None)
    monkeypatch.setattr(languages, "_messages_locale", lambda code: None)
    monkeypatch.delenv("LANGUAGE", raising=False)
    return monkeypatch


def test_available_lists_shipped_translations_and_english(localedir):
    assert languages.available(localedir) == ["en", "pl"]


def test_available_without_translations():
    assert languages.available("/nonexistent") == ["en"]
    assert languages.available(None) == ["en"]


def test_native_names(localedir):
    assert languages.native_name("en", localedir) == "English"
    assert languages.native_name("pl", localedir) == "Polski"
    # Without a translation, or one that does not name itself: the code.
    assert languages.native_name("de", localedir) == "de"


def test_resolve():
    codes = ["en", "pl"]
    assert languages.resolve("", codes) is None
    assert languages.resolve("pl", codes) == "pl"
    assert languages.resolve("en", codes) == "en"
    # Not installed, not a code: English.
    assert languages.resolve("de", codes) == "en"
    assert languages.resolve("../../etc", codes) == "en"
    assert languages.resolve("pl\n", codes) == "en"


def test_system_language_is_left_alone(localedir, environment):
    environment.setenv("LANGUAGE", "pl:en")
    assert languages.apply(localedir, "") is None
    assert os.environ["LANGUAGE"] == "pl:en"
    assert languages.active() is None
    assert languages.child_environment()["LANGUAGE"] == "pl:en"


def test_chosen_language_only_in_this_process(localedir, environment):
    assert languages.apply(localedir, "en") == "en"
    assert os.environ["LANGUAGE"] == "en"
    assert languages.active() == "en"
    # Programs started from the application: as before.
    assert "LANGUAGE" not in languages.child_environment()


def test_chosen_language_over_a_system_language(localedir, environment):
    environment.setenv("LANGUAGE", "de")
    assert languages.apply(localedir, "pl") == "pl"
    assert os.environ["LANGUAGE"] == "pl"
    assert languages.child_environment()["LANGUAGE"] == "de"
    # Applied again: the original stays the one from before.
    languages.apply(localedir, "en")
    assert languages.child_environment()["LANGUAGE"] == "de"


def test_unavailable_saved_language_falls_back_to_english(localedir, environment):
    assert languages.apply(localedir, "de") == "en"
    assert os.environ["LANGUAGE"] == "en"
    assert languages.effective("de") == "en"


def test_chosen_language_translates(localedir, environment):
    import gettext
    languages.apply(localedir, "pl")
    translation = gettext.translation("deskence", localedir, fallback=True)
    assert translation.gettext("Same as the System") == "Zgodny z systemem"
    # A text the translation does not have: the English original.
    assert translation.gettext("No such text in any translation") == \
        "No such text in any translation"
    languages.apply(localedir, "en")
    translation = gettext.translation("deskence", localedir, fallback=True)
    assert translation.gettext("Same as the System") == "Same as the System"


def test_unreadable_settings_mean_system(monkeypatch):
    from gi.repository import Gio

    def broken():
        raise RuntimeError("no settings")
    monkeypatch.setattr(Gio.SettingsSchemaSource, "get_default", broken)
    assert languages.read_setting() == ""


def test_c_locale_gets_a_messages_locale(localedir, environment):
    """Under the C locale the C library ignores LANGUAGE: LC_MESSAGES is
    set too, in the environment, and children get it back unset."""
    calls = []

    def setlocale(category, value=None):
        if value is None:
            return "C"
        calls.append(value)
        return value
    environment.setattr(languages, "_messages_locale", _real_messages_locale)
    environment.setattr(languages.locale, "setlocale", setlocale)
    environment.delenv("LC_ALL", raising=False)
    environment.delenv("LC_MESSAGES", raising=False)
    languages.apply(localedir, "pl")
    assert calls == ["pl_PL.UTF-8"]
    assert os.environ["LC_MESSAGES"] == "pl_PL.UTF-8"
    child = languages.child_environment()
    assert "LC_MESSAGES" not in child and "LANGUAGE" not in child
    assert languages.original_environment() == {"LANGUAGE": None, "LC_MESSAGES": None}


_real_messages_locale = languages._messages_locale
