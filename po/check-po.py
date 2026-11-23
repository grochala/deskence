#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks the translations of Deskence, without anything beyond Python and
msgfmt (from gettext).

  check-po.py --check     fails when a catalog is broken or out of date
  check-po.py --status    shows how complete each translation is
  check-po.py --glossary  prints the key terms of every translation
                          (po/GLOSSARY.md is made with it)
  check-po.py --same-texts OLD.pot NEW.pot
                          fails when the two templates have different
                          texts (deskence.pot not regenerated after a
                          change of the sources)

--check, for every language in LINGUAS:
- the catalog exists and msgfmt --check accepts it (syntax, header, plural
  forms, python-brace-format and javascript-format placeholders);
- it has exactly the texts of deskence.pot: a catalog that was not merged
  after the template changed is out of date (run
  "meson compile -C _build deskence-update-po");
- translated texts keep the placeholders ({}, %s, %d; {0}, {1}… may
  reorder the {} of the original) and the keyboard mnemonic (one "_"), and
  the plural forms are all filled in;
- the search keywords of the desktop file end with ";", and the name of the
  language is translated and unique.
Untranslated texts are not an error: they are shown in English. --status
lists them, with the fuzzy ones and those marked "# NEEDS-REVIEW:".
"""

import argparse
import ast
import os
import re
import subprocess
import sys
import tempfile

PO_DIR = os.path.dirname(os.path.abspath(__file__))
DOMAIN = "deskence"
NAME_CONTEXT = "Name of this language, in this language"
REVIEW = "NEEDS-REVIEW:"
PLACEHOLDER = re.compile(r"\{\d*\}|%[sd]")
# Translations may reorder brace placeholders with {0}, {1}…, which
# str.format() accepts for a "{} … {}" original.
NUMBERED = re.compile(r"\{\d+\}")
# A mnemonic: "_" before a letter, not inside an identifier like
# DIRECTORY_ or folder_stacks.
MNEMONIC = re.compile(r"(?<![A-Za-z0-9_])_(?=\w)|(?<=[^\W_])_(?=[^\W\d_])")
# Texts whose "_" is never a mnemonic.
NO_MNEMONIC_SOURCES = ("gschema.xml", "metainfo.xml", ".desktop")


class Entry:
    def __init__(self):
        self.context = None
        self.msgid = None
        self.plural = None
        self.msgstr = []
        self.flags = set()
        self.references = []
        self.translator_comments = []
        self.obsolete = False

    @property
    def key(self):
        return (self.context, self.msgid)

    @property
    def translated(self):
        return bool(self.msgstr) and all(self.msgstr) and "fuzzy" not in self.flags


def parse(path):
    """The entries of a PO file, the header first."""
    entries, entry, field = [], None, None

    def finish():
        if entry is not None and entry.msgid is not None:
            entries.append(entry)

    with open(path, encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line.strip():
                finish()
                entry, field = None, None
                continue
            if entry is None:
                entry = Entry()
            if line.startswith("#~"):
                entry.obsolete = True
            elif line.startswith("#,"):
                entry.flags.update(f.strip() for f in line[2:].split(","))
            elif line.startswith("#:"):
                entry.references += line[2:].split()
            elif line.startswith("# ") or line == "#":
                entry.translator_comments.append(line[2:])
            elif line.startswith("#"):
                pass
            elif line.startswith('"'):
                value = ast.literal_eval(line)
                if field == "msgstr":
                    entry.msgstr[-1] += value
                else:
                    setattr(entry, field, getattr(entry, field) + value)
            else:
                keyword, _, value = line.partition(" ")
                try:
                    value = ast.literal_eval(value)
                except (SyntaxError, ValueError):
                    raise SystemExit(f"{path}:{number}: cannot read this line")
                if keyword == "msgctxt":
                    entry.context, field = value, "context"
                elif keyword == "msgid":
                    entry.msgid, field = value, "msgid"
                elif keyword == "msgid_plural":
                    entry.plural, field = value, "plural"
                elif keyword == "msgstr" or keyword.startswith("msgstr["):
                    entry.msgstr.append(value)
                    field = "msgstr"
                else:
                    raise SystemExit(f"{path}:{number}: unknown keyword {keyword}")
    finish()
    return [e for e in entries if not e.obsolete]


def header(entries):
    fields = {}
    for line in entries[0].msgstr[0].splitlines():
        name, _, value = line.partition(":")
        fields[name.strip()] = value.strip()
    return fields


def linguas():
    with open(os.path.join(PO_DIR, "LINGUAS"), encoding="utf-8") as f:
        return [word for line in f for word in line.split("#")[0].split()]


def has_mnemonic(entry, text):
    if any(ref.split(":")[0].endswith(NO_MNEMONIC_SOURCES) for ref in entry.references):
        return None
    return len(MNEMONIC.findall(text))


def check_catalog(code, template):
    problems = []
    path = os.path.join(PO_DIR, code + ".po")
    if not os.path.isfile(path):
        return [f"{code}: listed in LINGUAS, but {code}.po is missing"]
    msgfmt = os.environ.get("MSGFMT", "msgfmt")
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run([msgfmt, "--check", "-o", os.path.join(tmp, "x.mo"), path],
                                capture_output=True, text=True)
    if result.returncode:
        problems.append(f"{code}: msgfmt --check failed:\n{result.stderr.strip()}")
    entries = parse(path)
    fields = header(entries)
    if fields.get("Language") != code:
        problems.append(f"{code}: the header says Language: {fields.get('Language')}")
    if "Plural-Forms" not in fields:
        problems.append(f"{code}: the header has no Plural-Forms")
    nplurals = re.search(r"nplurals=(\d+)", fields.get("Plural-Forms", ""))
    nplurals = int(nplurals.group(1)) if nplurals else 2

    keys = {e.key for e in entries[1:]}
    missing = [k for k in template if k not in keys]
    extra = [k for k in keys if k not in template]
    if missing or extra:
        problems.append(f"{code}: out of date with deskence.pot ({len(missing)} missing, "
                        f"{len(extra)} no longer used); run "
                        f"\"meson compile -C _build {DOMAIN}-update-po\"")

    for entry in entries[1:]:
        if not entry.translated:
            continue
        where = f"{code}: {entry.msgid[:60]!r}"
        sources = [entry.msgid] if entry.plural is None else [entry.msgid, entry.plural]
        if entry.plural is not None and len(entry.msgstr) != nplurals:
            problems.append(f"{where}: {len(entry.msgstr)} plural forms, Plural-Forms says {nplurals}")
        expected = sorted(PLACEHOLDER.findall(sources[-1]))
        for text in entry.msgstr:
            numbered = NUMBERED.findall(text)
            if numbered and sorted(numbered) != [f"{{{i}}}" for i in range(len(numbered))]:
                problems.append(f"{where}: numbered placeholders must be {{0}}…{{n}}, each once: {text!r}")
            found = sorted(NUMBERED.sub("{}", p) for p in PLACEHOLDER.findall(text))
            # One plural form may say "one" instead of the number (%d).
            if found != expected and not (
                    entry.plural is not None and
                    sorted(found + ["%d"]) == expected and nplurals > 1):
                problems.append(f"{where}: placeholders {found} instead of {expected}: {text!r}")
            wanted = has_mnemonic(entry, entry.msgid)
            if wanted is not None and has_mnemonic(entry, text) != wanted:
                problems.append(f"{where}: needs {wanted} mnemonic(s) (\"_\"): {text!r}")
        if any(ref.split(":")[0].endswith(".desktop.in.in") for ref in entry.references) \
                and entry.msgid.endswith(";") and not entry.msgstr[0].endswith(";"):
            problems.append(f"{where}: keywords must end with \";\"")
    return problems


def template_keys():
    return {e.key for e in parse(os.path.join(PO_DIR, DOMAIN + ".pot"))[1:]}


def check():
    template = template_keys()
    codes = linguas()
    problems = []
    if codes != sorted(set(codes)):
        problems.append("LINGUAS: keep the codes sorted and listed once")
    for name in sorted(os.listdir(PO_DIR)):
        if name.endswith(".po") and name[:-3] not in codes:
            problems.append(f"{name} is not listed in LINGUAS, so it is not installed")
    names = {}
    for code in codes:
        problems += check_catalog(code, template)
        path = os.path.join(PO_DIR, code + ".po")
        if os.path.isfile(path):
            for entry in parse(path):
                if entry.context == NAME_CONTEXT:
                    name = entry.msgstr[0] if entry.translated else ""
                    if not name or name == entry.msgid:
                        problems.append(f"{code}: the name of the language is not translated")
                    elif name in names:
                        problems.append(f"{code}: \"{name}\" also names {names[name]}")
                    names[name] = code
    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"{len(codes)} translations checked, {len(problems)} problem(s).")
    return 1 if problems else 0


def status():
    template = template_keys()
    total = len(template)
    print(f"{total} texts in deskence.pot\n")
    print(f"{'Code':8} {'Language':22} {'Done':>6} {'Untr.':>6} {'Fuzzy':>6} "
          f"{'Review':>6}  Reviewed  Up to date")
    for code in linguas():
        path = os.path.join(PO_DIR, code + ".po")
        if not os.path.isfile(path):
            print(f"{code:8} missing")
            continue
        entries = parse(path)
        fields = header(entries)
        by_key = {e.key: e for e in entries[1:]}
        current = [by_key[k] for k in template if k in by_key]
        done = sum(e.translated for e in current)
        fuzzy = sum("fuzzy" in e.flags for e in current)
        review = sum(any(c.startswith(REVIEW) for c in e.translator_comments) for e in current)
        name = next((e.msgstr[0] for e in current if e.context == NAME_CONTEXT and e.translated), "")
        print(f"{code:8} {name:22} {100 * done / total:5.1f}% {total - done - fuzzy:6} {fuzzy:6} "
              f"{review:6}  {fields.get('X-Deskence-Reviewed', 'no'):8}  "
              f"{'yes' if set(by_key) == template else 'no'}")
    print("\nReviewed: a native speaker read the whole translation (X-Deskence-Reviewed"
          "\nin the header). Review: texts marked \"# NEEDS-REVIEW:\" by the translator.")
    return 0


# The terms that name features and places of Deskence, in the order of the
# glossary, as texts of deskence.pot (without mnemonics).
GLOSSARY = [
    "Dock", "Desktop Icons", "Applications View", "Top Bar", "Windows", "Clipboard",
    "Clipboard History", "Keep Awake", "Always on Top", "Presets", "Folders in the Dock",
    "Pinned Applications", "Pin", "Trash", "Hover Highlight", "Application Folders",
    "Title Bar Buttons", "Keyboard Shortcuts", "Application Icons", "Desktop Settings",
    "Show Apps", "Restore _Default", "Same as the System ({})",
]


def glossary():
    codes = linguas()
    columns = {}
    for code in codes:
        terms = {}
        for entry in parse(os.path.join(PO_DIR, code + ".po"))[1:]:
            if entry.translated and entry.plural is None:
                terms.setdefault(entry.msgid, entry.msgstr[0])
        columns[code] = terms
    print("# Glossary of Deskence translations\n")
    print("Generated by `po/check-po.py --glossary` from the catalogs; use these")
    print("terms for the same things in new texts. Mnemonics (`_`) are left out.\n")
    for term in GLOSSARY:
        print(f"## {term.replace('_', '')}\n")
        print("| Code | Translation |")
        print("|---|---|")
        for code in codes:
            text = columns[code].get(term, "")
            text = re.sub(r"\(_\w\)", "", text)  # "取消(_C)"
            text = text.replace("_", "").replace("\u00ad", "").replace("|", "\\|")
            print(f"| {code} | {text} |")
        print()
    return 0


def same_texts(old, new):
    keys = [{e.key for e in parse(path)[1:]} for path in (old, new)]
    added, removed = keys[1] - keys[0], keys[0] - keys[1]
    for context, msgid in sorted(added, key=str):
        print(f"new in the sources: {msgid[:70]!r}", file=sys.stderr)
    for context, msgid in sorted(removed, key=str):
        print(f"no longer in the sources: {msgid[:70]!r}", file=sys.stderr)
    if added or removed:
        print(f"{DOMAIN}.pot is out of date; run "
              f"\"meson compile -C _build {DOMAIN}-pot {DOMAIN}-update-po\"", file=sys.stderr)
        return 1
    print(f"{DOMAIN}.pot matches the sources.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--status", action="store_true")
    group.add_argument("--glossary", action="store_true")
    group.add_argument("--same-texts", nargs=2, metavar=("OLD", "NEW"))
    args = parser.parse_args()
    if args.same_texts:
        return same_texts(*args.same_texts)
    if args.glossary:
        return glossary()
    return check() if args.check else status()


if __name__ == "__main__":
    sys.exit(main())
