# Settings migration

## Settings versions

The key `settings-version` in `io.github.deskence.Deskence` records which
format the stored settings have (currently 5). `src/deskence/migrations.py`
brings older settings up to date step by step when the application starts:

| Version | Change |
|---|---|
| 2 | Normalizes the custom applications button image. |
| 3 | No conversion: new applications view color keys; existing values are kept. |
| 4 | Copies the custom button image into the `deskence` data folder. |
| 5 | Only new keys; the applications view settings stay in the dock schema. |

A new step is needed only when existing values have to be converted. Keys
that are merely added get their defaults from the schema.

## From Better GNOME Desktop (0.3.0 and older)

Deskence was called Better GNOME Desktop up to 0.3.0. Version 0.4.0
renamed the package and the command; 0.5.0 renamed all remaining
identifiers. The user interface, metadata and messages only use the new
name; the old one is kept only in the migration and compatibility code
listed below, and in changelogs.

| Before (≤ 0.3.0) | Now | Migration or compatibility |
|---|---|---|
| Application ID `io.github.bettergnome.Desktop` (desktop file, D-Bus name, AppStream, icons, GResource) | `io.github.deskence.Deskence` | The new ID replaces the old one in place in favorites, the applications view layout and application folders. AppStream lists the old ID in `<provides>`. The old D-Bus name has its own service file and is an alias in the application (`LegacyName` in `application.py`), so the settings menu items of the old extensions keep working until the next login. |
| Schema and dconf path `io.github.bettergnome.Desktop`, `/io/github/bettergnome/desktop/` | `io.github.deskence.Deskence`, `/io/github/deskence/deskence/` | Values set by the user are copied once (`rename.py`, key `legacy-settings-migrated`), without overwriting values already set in Deskence, and checked after writing; the old values stay. The old schema is read from a copy generated at build time (`data/schemas/make-legacy-schema.py` → `/usr/share/deskence/legacy-schemas/`) that is not installed among the system schemas. |
| Extension UUIDs `dock@`, `desktop-icons@`, `tray@bettergnome.github.io` | `…@deskence.github.io` | The new UUID replaces the old one in `enabled-extensions`. The old one is removed once it is not running in this session or the Shell already knows the new one, so after an update during a session the old extensions run until logout and the new ones start at login – never both. An old UUID running next to a known new one (for example a copy in the home directory) is shown as a conflict. |
| Desktop helper: title tag `@bettergnome-desktop:`, variable `BETTERGNOME_DESKTOP_AREAS`, ID `io.github.bettergnome.DesktopIcons`, drag MIME type | `@deskence-desktop:`, `DESKENCE_DESKTOP_AREAS`, `io.github.deskence.Deskence.DesktopIcons`, `application/x-deskence-desktop-icons` | When started under the old path (a symlink), the helper speaks the old protocol (`deskence_desktop/legacy.py`). |
| Package and command `better-gnome-desktop`, helper `/usr/libexec/better-gnome-desktop-icons`, `/usr/share/better-gnome-desktop` | `deskence`, `deskence-desktop-icons`, `/usr/share/deskence` | RPM: `Obsoletes`/`Provides`. DEB: `Breaks`/`Replaces` and an empty transitional package `better-gnome-desktop`. Symlinks under the old command and helper names. |
| `~/.local/state/`, `~/.local/share/`, `~/.cache/better-gnome-desktop` | `…/deskence` | Icon positions: copied when the desktop helper first starts. Custom button image: copied after comparing contents (settings version 4). Cache: rebuilt. The old files stay, so going back to 0.3.0 loses nothing. |
| Modules `bettergnome`, `bettergnome_desktop`, CSS classes `bettergnome-*`, GTypes `BetterGnome*`/`Bg*` | `deskence`, `deskence_desktop`, `deskence-*`, `Deskence*` | Internal; code only. |

### When it runs

The migration (`rename.run`) runs at every login through
`/etc/xdg/autostart/deskence-migration.desktop` (`deskence --migrate`,
about 0.3 s and a no-op when there is nothing to move) and when the
application starts. Settings go first, then `enabled-extensions`, so the
Shell enables the new extensions – installed before the session started,
so without another login – with the user's settings already in place. Each
step only changes what still has the old form: running it again changes
nothing, and an interrupted run is finished by the next one. Nothing is
deleted.

Updating:

    sudo dnf install --nogpgcheck ./deskence-0.10.0.rpm   # Obsoletes removes better-gnome-desktop
    sudo apt install ./deskence-0.10.0.deb                # Breaks/Replaces removes better-gnome-desktop

The transitional DEB package can be removed after the update.

### Planned removal

The compatibility pieces are meant to be removed once updates from 0.3.0 no
longer need to be supported (tentatively in 0.7): the symlinks
`better-gnome-desktop` and `better-gnome-desktop-icons`, the transitional DEB
package, the D-Bus alias (`LegacyName`, `io.github.bettergnome.Desktop.service`),
`deskence_desktop/legacy.py`, the legacy schema copy and the autostart entry
with `rename.py`.
