# Architecture

## Components

```
data/                 GSettings schema, desktop file, AppStream, D-Bus services,
                      migration autostart entry, application icons
src/deskence/         settings application (Python, GTK 4, libadwaita, .ui files)
desktop-icons/        deskence-desktop-icons: GTK 4 process that draws the desktop
extensions/dock       GNOME Shell extension: dock, window previews, folder stacks
extensions/desktop    GNOME Shell extension: starts the desktop process, marks its
                      windows as desktop, draws the desktop context menu
extensions/tray       GNOME Shell extension: StatusNotifierWatcher/host and DBusMenu
extensions/app-grid   GNOME Shell extension: alphabetical applications view
extensions/clipboard  GNOME Shell extension: clipboard history
extensions/keep-awake GNOME Shell extension: Keep Awake quick setting
po/                   translations
packaging/            RPM spec, Debian packaging, build containers
tests/unit            pytest and gjs unit tests
tests/integration     isolated GNOME Shell session harness
```

The settings application (`deskence`) writes GSettings keys and enables or
disables the extensions through GNOME Shell. Each extension reads its keys
and reacts to changes live. The application does not run in the
background.

| Module | Responsibility |
|---|---|
| `deskence.in` | The `deskence` command: command line or settings window, refusal to run as root |
| `cli.py` | Command line (`status`, `enable`, `disable`, `preset`, `reset`, `diagnostics`), without GTK |
| `features.py` | The feature identifiers and extension UUIDs, the one list all other modules use |
| `control.py` | Operations shared by the window and the command line: reset scopes, preset setters, import context, whether settings are stored |
| `diagnostics.py` | The report for bug reports, the one list of what is collected (GUI and command line) |
| `search.py` | Searching the settings: matching and translatable keywords; the entries come from the window's rows |
| `keybindings.py`, `shortcuts.py` | The shortcuts of Deskence, their rules and clashes (without GTK); their rows, recording dialog and panel |
| `application.py`, `window.py` | Single-instance `Adw.Application`, D-Bus activation, `show-page` action, main window |
| `pages.py`, `general.py` | Settings pages; General page with presets |
| `shell.py`, `conflicts.py` | State of our extensions in GNOME Shell; detection of conflicting extensions |
| `presets.py` | Preset export, validation and import ([data.md](data.md)) |
| `migrations.py`, `rename.py` | Settings migrations and takeover of Better GNOME Desktop ([migration.md](migration.md)) |
| `appgrid.py` | Saving and restoring the manual applications view layout |
| `previews.py`, `preview_geometry.py` | Dock and desktop previews in the settings (geometry without GTK, tested) |
| `button_layout.py`, `appsicon.py` | Title bar buttons, applications button image |
| `deskence_desktop/` | Desktop process: icon model, positions, file operations, shell geometry protocol, menus |

## Decisions

1. **Own extensions, enabled independently.** Six extensions with UUIDs
   `<feature>@deskence.github.io`. None has `prefs.js`: GNOME does not need
   it, so there is no second preferences window and no Settings button in
   the Extensions app.

2. **The package owns the files.** Extensions are installed only in
   `/usr/share/gnome-shell/extensions/<uuid>` and updated by the package
   manager. The application never copies anything to the home directory. A
   copy in `~/.local/share/gnome-shell/extensions/<uuid>`, which would hide
   the packaged one, is detected and reported, not deleted.

3. **Enabling through the GNOME Shell API.** D-Bus `org.gnome.Shell.Extensions`
   (`EnableExtension`, `DisableExtension`, `ListExtensions`,
   `ExtensionStateChanged`). When the Shell does not know an extension yet
   (installed during the session), the UUID is appended to
   `enabled-extensions` the same way the Shell does it; the list is never
   replaced. "Log out required" and "update installed" (different
   `version-name` on disk and in the Shell) are shown to the user.

4. **Module-level extension state**, as a defense against the GNOME 48
   enabling race ([compatibility.md](compatibility.md)).

5. **The desktop is a separate GTK 4 process**
   (`/usr/libexec/deskence-desktop-icons`), started through
   `Meta.WaylandClient`, because a normal Wayland window cannot be placed
   below other windows. The extension marks as desktop only windows whose
   title contains `@deskence-desktop:<connector>` (dialogs stay normal
   windows) and stretches them over the whole monitor, so every click on the
   empty desktop, also beside a short dock, reaches the process; the top bar
   and dock are Shell actors above the windows. The extension sends the
   geometry (icon area without panels, docks as exclusions, work area for
   menus) to the process as JSON on stdin (`extensions/desktop/areas.js` →
   `shellareas.py`); our dock is recognized by the `deskence-dock-holder`
   class. A crashing process is restarted at most 5 times a minute. No file
   operation runs inside the Shell process.

   **The desktop context menu is drawn by the Shell**
   (`extensions/desktop/menu.js`). A GTK menu is a Wayland popup that mutter
   (`constrain_custom_rule`) keeps inside the work area, so beside a dock
   that reserves space it ended up over the dock or squeezed. The process
   prints a menu description (JSON) on stdout, the Shell opens it at the
   clicked point and sends the chosen action back on stdin. Popovers with a
   text field (rename, new folder) stay GTK popovers.

6. **File operations are delegated to Nautilus**
   (`org.gnome.Nautilus.FileOperations2`: progress, name conflicts, undo,
   errors; properties through `org.freedesktop.FileManager1`). Without
   Nautilus, asynchronous GIO fallbacks never overwrite (they use "name (2)")
   and never delete permanently. The GNOME file clipboard format is
   `x-special/gnome-copied-files`.

7. **Icon positions** – see [data.md](data.md).

8. **The dock builds on Shell classes** (`AppDisplay.AppIcon`, `AppMenu`,
   `IconGrid.BaseIcon`) and the `#dash` style name, so colors, states and the
   light, dark and high-contrast styles come from the Shell theme. The own
   stylesheet only changes geometry and is scoped to `.deskence-dock`.
   Pinned applications are the GNOME favorites (`favorite-apps`); there is no
   second list. The overview dash is hidden and its space reserved for the
   dock; disabling restores everything.

   - The applications button is outside the scrolling list
     (`ViewportLayout`); the list starts at the beginning and scrolls when it
     does not fit.
   - Magnification uses transforms without relayout, in two independent
     zones: the list and, in a full or scrolling dock, the button, which only
     grows up to the first list icon (`logic.js appsButtonMaxScale`) so no
     space has to be reserved next to it. `fitInView` keeps magnified icons
     that are fully visible at normal size from being clipped;
     `amountForRoom` limits the strength in a full dock without scrolling.
   - Icons are rendered at the largest displayed size (× magnification ×
     monitor scale) and drawn at normal size, so they stay sharp without
     reloading.
   - Highlights, indicators, symbolic icons and the distribution logo use a
     light or dark "ink" chosen from the background color
     (`logic.js inkForBackground`). Without a `-symbolic` logo variant a
     silhouette is computed from the color logo (`logo.js`) when it stays
     readable.
   - In the overview, the workspace preview is extended over the strip the
     dock reserves (`overviewBackdrop.js`), so the strip takes part in the
     same continuous transition.
   - In the overview (window picker and application grid) a dock along
     the whole edge takes the look of the top bar, so both frame the
     overview alike: the bar's background from the current style composed
     over the overview background (`logic.js panelLook`; the bar is
     transparent there in the GNOME styles, and a custom application grid
     wallpaper or color stops below it). The background color moves there
     with the overview state and stays in the grid
     (`overviewProgress(length, value)`, `mixBackground`), so moving between
     the two views never shows the desktop look. A short dock keeps its own
     background, shape and the user's color and transparency in every
     state. Only the inline color of the background layer changes; the
     settings, the geometry and the items do not, and the ink follows the
     color actually drawn.

9. **Tray.** Our own `org.kde.StatusNotifierWatcher` when the name is free;
   when another program owns it, Deskence registers as a host there, does not
   take the name over, and queues for it. Items may register a bus name or
   only an object path (libappindicator). "Passive" items are hidden by
   default. XEmbed is out of scope.

10. **Window buttons** change `org.gnome.desktop.wm.preferences button-layout`,
    touching only the minimize and maximize buttons. The value before the
    first change is remembered and can be restored only while the current
    value is still the one Deskence wrote; later changes by the user win.

11. **Settings application.** Python, GTK 4 and libadwaita, layout in `.ui`
    files in a GResource, single instance with D-Bus activation
    (`DBusActivatable`) and a `show-page` action used by the "Dock Settings"
    and "Desktop Settings" menu items. Pages: General, Dock, Desktop Icons,
    Applications View, Top Bar, Windows, Clipboard. There is no settings
    search.

12. **Migrations** – see [migration.md](migration.md).

13. **Rename to Deskence** – see [migration.md](migration.md).

14. **Previews in the settings** (`previews.py`, `preview_geometry.py`). One
    `ScreenPreview` draws the screen (frame, top bar, dock); pages add their
    own elements. It is an illustration, not a thumbnail: the screen has the
    aspect ratio of the current monitor but is treated as 440 logical pixels
    tall, so the dock and icons are about twice the size of a faithful
    thumbnail while their proportions stay true. When elements do not fit,
    fewer are shown first (at most 3 applications or 3 desktop icons) and
    only then are they scaled down.

15. **Page icons.** Adwaita has no symbolic icons for a dock, a desktop with
    icons or a top bar (`user-desktop-symbolic` is a folder in Adwaita 48 and
    51), so the application has four own 16×16 icons in the Adwaita style
    (`src/deskence/ui/icons/`), filled paths recolored by GTK.

16. **Window previews in the dock** (`windowPreviews.js`). One panel per
    dock. It opens after the pointer rests 450 ms on a running application
    (120 ms when moving between icons with the panel open), on the inner
    side of the screen beyond the reach of magnified icons, and closes
    350 ms after the pointer leaves both. Padding on the dock side is
    reactive, so crossing the gap does not close it. The panel is top chrome
    without reserved space and uses the Shell menu style classes. Thumbnails
    are `Clutter.Clone`s of the window actors clipped to the window frame,
    never written to disk; minimized windows show the application icon.
    Clicking calls `Main.activateWindow`; hovering never activates anything.
    The panel is keyboard accessible and closes on a context menu, drag,
    icon click, overview, scrolling, rebuild or disabling.

17. **Presets** – see [data.md](data.md).

18. **Applications view sorting.** The background keys stay in the dock
    schema (`app-grid-*`) and work together with the dock. Before switching
    to alphabetical order the application saves `app-picker-layout` and the
    folder `apps` lists in `manual-layout` (`appgrid.py`); switching back
    restores them – pages first, because GNOME saves the positions it shows
    when a folder list changes, then folders. Removed applications are
    skipped, new ones go after the others.

    The `app-grid@` extension keeps the order. GNOME 51 does not move icons
    without a saved position (new ones go to the end of the second page), so
    the full layout is written, sorted with `Intl.Collator` (user's language,
    case-insensitive, numeric) and split into pages of the grid size, but
    only when it differs from the current one. Renamed applications get new
    icons, since GNOME only compares IDs. Reordering by dragging in the main
    view is disabled on the view instance (`_maybeMoveItem`, `acceptDrop`)
    with a one-time notification; moving into and out of folders and to the
    dock still works. Disabling the extension changes nothing in the GNOME
    settings.

    **Folder tiles and hover highlight** (`extensions/dock/appFolders.js`,
    keys `app-grid-folder-*` and `app-grid-hover-*` in the dock schema,
    drawn by the dock extension like the background). The theme gives
    `.app-folder` an opaque background for every state, so an inline style
    would hide hover, focus and drop. Instead `logic.js appGridStylesheet()`,
    the one place these colors are worked out, builds rules for all states
    and the stylesheet is loaded into the theme and replaced on every change,
    so the tiles update at once. Folder rules are limited to
    `#overviewGroup .apps-scroll-view .overview-tile.app-folder` (folder
    icons only exist in the grid; naming both classes makes them win over
    the rules of application tiles); the highlight also covers application
    tiles in the grid and in an open folder (`.app-folder-dialog`), never
    the dock, the desktop or folder stacks. The tile background, the hover
    highlight, keyboard focus, press and drop are separate: the highlight is
    a layer composited over the tile background (`composite()`), so at 100 %
    transparency a folder looks under the pointer as at rest; press and
    selection are a step further from it; the theme's focus ring and drop
    outline stay. Without a hover override, a folder's hover is a lighter
    (on a light, nearly opaque tile darker) step of its color with more
    alpha, a highlight of the surface like other tiles, never an outline; a
    mostly see-through tile is outlined only when pressed or selected.
    Names get a text color only on a background opaque enough to decide it,
    chosen for the color seen (the highlight over the tile, or over the dark
    grid or a light custom grid). The alpha never drops below 1/255,
    invisible but enough for St to paint the inset box shadows drawn with
    the background: the theme's focus ring and the high contrast outline.
    With only one of color and transparency overridden, the rest comes from
    invisible probes (a folder at rest, an application under the pointer)
    outside the scroll view, read again after every theme change. Disabling
    the dock unloads the stylesheet.

19. **Closing and peeking at windows** (`windowPreviews.js`, `peek.js`). The
    close button calls `Meta.Window.delete()`, a normal close request, so the
    application can ask about unsaved changes; the thumbnail goes away only
    with the window. Peeking (after 600 ms over a thumbnail) puts a
    translucent veil above `window_group` (below the top bar, dock and panel)
    and a clone of the window above it. Windows are not changed in any way,
    so ending the peek only removes two actors. Minimized windows and
    windows on other workspaces are shown enlarged beside the panel. The
    thumbnail menu offers Always on Top (`make_above`/`unmake_above`) and
    Close; a pin marks windows that are above.

20. **Folder stacks** (`stacks.js`, `stackLogic.js`). Entries use the same
    identities as presets (`folder-stacks`) and come after the applications,
    before drives and the trash. The panel uses a `GrabHelper` like a menu.
    Folders are read with `enumerate_children_async` in batches of 100, up to
    5000 entries; the panel builds 120 items and adds the next 120 while it
    is scrolled within two pages of the end, so a large folder opens quickly
    and keeps few actors. Thumbnails come from the thumbnail cache or are
    images up to 8 MB loaded by St in threads. A file monitor refreshes the
    panel, keeping the scroll position and focus, as does stepping back out
    of a subfolder. The whole panel is at most half as tall as the work
    area of its monitor and never leaves the free area beside the dock
    (`panelHeights()`); only the contents scroll. The grid is a
    `Clutter.GridLayout` with 3–6 columns, more for larger folders and
    fewer when the panel would be wider than 1.6 times its height limit
    (`gridColumns()`, `gridFit()`): `St.Viewport` takes its scroll range
    from the minimum height of its layout, and a `FlowLayout` reports one
    row there, which made a grid impossible to scroll. Long names are
    shortened and shown in full in a tooltip. Focus follows pointer motion
    (not scrolling under a resting pointer) and a focused item scrolls into
    view. `.desktop` files are shown in the file manager, never launched.
    Removing a folder from the dock only changes the setting.

21. **Clipboard history** (`extensions/clipboard`). `Meta.Selection`
    `owner-changed` triggers a read through `St.Clipboard` (text or
    PNG/JPEG/WebP/GIF/BMP). The image buffer is copied: the buffer passed to
    the St callback is not owned by JS, and using it later crashed the Shell.
    **Pasting:** 120 ms after the panel closes, Ctrl+V is sent through the
    Shell's virtual keyboard (`Clutter.Seat.create_virtual_device`, the same
    mechanism as the GNOME on-screen keyboard; no X11 or extra processes),
    only when the window the panel was opened from is still active;
    Ctrl+Shift+V for applications in the `TerminalEmulator` category.
    Otherwise the item is only put on the clipboard with a "Ready to Paste"
    message. What is recorded and stored: [data.md](data.md).

22. **Keep Awake** (`extensions/keep-awake`).
    `org.gnome.SessionManager.Inhibit` with flag 4 (suspend); gnome-session
    passes it to logind in `block-weak` mode, which a manual suspend does not
    respect. Flag 8 (idle) only with "Also Keep the Screen On", in which
    case the screen neither blanks nor locks by itself. Changing it takes a
    new inhibitor before releasing the old one. Durations use the monotonic
    clock, "until a time" the wall clock (checked every 20 s and exactly at
    the end). The session is not saved; disabling releases the inhibitor.

23. **Always on Top.** The GNOME window menu already has the item. Deskence
    adds it to the dock preview menu and sets GNOME's `toggle-above` shortcut
    on the Windows page. Why there is no title bar pin:
    [compatibility.md](compatibility.md).

24. **Start on the desktop** (`extensions/dock/startup.js`, key
    `show-desktop-at-login`, off by default so updates keep GNOME's
    behavior). GNOME Shell enables extensions while its startup animation
    runs; both are asynchronous, so either may get further first. If the
    animation has not chosen yet, `Main.sessionMode.hasOverview` is false
    until `startup-complete` and the animation brings up the desktop
    instead of the overview. If it is already opening the overview (the
    usual case in testing), the overview is hidden at once through the path
    GNOME has for that (`Overview.runStartupAnimation`): the animation starts
    from the full-size workspace with transparent controls, and the search
    entry, the only control laid out in that state, is kept transparent
    until the overview is hidden. Nothing is simulated and there is no
    timeout. Outside the startup the module does nothing, so enabling or
    reloading the dock, or unlocking the screen, never closes an overview.
    It lives in the dock extension because there is no always-running
    component; the General page says so while the dock is off.

25. **Command line** (`cli.py`, `man deskence`). `deskence` with a
    command (or `--help`, `--version`) runs the command line before GTK
    is loaded; anything else (`--page`, `--gapplication-service`, no
    arguments) opens the window as before. The command line uses the same
    code as the window: `shell.ShellExtensions(blocking=True)` for the
    state and for enabling (GNOME Shell's D-Bus API, or
    `enabled-extensions` for the next session, never replacing the list),
    `presets` for validation, plans and applying with a backup, `control`
    for what a reset restores, `diagnostics` for the report. Saving and
    applying are told apart: a change GNOME Shell did not confirm is
    reported as saved for the next login (exit status 4). Before writing,
    `control.storage()` checks that the settings are kept: dconf needs the
    session bus (writes go through its service), and the in-memory backend
    keeps nothing; otherwise nothing is written. On a text console of the
    same user, GDBus finds the systemd user bus at `$XDG_RUNTIME_DIR/bus`
    without `DBUS_SESSION_BUS_ADDRESS`, so the commands reach a running
    GNOME Shell; nothing guesses a bus address or a display. Resets never
    change how the clipboard history is kept (`remember`, `max-entries`):
    at their defaults the clipboard feature would delete the saved history
    or drop items; this applies to the window as well. The window follows
    changes made on the command line: settings through GSettings, features
    through GNOME Shell's signals, presets and the import backup through
    file monitors.

26. **Searching the settings** (`search.py`, `window.py`). The entries are
    read from the rows of the pages when the search opens (title, subtitle,
    group, page), so they always match what the window shows, in its
    language; only rows of the page templates and rows that ask for it are
    entries, so preset names, folders in the dock and other user data are
    never searched. `search.keywords()` adds translatable words by row id
    (a test checks the ids exist). Matching folds case and diacritics and
    also matches the beginning of longer words. Opening a result scrolls the
    row a third from the top, highlights it and focuses it; a hidden or
    dimmed row points at the switch that makes it available (an option
    above it, or its feature) with a toast, and nothing is turned on.

27. **Undoing a preset** (`presets.apply_plan`, `plan_undo`, `undo`, see
    [data.md](data.md)). The record holds only what the preset changes,
    with "set or default" for each value, and undo compares each value with
    what the preset set, so later changes are never overwritten silently;
    keys of one option (`option_group()`) go together. The record is a file
    shared by the window and the command line rather than kept in the
    window's memory, because `deskence preset undo` needs it too.

28. **Keyboard shortcuts** (`keybindings.py`). One list of actions with
    their storage and scope (global, or the settings window). A recorded
    shortcut is normalized and checked against GNOME's rules (a modifier
    besides Shift unless it is a function key; no Ctrl/Alt + character for
    global shortcuts) and for clashes with other Deskence shortcuts and with
    GNOME's keybinding schemas (window manager, GNOME Shell, mutter,
    settings daemon media keys and custom shortcuts); local and global
    shortcuts never clash. While recording, the window asks the compositor
    to inhibit system shortcuts (GNOME Shell asks the user once), as GNOME
    Settings does, so GNOME's own combinations reach the dialog. Global
    shortcuts are registered by mutter from the keys: the clipboard
    extension's `Main.wm.addKeybinding` follows changes and is removed on
    disable; a failed registration is logged. Imported shortcuts are
    checked the same way.

29. **Counters and progress on dock icons** (`launcherLogic.js`,
    `launcherEntry.js`). The LauncherEntry API: `Update(app_uri, a{sv})`
    signals on the session bus from any object path; the dock only
    subscribes to the signal (no bus name is owned) while one of
    `show-app-counts` and `show-app-progress` is on. Values are validated,
    kept per sender and application, and dropped when the sender's
    connection closes (`bus_watch_name`), not when windows close. Senders
    are never added up: the counter shown is the one of the sender that
    updated it last while showing it, the same for progress. The badge and
    bar lie over the icon (no change to the tile size, scaled with
    magnification). Applications do not repeat their state, so values sent
    before the dock started listening appear with the next update.

30. **Files dropped on the dock** (`fileDrop.js`, `dropLogic.js`). Files
    dragged from Files, the desktop or other applications open in an
    application dropped on, or are copied or moved into a folder (stack).
    They come from Wayland clients, which GNOME Shell only sees through
    mutter (`Main.xdndHandler`): positions and the end of the drag. Over a
    Shell actor there is no Wayland surface to drop on, so mutter cancels the
    drag at its source and the application never moves or deletes anything
    because of it. What is dragged is read during the drag from the DND
    selection (`Meta.Selection`, `SELECTION_DND`, `text/uri-list`); mutter
    clears it before the drag ends. A drop is the drag ending with a button
    release (`Clutter.get_current_event()`); Escape or a vanished source end
    it otherwise and nothing happens. The drag holds an input-only grab, so
    the dock's actors get no pointer events while it lasts: hover, revealing
    at the screen edge, scrolling and the highlight follow the reported
    positions, and the wheel cannot scroll. Pinning and reordering use GNOME
    Shell's own DND and never pass here.

    - Applications: `Gio.DesktopAppInfo.launch_uris_async()` with the
      Shell's launch context, the same for running and stopped
      applications. The desktop entry decides: `%u`/`%U` take any URI,
      `%f`/`%F` local files, anything else is refused while hovering (the
      icon dims and the label says so). Declared MIME types are not checked;
      the application decides what it can read.
    - Folders: Files' `FileOperations2` `CopyURIs`/`MoveURIs`, like the
      desktop (decision 6), so progress, name conflicts, permissions, errors
      and undo are those of Files. There is no fallback in the Shell: without
      Files a message says so. Shift moves, Ctrl copies (mutter's order);
      otherwise files move within a file system and are copied across file
      systems (`id::filesystem` of the folders, read asynchronously). Refused
      while hovering: a missing or unmounted folder, a read-only one, a
      folder into itself or its subfolder, files already in the folder
      (moving), web links. The label tells what a drop does.
    - Hovering a folder for 600 ms opens its panel without a grab: a Shell
      grab would take the pointer from the drag (mutter passes events to the
      Wayland drag only while the Shell holds none). The panel shows what a
      drop does instead of the sorting buttons, its subfolders are targets,
      its files are not (dropping there means the folder itself), and it
      scrolls while the pointer rests near an end of the contents. It closes
      700 ms after the pointer left the icon and the panel, and when the
      drag ends.
    - The icons keep their normal size during the drag, as during GNOME
      Shell drags, so targets do not move under the pointer. A refused drop
      lets the drag image slide back; an accepted one hides it.
    - Disabling the dock removes the drag monitor, timers, highlights and a
      panel opened for the drag, and cancels pending reads and drops.

## Other facts used by the design

- GNOME Shell scans extension directories only in `_loadExtensions()` at
  session start; reloading ES modules in a running Shell is not supported.
- The overview (`ControlsManagerLayout`) only takes the top offset from the
  work area; the overview dash occupies the bottom.
- Monitors: `Main.layoutManager.monitors`, `getWorkAreaForMonitor()` and
  `get_monitor_for_connector()` in the Shell, `Gdk.Monitor.get_connector()`
  in GTK; the primary monitor for the GTK process comes from
  `org.gnome.Mutter.DisplayConfig.GetCurrentState`.
- SNI: watcher `org.kde.StatusNotifierWatcher` at `/StatusNotifierWatcher`,
  items `org.kde.StatusNotifierItem`, menus `com.canonical.dbusmenu`
  (`GetLayout`, `Event`, `AboutToShow`, `LayoutUpdated`,
  `ItemsPropertiesUpdated`).
