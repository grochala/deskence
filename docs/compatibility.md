# Compatibility

## GNOME versions

The facts below were taken from the installed GNOME Shell and mutter
sources and typelibs of the target systems, not from general documentation.

| | Fedora 45 | Debian 13 "trixie" |
|---|---|---|
| GNOME Shell | 51.1 | 48.7 |
| mutter | 51 | 48 (API 16) |
| GTK | 4.24 | 4.18 |
| libadwaita | 1.10 | 1.7 |

The extensions declare `shell-version: ["48", "51"]`, set by the Meson
option `shell_versions`. GNOME 49 and 50 probably work, because the code
checks which API is available rather than the version number, but they have
not been tested and are therefore not declared.

Differences the code handles:

- **Marking the desktop window.** mutter 49 and newer:
  `Meta.WaylandClient.new_subprocess()`, `Meta.Window.set_type(DESKTOP)` and
  `hide_from_window_list()`. mutter 48: `WaylandClient.new()` with
  `spawnv()`, `client.make_desktop(window)` and
  `client.hide_from_window_list(window)`.
- **Enabling race in GNOME 48.** `_onEnabledExtensionsChanged` is
  asynchronous and has no lock, so enabling several extensions quickly can
  create two instances of the same extension and call `enable()` on both
  (reproduced in testing). GNOME 49 added a mutex. The extensions keep their
  state at module level: a second `enable()` does nothing and one
  `disable()` cleans up everything.
- **Popup menus.** GNOME 48 has no `popupMenuSide` parameter.

## Feature matrix

| Feature | GNOME 51 (Fedora 45) | GNOME 48 (Debian 13) | GNOME 49/50 |
|---|---|---|---|
| Dock | tested | started, basic test | not declared |
| Dock window previews | tested | panel opens, basic test | not declared |
| Desktop icons | tested | started (`make_desktop` path) | not declared |
| Top bar application icons | tested | an item is shown | not declared |
| Applications view, clipboard, Keep Awake, folder stacks (0.6.0) | tested | not tested | not declared |
| Application folder tile background | tested | not tested | not declared |
| Settings application | tested with libadwaita 1.10 | not run directly; to be checked with libadwaita 1.7 | – |
| Command line (`deskence status` ...) | tested | not tested | not declared |
| Settings search, shortcuts panel, preset undo, diagnostics (0.10.0) | tested | not tested | – |
| Dock counters and progress (LauncherEntry) | tested with a synthetic sender | not tested | not declared |
| Files dropped on dock applications and folders (0.11.0) | tested with a GTK 4 test source | tested headless in a container | not declared |

"Tested" means the checks in an isolated headless Wayland session listed
in [testing.md](testing.md). On Fedora 45 every release is also tested by
the project owner in a real login session in a virtual machine and used
daily on hardware; Debian 13 has not been run in a real session.

## Known limitations

- GNOME Shell only scans extension directories at session start. The first
  installation and every update need a new login; reloading extension
  modules in a running Shell is not supported.
- Hidden files are not shown on the desktop. Renaming a file outside the
  desktop keeps its icon position only when the file monitor reports a
  rename.
- Files pasted on the desktop go to the first free cells, not to the
  clicked point.
- No legacy XEmbed tray icons.
- Applications that draw their own title bar may ignore the button settings.
- There is no Always on Top pin in title bars. On Wayland the applications
  draw their own title bars (GTK 4/libadwaita, `gtk-decoration-layout`) and
  X11 windows use `mutter-x11-frames`; all of them only know `icon`, `menu`,
  `minimize`, `maximize` and `close`. A consistent button would need changes
  in the applications or toolkits, so Deskence adds the item to the dock
  preview menu and sets GNOME's `toggle-above` shortcut instead; the window
  menu already has the item.
- Escape closes the window previews only when the panel has the keyboard
  (opened with the keyboard or the pointer is over it); hovering an icon
  does not take the keyboard from the application.
- Automatic pasting sends Ctrl+V (Ctrl+Shift+V in applications in the
  `TerminalEmulator` category). `Meta.SelectionSourceMemory` carries one MIME
  type, so the history stores plain text; formatted text can only be pasted
  for the newest item while its application still offers it.
- Only clipboard content marked as secret by the application
  (`x-kde-passwordManagerHint`) is skipped; not every password can be
  recognized.
- The folder panel shows thumbnails only from the thumbnail cache and small
  images; it does not generate new ones.
- In a full-length or scrolling dock the applications button grows less than
  the icons when magnified (only up to the first icon), because no space is
  reserved for it.
- After an update from Better GNOME Desktop the old extensions keep running
  with the old settings until the next login, and their messages may be in
  English because the translation domain changed.
- Extended window tiling is not implemented.
- Counters and progress on dock icons appear only for applications that
  send LauncherEntry updates, and only from their next update after the
  dock started listening (there is no standard way to ask for the current
  state). Checked with a synthetic sender, not yet with real applications.
- Shortcut clashes are found among Deskence's shortcuts and GNOME's
  keybinding settings only; shortcuts of other applications, extensions or
  keyboard layouts cannot be read.
- Files dropped on the dock: only drags that offer `text/uri-list` are
  recognized (GTK, Qt and the desktop do). Copying and moving into folders
  needs Files (Nautilus); there is no fallback in the Shell. Whether an
  application takes files is read from its desktop entry (`%u`, `%U`, `%f`,
  `%F`), not from the formats it declares, so an application may still
  refuse a file it opened. The wheel does not scroll a folder panel during a
  drag (the drag holds the pointer); resting near an end does. Drags from
  X11 applications and touch drags have not been tested. After a drop the
  source application sees a cancelled drag, since the file went to the
  Shell rather than to a window.
- There is no package repository; updates mean installing a newer package
  file.
