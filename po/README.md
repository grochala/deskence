# Translating Deskence

Deskence uses GNU gettext with one domain, `deskence`, for everything a
user can read:

| Source | Shown by |
|---|---|
| `src/deskence/*.py`, `src/deskence/ui/*.ui` | the settings window and the `deskence` command |
| `extensions/*/*.js` | the dock, tray, clipboard history and Keep Awake in GNOME Shell |
| `desktop-icons/deskence_desktop/*.py` | the desktop icons |
| `data/*.desktop.in.in`, `data/*.metainfo.xml.in` | application menus and software centres |
| `data/schemas/*.gschema.xml` | summaries and descriptions in dconf Editor |

The files with strings are listed in `POTFILES.in`; the template is
`deskence.pot`, each language has a catalog `<code>.po`, and `LINGUAS` lists
the catalogs that are built and installed (as
`<localedir>/<code>/LC_MESSAGES/deskence.mo`).

The settings window and the command line follow the system language or the
language chosen on the General page. The GNOME Shell extensions and the
desktop icons always follow the language of the GNOME session.

## State of the translations

All 28 catalogs translate every text of the template. Apart from Polish
(written by the project's author), they were prepared with machine
assistance in November 2026 and **have not been reviewed by native
speakers yet**: they use GNOME's usual terms and were checked for
placeholders, mnemonics, plural forms and layout, but wording and grammar
need a native reader. Each such catalog says so in its header
(`X-Deskence-Reviewed: no`). Texts the translator was least sure of are
marked with a `# NEEDS-REVIEW:` comment explaining why (Irish and Maltese
have the most).

    meson compile -C _build deskence-po-status

shows, per language, how much is translated, fuzzy, marked for review and
whether the catalog matches the template.

## After changing strings in the code

    meson compile -C _build deskence-pot deskence-update-po

regenerates `deskence.pot` from the sources and merges it into every
catalog (`msgmerge`). New texts are untranslated and changed ones become
fuzzy; both are shown in English until a translator handles them.
`meson test` runs `check-po`, which fails when a catalog is broken or was
not merged after the template changed; CI also fails when `deskence.pot`
was not regenerated after the sources changed.

## Improving a translation

1. Edit `po/<code>.po` with any PO editor (Gtranslator, Poedit, Lokalize) or
   a text editor.
2. Check it: `msgfmt --check -o /dev/null po/<code>.po` and
   `python3 po/check-po.py --check` (or `meson test -C _build check-po`).
3. Try it: `LANGUAGE=<code> deskence --help` after installing, or choose the
   language on the General page of the settings. For the GNOME Shell parts,
   log in with that system language.
4. When a native speaker has read the whole catalog, set
   `X-Deskence-Reviewed: yes` in its header and remove the
   `# NEEDS-REVIEW:` comments that were resolved.

## Adding a language

1. `msginit -i po/deskence.pot -o po/<code>.po -l <code>` (the code as a
   gettext locale directory name: `pt_BR`, `sr@latin`).
2. Add the code to `LINGUAS` (sorted, one per line).
3. Translate the entry with the context *Name of this language, in this
   language* first: it is how the language appears in the list of the
   settings.
4. Run the checks above; `meson install` then installs the catalog, and the
   RPM and DEB packages pick it up without changes (`%find_lang`,
   `usr/share/locale`).

A regional variant without a catalog of its own can be pointed at the
closest one in `po/meson.build` (`locale_aliases`), as `zh_HK` uses
`zh_TW`: gettext only falls back from `zh_HK` to `zh`, never to `zh_TW`.

## Conventions

- **Terms**: use the terms of [GLOSSARY.md](GLOSSARY.md) (generated with
  `python3 po/check-po.py --glossary > po/GLOSSARY.md`) and the names GNOME
  uses in your language for its own parts (activities overview, top bar,
  quick settings, Files, Settings, Extensions).
- **Keep untranslated**: Deskence, GNOME, GNOME Shell, command and option
  names (`deskence preset undo`, `--yes`), GSettings key names and values in
  quotes (`"autohide"`, `folder-stacks`), paths, D-Bus names, key names on
  keyboards (`Ctrl`, `Shift`, `Escape`) unless your language names them
  differently in GNOME.
- **Mnemonics**: a `_` before a letter marks the Alt shortcut of labels from
  `.ui` files and dialogs; keep exactly one, on a letter of your
  translation. CJK translations add it in brackets: `取消(_C)`.
- **Placeholders**: `{}` (Python) and `%s`, `%d` (JavaScript) must all be
  kept. Python placeholders may be reordered with numbers, `{1} … {0}`;
  JavaScript ones cannot be reordered. Comments starting with `Translators:`
  say what a placeholder stands for.
- **Composed texts**: some short texts fill a `{}` of another one, for
  example "left" in "Preview: dock at the {} of the screen" and "a dock" in
  "Also provides {}."; translate them in the form that fits there (the
  comments name the sentence).
- **Plurals**: fill every form of your `Plural-Forms`. A form for one may
  spell the number out instead of `%d`.
- **Long words**: page names in the sidebar have little room. Long compound
  words may contain a soft hyphen (U+00AD) where they can break
  (`Anwendungs­übersicht`); search ignores it.
- **Search keywords**: the comma-separated keyword lists are what people
  type to find a setting; translate them as people would search and keep a
  few English words, so that the way back from an unreadable language
  stays open. In the `.desktop` keywords keep the `;` separators and the
  final `;`.
- **Typography**: use the quotation marks and spacing of your language
  (French narrow no-break spaces, German „…“ or »…«, CJK full-width
  punctuation) and `…` for an ellipsis.
