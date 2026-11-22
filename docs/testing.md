# Testing

There are three levels of testing, and they prove different things:

1. **Automated checks** (`meson test`) – data validation and unit tests of
   logic that does not need a running Shell. They do not load the extensions
   into GNOME Shell.
2. **Isolated GNOME Shell session** – a headless Wayland Shell started with
   its own home directory and D-Bus, driven with a virtual pointer and
   keyboard and screenshots. This is where extension behavior was checked.
3. **Virtual machines or hardware** – real login, package installation and
   updates, the lock screen, real input devices and applications. This level
   has not been done yet; see the checklist below.

## Automated checks

    meson setup _build
    meson test -C _build --print-errorlogs

| Test | Contents |
|---|---|
| `validate-desktop`, `validate-metainfo`, `validate-schema`, `validate-man` | `desktop-file-validate`, `appstreamcli validate`, `glib-compile-schemas --strict`, `groff -man -z -ww` without warnings |
| `unit-python` (pytest, `tests/unit/*.py`) | Settings search (case and diacritics, word beginnings, ranking, the Polish catalog: "przezroczystość", "schowek", "ikony", "usypianie", "sortowanie"; keywords point at existing rows), keyboard shortcuts (spelling, GNOME's rules, clashes with stand-in GNOME schemas including custom shortcuts, local and global scopes, presets with a clashing shortcut), preset undo (only changed keys, defaults kept as defaults, later changes left alone or undone by choice, options of several keys undone whole, features, a failure half way, another preset replacing the record, older records), diagnostics (no home, user or host name, no setting values, unavailable values, monitors, os-release fields), every extension file installed, command line (separate processes with an isolated home and the keyfile settings backend: parsing and errors, unknown features, idempotent enabling and disabling, other extensions untouched, reset scopes and confirmation without a terminal, presets valid and damaged, no silent overwriting, `--dry-run` writing nothing, JSON and exit statuses, no GTK loaded, no session bus, an in-memory backend; with `dbus-daemon` installed, a stand-in of GNOME Shell's extensions interface on a private bus), window button layout, conflict detection, settings migrations, Better GNOME Desktop takeover (real GSettings with an in-memory backend), desktop icon model and grid, file name validation, GNOME file clipboard format, icon position storage, settings preview geometry, presets (export list, type and range validation, format versions, folder identities, archives and their limits, apply, undo and rollback), manual applications view layout |
| `unit-gjs` (`test_dbusmenu.js`) | DBusMenu parsing, SNI icon pixel selection and conversion, item registration forms |
| `unit-gjs-geometry` (`test_geometry.js`) | Dock magnification and its limits, window preview thumbnail sizes, desktop and menu geometry, applications view tile styles (folder background, hover highlight compositing, states, text color) |
| `unit-gjs-order` (`test_order.js`, `LANG=pl_PL.UTF-8`) | Name sorting (case, numbers, Polish characters, stability), paging |
| `unit-gjs-launcher` (`test_launcher.js`) | LauncherEntry: desktop ids, invalid values, counter text, merging senders without adding up, vanished senders |
| `unit-gjs-drop` (`test_drop.js`) | Files dropped on the dock: URI lists (CRLF, comments, non-URIs, duplicates), folders within folders and parents (root, remote hosts), copy or move with Shift/Ctrl and file systems, refused drops (nothing, links, missing or read-only folder, a folder into itself or its subfolder, moving to the same folder), how applications take files (`%U`, `%F`, none), scrolling near the ends of a list, drop versus cancel |
| `unit-gjs-stacks` (`test_stacks.js`) | Folder entries (no escaping the home directory), sorting, `.desktop` files, thumbnails, panel height limit, grid columns, loading more items |
| `unit-gjs-clipboard` (`test_clipboard.js`) | Secret markers, format choice, deduplication, count/size/memory limits, pinning, safe file names, search |
| `unit-gjs-keep-awake` (`test_keep_awake.js`) | Durations, "until a time" (today/tomorrow, clock changes, daylight saving time), rounding |

The same checks run in CI (`.github/workflows/ci.yml`) in Fedora 45 and
Debian 13 containers. If `unit-python` image tests fail inside a container
because glycin's `bwrap` sandbox cannot start, run the container with
`--privileged`.

## Isolated GNOME Shell session

`tests/integration/session.sh` starts `gnome-shell --headless --wayland` with
its own `HOME`, D-Bus session bus, dconf database and `XDG_RUNTIME_DIR`
under `$DESKENCE_TEST_DIR`. Your running session is not touched. The desktop
folder is deliberately called `Pulpit` to exercise a localized XDG
directory. Only in this session the test extension
`tests/integration/test-helper` is installed; it enables unsafe mode for
`Eval` and screenshots and is never packaged.

    export DESKENCE_TEST_DIR=/tmp/deskence-test DESKENCE_RUNTIME_DIR=/tmp/deskence-rt-$UID
    meson setup _build-test --prefix=$DESKENCE_TEST_DIR/prefix
    tests/integration/cycle.sh _build-test dock@deskence.github.io desktop-icons@deskence.github.io -- 1280x800 1024x768
    tests/integration/pointer.sh move 10 10          # the first event of a new device is lost
    tests/integration/pointer.sh click 700 400 3     # virtual pointer
    tests/integration/pointer.sh key Delete          # virtual keyboard
    tests/integration/session.sh shot /tmp/shot.png
    tests/integration/session.sh log
    tests/integration/session.sh stop

`cycle.sh` reinstalls into the test prefix and restarts the Shell, because
extension code cannot be reloaded. Helpers: `sni-test-item.py` (an SNI item
with a menu that logs calls) and `foreign-watcher.py` (a watcher owned by
another program). Without Meson on the host, build and install inside the
`deskence-fedora45` container with the same path mounted
(`--security-opt label=disable`) and run the session on the host.

## Verification so far

The project owner tests every release in a real login session in a Fedora 45
virtual machine and uses it daily on hardware. Debian 13 (GNOME 48) has not
been run in a real session. The checks listed below ran in the isolated
headless Wayland session.

**GNOME Shell 51.1 (Fedora 45)**, versions 0.1.0–0.6.0:

- Enabling through `gnome-extensions` and the settings application; the
  `enabled-extensions` list is extended, never replaced.
- Dock: pinned and running applications, indicators, menus, all positions
  and lengths, intelligent hiding and auto-hide, two monitors,
  magnification and overflow scrolling, background color and transparency,
  sharp icons at 100, 166 and 200 % scale.
- Window previews: live thumbnails, many windows, minimized windows and
  other workspaces, keyboard navigation, closing (with an unsaved-changes
  dialog), peeking, Always on Top.
- Desktop icons: localized desktop folder, hidden files and links, menus
  beside the dock and on a second monitor, selection, copy and paste through
  Nautilus, trash, rename, new folder, drag and drop, free placement and the
  grid, position migration.
- Tray: icon names and pixel data, Activate/SecondaryActivate, DBusMenu
  features, NeedsAttention, host mode with a foreign watcher.
- Applications view: alphabetical order live with 136 items, new and renamed
  applications, restoring the manual layout, rejected drops.
- Folder stacks: Downloads, subfolders, 3000 files, missing folders,
  refresh, `.desktop` files not launched, all dock positions.
- Clipboard: text and images, search, pinning, persistence modes and file
  permissions, lock screen, pasting into a GTK 4 application.
- Keep Awake against a mock `org.gnome.SessionManager`: flags, replacing the
  inhibitor, release on disable, "until a time".
- Presets: save, apply, undo, export and import after resetting dconf.
- Dock in the overview: every position, full and fitted, through desktop,
  window picker, application grid and back, with the application grid
  showing the wallpaper: a full dock's background pixels equal those of
  the top bar in the window picker and the grid, a fitted dock keeps the
  user's color, shape and transparency (0, 30 and 100 %, default look);
  switching between full and fitted with the overview and the grid open;
  animations turned off; the dock size never changes; recorded frame by
  frame, the full dock's color moves continuously and stays the bar's
  between window picker and grid; settings untouched.
- Start on the desktop: real GNOME Shell starts (a new shell process with
  the dock in `enabled-extensions`, not an extension reload) with the
  option off (overview, as in GNOME) and on (desktop; a test extension
  recording every frame from startup saw the overview group only at the
  full-size workspace state with the search entry fully transparent),
  opening the overview afterwards, reloading the dock with the overview
  open (stays open), locking and unlocking (same as without the option:
  GNOME closes the overview on lock), export and import.
- Application folder tiles: theme default, custom color only, transparency
  only, both, 0/50/100 %, light and dark shell style (also switching back
  and forth), hover with the pointer, keyboard focus ring at 100 %,
  dragging an application into a folder (drop highlight), opening and
  closing a folder (panel unchanged), live changes with the grid open,
  export and import of a preset in the session, an older preset without
  the keys, disable/enable cycles removing the stylesheet and probe.
- Folder stack panel (0.8.0): folders with 3 and 403 items, the whole panel
  at exactly half the work area (343 of 686 px at 1280×800, 384 of 768 with
  a side dock, 243 of 486 at 1024×600) and fitted to a small folder; grid
  (6, 4 and 3 columns depending on the height limit) and list; wheel and
  touchpad scrolling to the last of 403 items (added in chunks of 120);
  arrow keys revealing the focused item; scrolling over the dock with the
  panel open changes nothing and keeps the panel open; a subfolder starts
  at the top and Backspace returns to the earlier scroll position and
  focus; tooltip with the full name of a shortened one; dock at the
  bottom, left and right.
- Applications view hover highlight (0.8.0): folder hover without an
  outline (custom folder transparency 80 %), comparable to an application's
  hover; custom color with 0, 40, 50 and 100 % transparency over a custom
  folder background (pixel values match the compositing; at 100 % a folder
  looks as at rest); name color readable on the highlight; keyboard focus
  ring on a folder and an application at 100 %; an application inside an
  open folder; dragging an application onto a folder (drop highlight, the
  application lands in the folder); light, dark and high contrast styles;
  live changes and "Restore Default Settings" from the settings window
  (stylesheet removed); preset export and import of the new keys against
  the session's dconf; Polish and English settings, also in a 380 px wide
  window.
- Command line (0.9.0): `status`, `enable`, `disable`, `disable --all`
  against the running GNOME Shell (applied and confirmed; docks gone; the
  test helper extension untouched); the same from an environment like a
  text console login (only `HOME` and `XDG_RUNTIME_DIR` with the session
  bus at `$XDG_RUNTIME_DIR/bus`, no `DBUS_SESSION_BUS_ADDRESS`, no
  `DISPLAY`); with GNOME Shell stopped but the bus running: `disable --all`
  saved with exit status 4, and after starting GNOME Shell again the dock
  did not start; without a bus and with dconf: nothing written, exit
  status 1; presets imported and applied on the command line while the
  settings window was open: its preset list and switches followed. On the
  developer's real session only read-only checks were made: a process
  with only `HOME` and `XDG_RUNTIME_DIR` finds the user bus and GNOME Shell.
- Settings search, shortcuts, preset undo, diagnostics and dock counters
  (0.10.0): Ctrl+F and the search button, queries in Polish (also
  without diacritics), Down/Enter/Escape, results opening the page and
  focusing and highlighting the row in a wide and a 380 px window, a row
  dimmed by an option above it and one dimmed because its feature is off
  (toast pointing at the switch, nothing turned on), "no results"; the
  shortcuts panel opened from the search, recording refused for Super+V
  (GNOME notification list, after GNOME Shell's "allow inhibiting
  shortcuts" prompt), Super+L (lock screen) and a Deskence duplicate,
  accepted for Ctrl+Alt+K, the new combination opening the clipboard at
  once, the old one released, none while the clipboard is off; a preset
  turning on the clipboard and moving the dock applied in the window and
  undone with the toast button, the General page row and the command line
  (feature off and not running again); report preview, copying (read back
  from the clipboard) and saving; counters (7, 250 shown as 99+) and
  progress from the developer tool `tests/integration/launcher-entry.py`
  on a left and a bottom dock, with magnification and overflow scrolling,
  invalid values ignored, counters gone with their sender, a second sender
  not adding up, settings turned off and on, the dock disabled and enabled
  (values dropped, the next update shown), no JavaScript errors. The dock
  install list was missing the new modules; the session found it, and
  `test_install_lists.py` now guards it.
- The update path from real Better GNOME Desktop 0.3.0 extensions, during a
  session and after a simulated re-login.
- Repeated enable/disable cycles return the number of actors, windows and
  processes to the start value with no JavaScript errors in the log.
- Polish and English interface.

**Files dropped on the dock (0.11.0)**, GNOME Shell 51.1 headless with a
small GTK 4 window as the drag source (a `Gdk.FileList`, as Files offers
it), driven with the virtual pointer and keyboard:

- Two files dropped on Text Editor open in it; Settings (no `%U`/`%F`)
  is refused (dimmed, "cannot open files"), nothing starts.
- A file dropped on Downloads moves (same file system) through Files; with
  Ctrl held the label changes to copying while hovering; the drag source
  always ends with a cancel and never deletes.
- Hovering Downloads opens its panel without a grab; the edge scrolled
  through 300 files to a subfolder at the end; a drop on the subfolder and
  on the panel header (the folder itself) went there.
- Refused: a read-only folder, Downloads into itself, a file already in
  Downloads; Escape with the panel open closes it and changes nothing.
- Dock on the left (full length, auto-hide): revealed by resting at the
  screen edge, the panel opened beside it and stayed open while crossing
  the gap, then closed with the dock after the pointer left.
- Two monitors, dock on both, right side: a drop into the panel of the
  second monitor's dock.
- 200 % scale with magnification: icons magnify on hover, keep their size
  during a file drag; a drop into the panel works.
- Undo through Files' `Undo` returned the moved file.
- Pinning from the applications view and reordering in the dock still work.
- Disabling the dock during a drag with the panel open: no errors, no
  actors left.
- GNOME Shell 48.7 headless in a Debian 13 container (the host's system
  bus shared for logind): refused application, opening a file with Files
  (`%U`), the panel during a drag, a move into a subfolder.

0.11.1, the same session with the desktop icons enabled, after real
GNOME Shell starts with both extensions enabled (with and without "Start
on the desktop", four starts): clicking the empty desktop and an icon,
rubber band selection and moving a window by its title bar were checked
after each start and after every drag (drop on an application and a
folder, a refused drop, Escape before and after the panel opened, leaving
the panel and the dock, a desktop icon dragged into a folder, disabling
the dock and the desktop icons during a drag and enabling them again):
GNOME Shell held no modal grab and no grab actor afterwards. An exception
injected into the end of a drag still left no drag state behind. The
blocked input reported once on a test system was not reproduced; its cause
is not known.

Not verified: name conflicts (Nautilus 51.1 crashed in the isolated session
when building its conflict dialog, `nautilus_image_set_fallback`, also when
called directly with `gdbus`, so the dialog was not seen), Files itself as
the drag source, other file managers and applications as sources or
targets, X11 (Xwayland) drag sources, touch drags, a disconnected drive
while hovering, a real login session.

**GNOME Shell 48.7 (Debian 13, container with systemd)**, versions up to
0.5.0: the dock, desktop icons (mutter 48 path) and tray start; the window
preview panel opens; enabling and disabling work without JavaScript errors.
These runs found and fixed the missing `popupMenuSide` parameter, the double
`enable()` race and a missing `python3-gi-cairo` dependency. The 0.6.0
features were not run on GNOME 48.

**Packages:** the 0.6.0 RPM (Fedora 45) and DEB (Debian 13) packages build
with `packaging/build-packages.sh`; rpmlint reports no errors (warnings: no
man pages) and lintian reports nothing. Installing them in clean Fedora 45
and Debian 13 containers (`dnf install --nogpgcheck`, since the RPM is not
signed, and `apt install`) resolves all dependencies; they have not been run
in a real session yet. For 0.4.0 the update from the real 0.3.0 packages
was checked in containers: `apt install` with
Breaks/Replaces and the transitional package, `rpm -U` with Obsoletes,
migration with `deskence --migrate`, data kept after removal.

**Not verified yet:** dock counters and progress with real applications
(Telegram, Thunderbird, Firefox downloads, Nautilus copies), the toast's
Undo with a person clicking within its timeout on hardware (scripted, it
was clicked within 2 s), the command line on a real text console (Ctrl+Alt+F3)
while GNOME is broken or not running, a real logout and login with a display manager
(the migration autostart was run by hand; "Start on the desktop" was only
tested with headless shell starts, where the wallpaper loads at once), `dnf upgrade` from a repository,
GNOME 48 beyond a smoke test, real scaling, screen readers, pasting in
terminals and X11 applications, Keep Awake with real gnome-session and
logind, the desktop helper in legacy mode (`legacy.py`), the settings
application on libadwaita 1.7.

## When the desktop or windows stop taking clicks

To get control back without losing settings, from a text console
(Ctrl+Alt+F3, log in as the same user) or a terminal:

    deskence status                       # what is enabled and running
    deskence diagnostics > ~/deskence-report.txt
    journalctl --user -b -o short-precise | grep -iE 'deskence|JS ERROR' > ~/deskence-log.txt
    deskence disable dock desktop-icons   # or: deskence disable --all

`disable` keeps every setting; if GNOME Shell does not answer, the change is
saved for the next login (exit status 4). Then log in again (or return with
Ctrl+Alt+F2) and enable the features one at a time
(`deskence enable desktop-icons`, then `deskence enable dock`) to find the
one involved. If `deskence` itself cannot run,
`gsettings set org.gnome.shell disable-user-extensions true` turns off every
extension for the next login (`false` restores them). Neither deletes data.

To see what file drags do, put `DESKENCE_DEBUG=dnd` into
`~/.config/environment.d/deskence-debug.conf` and log in again; the dock
logs each drag's state changes (begin, kind of target, the panel, drop or
cancel, reset) with the Shell's modal count and grab, never file names or
pointer motion: `journalctl --user -b | grep 'Deskence dnd'`. A line
`reset: ... grab none` after every drag means Deskence released everything;
`grab ClutterInputOnlyActor` while a drag runs is mutter's own drag.

## Checklist for virtual machines

To be done on Fedora 45 and Debian 13 with a real login session (Fedora 45
is covered by the project owner's own testing, without results recorded
item by item):

- [ ] Install in a running session → "log out" banner → features work after login.
- [ ] Update to a newer package → "update installed" banner → new version after login.
- [ ] Uninstall → desktop files untouched; standard GNOME after login.
- [ ] Lock screen: dock hides and returns; no desktop or tray elements on the lock screen; SNI applications stay registered.
- [ ] Full screen (video, game): dock and top bar hidden.
- [ ] Scaling 100/125/200 % and large text: dock size, icon grid, menus.
- [ ] Monitors stacked vertically and with negative coordinates.
- [ ] Real mouse and touchpad: scrolling the dock, step sensitivity.
- [ ] Light GNOME style: dock background color after switching style.
- [ ] Applications view closing smoothness at 60/120 Hz; Debian logo (`emblem-debian`) as a silhouette.
- [ ] Disconnecting and reconnecting a monitor: icons return to their monitor.
- [ ] Real SNI applications: Telegram, Nextcloud, Dropbox, Element/Electron, KeePassXC.
- [ ] Conflicts: Dash to Dock, DING, AppIndicator installed and active → warnings, disabling on request.
- [ ] Orca: labels of the dock, desktop icons, settings switches, panels.
- [ ] Keyboard: Ctrl+Alt+Tab to the dock, arrows on the desktop, Shift+F10.
- [ ] Dragging files between Nautilus and the desktop and between monitors.
- [ ] Files from Nautilus and the desktop onto dock applications (one and several files) and into folder stacks: copy, move, Ctrl/Shift, a name conflict, a read-only folder, a removed USB stick, Escape; dock bottom, left and right, auto-hide.
- [ ] Without Nautilus: GIO fallback operations.
- [ ] Long session: no growing leaks (`journalctl`, `top`).
- [ ] Settings application on libadwaita 1.7 (Debian 13).
- [ ] 0.6.0 features on GNOME 48: window closing and peeking, folder stacks, clipboard, Keep Awake, applications view sorting, folder tile background.
- [ ] Folder tile background and hover highlight in the high contrast style on real hardware.
- [ ] Folder stack panel with a real touchpad (kinetic scrolling) and at 125/200 % scaling.
- [ ] Keep Awake with gnome-session and logind: manual suspend, closing the lid.
- [ ] Clipboard pasting in terminals (Ptyxis, GNOME Terminal) and X11 applications.
- [ ] Exporting a preset on one computer and importing it on another.
- [ ] Recovery from a text console: `deskence status`, `disable --all` with GNOME running and after it failed, `reset --all --yes`, then logging in again.
