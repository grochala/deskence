# Stored data

Deskence stores only the data listed here. The package installs files under
`/usr` and `/etc/xdg/autostart`; nothing is copied into the home directory
by the package or the application.

| What | Where |
|---|---|
| Settings | dconf, `/io/github/deskence/deskence/` (schemas `io.github.deskence.Deskence*`) |
| Desktop icon positions | `$XDG_STATE_HOME/deskence/icon-positions.json` |
| Copy of a custom applications button image | `$XDG_DATA_HOME/deskence/` |
| Saved presets | `$XDG_DATA_HOME/deskence/presets/<name>-<id>/` |
| Undo record of the last applied preset | `$XDG_STATE_HOME/deskence/before-import.json` |
| Clipboard history (only when chosen) | `$XDG_DATA_HOME/deskence/clipboard/` |
| Cache (distribution logo silhouette, preset import work files) | `$XDG_CACHE_HOME/deskence/` |

Deskence also changes some GNOME settings, but only through its own
controls: `org.gnome.shell enabled-extensions` and `favorite-apps`,
`org.gnome.desktop.wm.preferences button-layout`,
`org.gnome.desktop.wm.keybindings toggle-above` and, for sorting, the
applications view layout (`app-picker-layout` and folder lists).

## Desktop icon positions

Format version 3: logical pixels relative to the top-left corner of the
monitor, plus the monitor connector; versions 1 and 2 are converted on load.
Free placement or snapping to the grid only applies when dropping icons;
"Align to Grid" is a separate action. Icons from a disconnected monitor,
under the dock or outside the area are moved temporarily without changing
their saved position, and return when the space is back.

## Clipboard history

By default the history lives in memory only and is gone after logging out.
With "Keep After Logging Out" set to pinned items or the whole history,
texts are saved in `history.json` and images as files next to it, in a
folder with mode 0700 and files with mode 0600. Choosing "Nothing" deletes
these files. Contents are never written to the log.

Not recorded: content marked with `x-kde-passwordManagerHint` (password
managers), anything while remembering is paused or the screen is locked, the
primary selection unless enabled, text over 1 MB and images over 8 MB. The
history holds 10 to 200 items (pinned items do not count) and 64 MB in total.
The extension also runs on the lock screen so the in-memory history survives
locking, but it records nothing there and its shortcut does not work.

## Presets

A preset is readable JSON:

- `format` (`io.github.deskence.Deskence.preset`), `version` (1), `name`,
  `settings-version`;
- `modules` – module → key → JSON value, enumerations as names;
- `features` – which features are enabled;
- optionally `pinned-apps` (`favorite-apps`), `folder-stacks` (entries and
  sorting) and `assets` (the applications button image).

Only the keys in the explicit `ENTRIES` list in `src/deskence/presets.py`
are exported: Deskence keys plus GNOME's `button-layout` and `toggle-above`.
Never the whole dconf database, the clipboard history, the paused state, the
saved applications view layout, a Keep Awake session or migration markers.

With an image the file is a ZIP archive with the `.deskence` extension:
`preset.json` at the root and `assets/<name>`. Only `preset.json` and known
assets with an exact `assets/[A-Za-z0-9._-]` name are read, and they are
written under names chosen by Deskence (limits: JSON 1 MB, asset 4 MB,
archive 16 MB or 32 entries). Nothing is extracted by names from the archive
or executed.

Folder stacks are stored by identity: `xdg:DOWNLOAD`, `home:relative/path`,
other folders as `file://` URIs. Paths from another home directory
(`/home/<user>/…`, `/var/home/…`) are moved to the current one on import when
the folder exists there.

Importing is two steps. `plan_import()` checks the format and version (newer
versions are rejected, older ones converted by `FORMAT_MIGRATIONS`), value
types and ranges, whether keys are writable and whether applications,
folders, images and monitors exist; it shows the changes, warnings and
skipped values and writes nothing; imported shortcuts that are not allowed
or clash with another Deskence or GNOME shortcut are left out with a warning.
`apply_plan()` first writes an undo record (format
`io.github.deskence.Deskence.undo`, version 1): for each setting the preset
changes, its value before, whether that value was set or only the default,
and the value the preset set; the same for features it turns on or off.
When writing fails half way, what was applied is put back where the value
is still the one the preset set, and the error says what could not be put
back. "Undo Last Applied Preset" (the toast after applying, the General
page, `deskence preset undo`) restores only those settings, and only where
they still have the preset's value; a setting changed since is reported
and left alone unless the user chooses to undo it too. Keys that make one
option (a custom color and the color, folders in the dock and their order,
the applications button icon and its image) are undone together. There is
one level: applying another preset replaces the record. It is a file, so
the settings window and the command line share it and it survives closing
the window; it is deleted when used. Records written by Deskence 0.9 and
older (a full snapshot) are still restored as before.

"Restore Default Deskence Settings" on the General page resets Deskence
keys except internal state. It does not touch GNOME settings, pinned
applications, enabled features or presets.

## Removing all data

After uninstalling the package:

    dconf reset -f /io/github/deskence/deskence/
    rm -r ~/.local/state/deskence ~/.local/share/deskence ~/.cache/deskence

Leftover UUIDs in `org.gnome.shell enabled-extensions` are harmless; GNOME
ignores extensions that are not installed. After an update from Better GNOME
Desktop the old data is still there as well (see
[migration.md](migration.md)):

    dconf reset -f /io/github/bettergnome/desktop/
    rm -r ~/.local/state/better-gnome-desktop ~/.local/share/better-gnome-desktop ~/.cache/better-gnome-desktop

The paths assume the default XDG directories.
