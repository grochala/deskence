# Building and packaging

Deskence is shipped as native RPM and DEB packages and as Meson source. At
run time everything comes from the host distribution's packages, installed
with DNF or APT. Containers are used only to build the packages and run the
checks; they play no part in running Deskence.

## Dependencies

### Build

| Tool | Fedora 45 | Debian 13 |
|---|---|---|
| Meson ≥ 1.0, Ninja | `meson`, `ninja-build` | `meson`, `ninja-build` |
| gettext | `gettext` | `gettext` |
| `glib-compile-schemas`, `glib-compile-resources` | `glib2-devel` | `libglib2.0-bin`, `libglib2.0-dev-bin` |
| Python 3 (also generates the legacy schema copy) | `python3` | `python3` |

### Run time

These are the dependencies declared in `packaging/rpm/deskence.spec` and
`packaging/debian/control`:

| Need | Fedora 45 | Debian 13 |
|---|---|---|
| GNOME Shell ≥ 48 | `gnome-shell` | `gnome-shell` |
| Python bindings with cairo | `python3-gobject` | `python3`, `python3-gi`, `python3-gi-cairo`, `gir1.2-glib-2.0` |
| GTK 4, libadwaita ≥ 1.6 | `gtk4`, `libadwaita` | `gir1.2-gtk-4.0`, `gir1.2-adw-1` |
| Trash and drives | `gvfs` | `gvfs` |
| File operations, properties (recommended) | `nautilus` | `nautilus` |
| "Change Background" in the desktop menu (recommended) | `gnome-control-center` | `gnome-control-center` |

### Tests and validation

`meson test` runs whatever of these it finds and skips the rest:

- `pytest`, PyGObject, GTK 4 and libadwaita introspection data (`unit-python`);
- `gjs` (`unit-gjs*`); the sorting test runs with `LANG=pl_PL.UTF-8`;
- `desktop-file-validate` from desktop-file-utils (`validate-desktop`);
- `appstreamcli` from appstream (`validate-metainfo`);
- `glib-compile-schemas` (`validate-schema`).

The integration harness additionally needs GNOME Shell and the `dbus-daemon`,
`gdbus`, `gsettings`, `dconf` and `gnome-extensions` tools; see
[testing.md](testing.md).

## Building from source

    meson setup _build --prefix=/usr
    meson compile -C _build
    meson test -C _build

Meson options (`meson_options.txt`):

- `shell_versions` – GNOME Shell versions written to the extension metadata
  (default `48,51`). Only list versions that were tested.
- `tests` – register the unit tests (default `true`; the packages build with
  `-Dtests=false` and run their own validation).

`meson install` puts the extensions under
`<prefix>/share/gnome-shell/extensions`. GNOME Shell only looks for
system extensions in the directories of `XDG_DATA_DIRS`, so a prefix other
than `/usr` is only useful for the isolated test session. Installing a
development build into `/usr` of your own system bypasses the package
manager; use the packages or a virtual machine instead.

## Packages

    packaging/build-packages.sh [OUTPUT_DIR]

The script needs Podman. It builds two images from
`packaging/containers/` (Fedora 45 and Debian 13) that provide the build
tools, makes a source tarball of the working tree (without `.git`,
`_build*`, `dist/` and the output directory) and builds the packages from
it. The Meson build directory `_build/` is not used.

Without an argument the results go to `dist/` at the top of the repository,
whatever the current directory; a given directory is used instead and
created if needed:

    dist/
      release/
        deskence-<version>.rpm                      for the GitHub release
        deskence-<version>.deb                      for the GitHub release
        SHA256SUMS                                  checksums of these two
      fedora-45/deskence-<version>-1.fc45.noarch.rpm
      fedora-45/deskence-<version>-1.fc45.src.rpm
      debian-13/deskence_<version>_all.deb
      debian-13/better-gnome-desktop_<version>_all.deb  transitional package
      deskence-<version>.tar.xz                     source tarball
      SHA256SUMS

The folder names come from the release of the build container. Results are
collected in a temporary folder and only moved into place when both builds
succeed, so a failed run leaves the output directory as it was; the final
lines list the files of this run. Files of the same name are replaced,
other files in the directory are kept. `SHA256SUMS` covers exactly the
files of this run, by file name without the folder.

`release/` is made anew on every run. It holds copies of the binary RPM
and the `deskence` DEB named only after the program and the version
(`deskence-<version>.rpm`, `deskence-<version>.deb`), with their own
`SHA256SUMS`: these three files are attached to the GitHub release (see
[releasing.md](releasing.md)).

The script stops before building when the version in `meson.build`, the
RPM spec, the Debian changelog and the metainfo file differ. rpmlint and
lintian results are printed but do not stop the build. The RPM `%check`
section validates the desktop files, the AppStream metadata and the schema.
The packages were built for Fedora 45 and Debian 13 only; other releases of
these or related distributions have not been tried.

Preparing and publishing a release is described in
[releasing.md](releasing.md).
