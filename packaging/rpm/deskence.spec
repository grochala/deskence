Name:           deskence
Version:        0.13.0
Release:        1%{?dist}
Summary:        Dock, desktop icons and tray for GNOME

License:        GPL-3.0-or-later
URL:            https://github.com/grochala/deskence
Source0:        %{name}-%{version}.tar.xz

BuildArch:      noarch

BuildRequires:  meson >= 1.0
BuildRequires:  gettext
BuildRequires:  glib2-devel
BuildRequires:  desktop-file-utils
BuildRequires:  libappstream-glib
BuildRequires:  python3

Requires:       gnome-shell >= 48
Requires:       gtk4 >= 4.14
Requires:       libadwaita >= 1.6
Requires:       python3-gobject
Requires:       gvfs
Recommends:     nautilus
Recommends:     gnome-control-center

# Renamed from better-gnome-desktop in 0.4.0. The new package replaces the
# old one on update, so its extensions go and only the new set is
# installed; the user's settings and enabled features are taken over at the
# next login (deskence --migrate, an autostart entry). The old command and
# helper path stay as symlinks, the old D-Bus name as an alias, until the
# old extensions are gone everywhere.
%global legacy_name better-gnome-desktop
%global legacy_id io.github.bettergnome.Desktop
%global app_id io.github.deskence.Deskence
Obsoletes:      %{legacy_name} < 0.4.0
Provides:       %{legacy_name} = %{version}-%{release}

%description
Deskence (formerly Better GNOME Desktop) adds a dock with folders, files and
folders on the desktop, application icons (StatusNotifierItem) in the top
bar, a clipboard history, Keep Awake in the quick settings, an alphabetical
applications view and title bar button settings to the standard GNOME
desktop, configured in one application, with presets to move settings.

It consists of six GNOME Shell extensions owned by this package, a desktop
icons helper and a settings application. It works in the existing GNOME
session; extensions installed or updated by this package start after the
next login.

%prep
%autosetup

%build
%meson -Dtests=false
%meson_build

%install
%meson_install
%find_lang %{name}

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/%{app_id}.desktop
desktop-file-validate %{buildroot}%{_sysconfdir}/xdg/autostart/deskence-migration.desktop
appstream-util validate-relax --nonet %{buildroot}%{_metainfodir}/%{app_id}.metainfo.xml
glib-compile-schemas --strict --dry-run %{buildroot}%{_datadir}/glib-2.0/schemas

%files -f %{name}.lang
%license COPYING
%doc README.md docs/*.md
%{_bindir}/deskence
%{_bindir}/%{legacy_name}
%{_mandir}/man1/deskence.1*
%{_mandir}/man1/%{legacy_name}.1*
%{_libexecdir}/deskence-desktop-icons
%{_libexecdir}/%{legacy_name}-icons
%{_datadir}/deskence/
%{_datadir}/gnome-shell/extensions/dock@deskence.github.io/
%{_datadir}/gnome-shell/extensions/desktop-icons@deskence.github.io/
%{_datadir}/gnome-shell/extensions/tray@deskence.github.io/
%{_datadir}/gnome-shell/extensions/app-grid@deskence.github.io/
%{_datadir}/gnome-shell/extensions/clipboard@deskence.github.io/
%{_datadir}/gnome-shell/extensions/keep-awake@deskence.github.io/
%{_datadir}/glib-2.0/schemas/%{app_id}.gschema.xml
%{_datadir}/applications/%{app_id}.desktop
%{_datadir}/dbus-1/services/%{app_id}.service
%{_datadir}/dbus-1/services/%{legacy_id}.service
%{_metainfodir}/%{app_id}.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/%{app_id}.svg
%{_datadir}/icons/hicolor/symbolic/apps/%{app_id}-symbolic.svg
%config(noreplace) %{_sysconfdir}/xdg/autostart/deskence-migration.desktop

%changelog
* Sun Nov 22 2026 Rafał Grochala <rafal.grochala@pixmedia.pl> - 0.13.0-1
- Dock: items of a folder panel can be copied or cut to the clipboard and
  pasted in Files or on the desktop

* Sun Nov 22 2026 Rafał Grochala <rafal.grochala@pixmedia.pl> - 0.12.0-1
- Dock: files and folders can be dragged from a folder panel onto another
  folder in the dock or onto the desktop
- Dock: applications take dropped files only of types they declare
- Dock: a clearer folder marker, matching the application dots

* Sun Nov 22 2026 Rafał Grochala <rafal.grochala@pixmedia.pl> - 0.11.3-1
- Start on the desktop: the session no longer stays without input, apart
  from the dock, when GNOME's animations are off (for example in virtual
  machines without 3D acceleration)
- Input diagnostics notice clicks over windows reaching the Shell

* Sun Nov 22 2026 Rafał Grochala <rafal.grochala@pixmedia.pl> - 0.11.2-1
- Dock: optional input diagnostics (DESKENCE_DEBUG=input) for a desktop
  and windows that stop taking clicks

* Sun Nov 22 2026 Rafał Grochala <rafal.grochala@pixmedia.pl> - 0.11.1-1
- Dock: the end of a file drag always cleans up, also after an error;
  mutter's drag image is left alone; optional diagnostics (DESKENCE_DEBUG=dnd)

* Sun Nov 22 2026 Rafał Grochala <rafal.grochala@pixmedia.pl> - 0.11.0-1
- Dock: files dropped on an application open in it; files dropped on a
  folder stack, or on a subfolder in its panel, are copied or moved there
  through Files

* Sun Nov 22 2026 Rafał Grochala <rafal.grochala@pixmedia.pl> - 0.10.0-1
- Settings search, a keyboard shortcuts panel with clash checks and a
  report for bug reports in the settings window
- Undoing a preset restores only what it changed, keeping later changes
- Dock: counters and progress reported by applications (LauncherEntry)

* Sun Nov 22 2026 Rafał Grochala <rafal.grochala@pixmedia.pl> - 0.9.0-1
- Command line for status, features, presets, defaults and diagnostics,
  usable from a text console; manual page deskence(1)
- Restoring defaults keeps a clipboard history that is kept after logging out

* Sun Nov 22 2026 Rafał Grochala <rafal.grochala@pixmedia.pl> - 0.8.0-1
- Applications view: custom color and transparency of the hover highlight;
  hovering a folder no longer draws an outline
- Folders in the dock: the panel takes at most half of the screen height
  and scrolls through the whole folder, also with the keyboard
- Settings: clearer descriptions, Polish wording, keyboard mnemonics

* Sun Nov 22 2026 Rafał Grochala <rafal.grochala@pixmedia.pl> - 0.7.1-1
- Dock: a dock along the whole edge matches the top bar in the activities
  overview and the applications view; a short dock keeps its own look
- Applications view: clearly visible hover, press, focus and selection on
  folder tiles with a custom color or transparency

* Sat Nov 21 2026 Rafał Grochala <rafal.grochala@pixmedia.pl> - 0.7.0-1
- Applications view: custom color and transparency of folder tiles
- General: optionally start the session on the desktop instead of the
  activities overview
- Dock: no separate background band in the activities overview

* Sat Nov 21 2026 Rafał Grochala <rafal.grochala@pixmedia.pl> - 0.6.1-1
- Project homepage and bug tracker in the package metadata
- Source tarball no longer includes earlier build output
- Documentation in English; no changes to the application

* Sat Nov 21 2026 Rafał Grochala <rafal.grochala@pixmedia.pl> - 0.6.0-1
- Settings: General page with presets, export and import (JSON or an
  archive with images), restoring defaults; Applications View page with
  alphabetical sorting; neutral previews
- Dock: folders with a contents panel; closing and peeking at windows
  from their previews; Always on Top in the preview menu
- New features: clipboard history, Keep Awake in the quick settings,
  Always on Top shortcut

* Sat Nov 21 2026 Rafał Grochala <rafal.grochala@pixmedia.pl> - 0.5.0-1
- Renamed the remaining identifiers to Deskence: application ID, settings schema,
  extension UUIDs and data folders; replaces better-gnome-desktop and takes
  over its settings, enabled features, favorites and icon positions
- Dock: window previews on hover; no extra space next to the applications
  button with magnification; running indicators under the icons of a
  bottom dock
- Settings: larger, clearer dock and desktop icon previews

* Sat Nov 21 2026 Rafał Grochala <rafal.grochala@pixmedia.pl> - 0.4.0-1
- Renamed to Deskence (package deskence, command deskence); replaces
  better-gnome-desktop
- Settings: page icons, "About" menu item

* Sat Nov 21 2026 Rafał Grochala <rafal.grochala@pixmedia.pl> - 0.3.0-1
- Dock: sharp magnified icons, no tiles under icons with a custom background,
  monochrome distribution logo, list kept at the start of a full-edge dock,
  running indicators on the inner side
- One continuous closing transition of the applications view
- Desktop menus open at the clicked point, also beside the dock
- Desktop grid anchored at the chosen corner with small margins
- Optional custom background color of the applications view

* Sat Nov 21 2026 Rafał Grochala <rafal.grochala@pixmedia.pl> - 0.2.0-1
- Dock: applications button position and icon, magnification, scrolling,
  background color and transparency, "Dock Settings" menu item
- Desktop icons: free placement, Align to Grid, positions relative to the monitor
- Smooth closing of the applications view, optional transparent background
- Immediate dock reordering; no drag frame; one desktop menu beside the dock

* Sat Nov 21 2026 Better GNOME Desktop developers - 0.1.0-1
- First release
