# Contributing

## Reporting bugs

Report bugs on the
[issue tracker](https://github.com/grochala/deskence/issues). The issue template asks for the
diagnostics report (General → Information for Bug Reports, or
`deskence diagnostics`), which covers most of the following. A useful
report contains:

- the distribution and version, the GNOME Shell version
  (`gnome-shell --version`) and the Deskence version (About in the
  application menu);
- Wayland or X11, the number of monitors and the display scaling;
- which Deskence features are enabled and which other extensions are active
  (`gnome-extensions list --enabled`);
- steps to reproduce, what you expected and what happened;
- related messages from the log, for example
  `journalctl --user -b | grep -iE 'deskence|gjs|gnome-shell'`.

Check the log before attaching it: it may contain file names or window
titles. Clipboard contents are never logged by Deskence.

## Development environment

The tools and dependencies are listed in [docs/building.md](docs/building.md).
If they are not installed on your machine, the build containers used for
packaging have everything needed to run the checks:

    podman build -t deskence-fedora45 -f packaging/containers/Containerfile.fedora45 packaging/containers
    podman run --rm -v "$PWD:/src:ro" --security-opt label=disable deskence-fedora45 \
        bash -ec 'meson setup /tmp/build /src && meson test -C /tmp/build --print-errorlogs'

Do not install development builds over your own session. GNOME Shell keeps
the loaded extension code until you log out, and a copy in
`~/.local/share/gnome-shell/extensions` would hide the packaged one. Use the
isolated GNOME Shell session from [docs/testing.md](docs/testing.md) or a
virtual machine.

## Checks

Before sending a change, run:

    meson setup _build
    meson test -C _build --print-errorlogs

This validates the desktop file, AppStream metadata and GSettings schema and
runs the Python and gjs unit tests. Passing unit tests do not show that the
extensions work in GNOME Shell: changes to the extensions need a check in the
isolated session, on every GNOME version listed in `meson_options.txt`
(`shell_versions`), and the description of what you tested.

## Changes

- Keep a change focused on one thing and describe why it is needed.
- Follow the style of the surrounding code. Comments explain reasons, GNOME
  limitations and non-obvious decisions, not the next line.
- A new or changed setting needs a GSettings key with a summary and, when an
  existing value has to be converted, a step in `src/deskence/migrations.py`
  (see [docs/migration.md](docs/migration.md)).
- New user-visible strings go through gettext; add new source files with
  strings to `po/POTFILES.in`.
- Only declare a GNOME Shell version in `shell_versions` after testing on it.
- Update the documentation in `docs/` when behavior or a design decision
  changes.

By contributing you agree that your contribution is licensed under
GPL-3.0-or-later, the license of the project.
