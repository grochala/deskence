# Releasing

Releases are published on
[GitHub Releases](https://github.com/grochala/deskence/releases) with the
packages attached as assets. Packages are never committed to the
repository; `dist/` is ignored by Git.

## Test releases and stable releases

Deskence is in the 0.x series. Releases are tested in a real login session
on Fedora 45 only; Debian 13 has not been run in a real session
([testing.md](testing.md)). Until every declared system is covered, publish
releases as **test releases**: mark them as *pre-release* on GitHub and say in the
notes what was and was not verified. Do not call a release stable.

A release can be called stable only after the virtual machine checklist in
[testing.md](testing.md) has been done on every declared system for that
version: installation, update from the previous release, logging in,
uninstalling, and the features changed since the last release.

## 1. Set the version

Raise the version before building packages whenever something changed
since the last one, also for test builds, so packages with different
contents never share a version:

- new features, one or several: the middle number (0.6.1 → 0.7.0);
- fixes and small corrections: the last number (0.7.0 → 0.7.1);
- the first number only by decision of the project owner.

The version must be the same in four places; `build-packages.sh` refuses to
build when they differ:

- `meson.build` – `version`;
- `packaging/rpm/deskence.spec` – `Version`, reset `Release` to 1, and a new
  `%changelog` entry;
- `packaging/debian/changelog` – a new entry at the top (`dch -v <version>`
  or by hand);
- `data/io.github.deskence.Deskence.metainfo.xml.in` – a new `<release>`
  at the top of `<releases>`.

If user-visible strings changed, update the translation template and the
translations:

    meson compile -C _build deskence-pot deskence-update-po

## 2. Run the checks

    meson setup _build      # once
    meson test -C _build --print-errorlogs

The same checks run in CI. For changes to the extensions, also check them in
the isolated GNOME Shell session on each declared GNOME version
([testing.md](testing.md)).

## 3. Build the packages

Commit the version change first, so that the source tarball matches the
tagged commit; the tarball is made from the working tree, including
uncommitted changes.

    packaging/build-packages.sh

This writes to `dist/` in the repository:

    dist/
      deskence-<version>.tar.xz
      fedora-45/deskence-<version>-1.fc45.noarch.rpm
      fedora-45/deskence-<version>-1.fc45.src.rpm
      debian-13/deskence_<version>_all.deb
      debian-13/better-gnome-desktop_<version>_all.deb
      SHA256SUMS
      release/deskence-<version>.rpm
      release/deskence-<version>.deb
      release/SHA256SUMS

`SHA256SUMS` lists only the files of this run, by file name without the
folder; older files left in `dist/` are not included. `release/` holds the
files to attach to the GitHub release (see [Publish](#6-publish)) with their
own `SHA256SUMS`, and is made anew on every run. If either build fails,
nothing in `dist/` is changed.

## 4. Check the packages

Read the rpmlint and lintian output printed by the build. Then check the
contents and dependencies:

    rpm -qpl dist/fedora-45/deskence-<version>-1.fc45.noarch.rpm
    rpm -qpR dist/fedora-45/deskence-<version>-1.fc45.noarch.rpm
    dpkg-deb -c dist/debian-13/deskence_<version>_all.deb
    dpkg-deb -f dist/debian-13/deskence_<version>_all.deb Depends

and the checksums, folder by folder:

    cd dist
    grep ' deskence-<version>.tar.xz$' SHA256SUMS | sha256sum -c
    (cd fedora-45 && sha256sum -c --ignore-missing ../SHA256SUMS)
    (cd debian-13 && sha256sum -c --ignore-missing ../SHA256SUMS)
    (cd release && sha256sum -c SHA256SUMS)

`rpm` and `dpkg-deb` are available in the build containers if the host lacks
one of them. Install each package with the package manager on a clean
system of the target release, so that the dependencies are resolved from the
distribution, for example in a fresh container (this checks dependencies and
file conflicts, not the desktop) and then in a virtual machine:

    sudo dnf install --nogpgcheck ./deskence-<version>-1.fc45.noarch.rpm   # until the RPMs are signed
    sudo apt install ./deskence_<version>_all.deb

### Signing

The packages are not signed. RPM 6 in Fedora 45 refuses to install unsigned
packages unless `dnf install --nogpgcheck` is used, which the README
currently tells users to do. Once a signing key exists, sign the RPMs
(`rpmsign --addsign`) and publish the public key; signing changes the files,
so regenerate `SHA256SUMS` afterwards, keeping the names without folders:

    cd dist
    sha256sum deskence-<version>.tar.xz fedora-45/*-<version>-* debian-13/*_<version>_* |
        sed -E 's#^([0-9a-f]+)  (.*/)?#\1  #' > SHA256SUMS

and copy the signed RPM to `release/deskence-<version>.rpm` again before
regenerating `release/SHA256SUMS` the same way.

## 5. Write the release notes

Start from the `<release>` text in the metainfo file and add:

- the GNOME versions and systems the packages were built for;
- what was tested, where (isolated session, virtual machine, hardware), and
  what was not;
- known issues and anything users must do, such as logging in again after
  updating.

## 6. Publish

1. Tag the release commit: `git tag -a v<version> -m "Deskence <version>"`
   and push the commit and the tag.
2. Create a GitHub release from the tag, titled `Deskence <version>`, with
   the notes, marked as pre-release for test releases.
3. Attach the three files from `dist/release/`:
   - `deskence-<version>.rpm` – the Fedora 45 package
   - `deskence-<version>.deb` – the Debian 13 package
   - `SHA256SUMS`

   They are copies of `fedora-45/deskence-<version>-1.fc45.noarch.rpm` and
   `debian-13/deskence_<version>_all.deb` with names that carry only the
   program and the version; the notes say which system each one is for.
   GitHub adds the source archives of the tag by itself.
4. Download all assets of the published release into an empty folder and
   run `sha256sum -c SHA256SUMS` there; every file must be reported as OK.
