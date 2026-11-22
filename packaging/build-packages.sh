#!/bin/bash
# Builds the RPM (Fedora 45) and DEB (Debian 13) packages in containers.
#   packaging/build-packages.sh [OUTPUT_DIR]
# OUTPUT_DIR defaults to dist/ at the top of the repository. Results go to
#   OUTPUT_DIR/deskence-<version>.tar.xz   source tarball the packages are built from
#   OUTPUT_DIR/fedora-<release>/           binary and source RPM
#   OUTPUT_DIR/debian-<release>/           DEB packages
#   OUTPUT_DIR/SHA256SUMS                  checksums of the files of this run only
#   OUTPUT_DIR/release/                    deskence-<version>.rpm, deskence-<version>.deb
#                                          and their SHA256SUMS, to attach to a GitHub release
# Needs podman. The containers only provide build tools; the packages
# depend on the host's own packages at run time.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=$(realpath -m "${1:-$ROOT/dist}")
NAME=deskence
VERSION=$(sed -n "s/^  version: '\(.*\)',/\1/p" "$ROOT/meson.build")

# Every place that names the version has to agree before anything is built.
mismatch=0
check_version() {
    if [ "$2" != "$VERSION" ]; then
        echo "error: $1 says ${2:-nothing}, meson.build says $VERSION" >&2
        mismatch=1
    fi
}
check_version packaging/rpm/deskence.spec "$(sed -n 's/^Version: *//p' "$ROOT/packaging/rpm/deskence.spec")"
check_version packaging/debian/changelog "$(sed -n '1s/^[^ ]* (\([^)]*\)).*/\1/p' "$ROOT/packaging/debian/changelog")"
check_version "the first <release> in the metainfo" \
    "$(grep -m1 -o '<release version="[^"]*"' "$ROOT/data/io.github.deskence.Deskence.metainfo.xml.in" | cut -d'"' -f2)"
[ "$mismatch" = 0 ] || exit 1

mkdir -p "$OUT"
# Results are collected in a fresh directory and only moved into OUT when
# both builds succeeded, so a failed run never mixes with earlier results.
STAGE=$(mktemp -d "$OUT/.build-XXXXXX")
trap 'status=$?; rm -rf "$STAGE"
      [ "$status" = 0 ] || echo "Build failed; nothing in $OUT was changed." >&2' EXIT

podman build -q -t deskence-fedora45 -f "$ROOT/packaging/containers/Containerfile.fedora45" "$ROOT/packaging/containers" >/dev/null
podman build -q -t deskence-debian13 -f "$ROOT/packaging/containers/Containerfile.debian13" "$ROOT/packaging/containers" >/dev/null

# Source tarball of the working tree, without build results: an output
# directory inside the tree would otherwise end up in the tarball, packages
# included.
EXCLUDE_OUT=(--exclude='./dist')
case "$OUT/" in
    "$ROOT"/*) EXCLUDE_OUT+=(--exclude="./${OUT#"$ROOT"/}") ;;
esac
TARBALL=$NAME-$VERSION.tar.xz
tar -C "$ROOT" --exclude-vcs --exclude='__pycache__' --exclude='./_build*' "${EXCLUDE_OUT[@]}" \
    --transform "s,^\.,$NAME-$VERSION," -cJf "$STAGE/$TARBALL" .

podman run --rm -v "$STAGE:/out:Z" deskence-fedora45 bash -ec "
  dir=/out/fedora-\$(rpm -E %fedora)
  mkdir -p ~/rpmbuild/SOURCES ~/rpmbuild/SPECS \$dir
  cp /out/$TARBALL ~/rpmbuild/SOURCES/
  tar -xJf /out/$TARBALL -O $NAME-$VERSION/packaging/rpm/$NAME.spec > ~/rpmbuild/SPECS/$NAME.spec
  rpmbuild -ba ~/rpmbuild/SPECS/$NAME.spec
  cp ~/rpmbuild/RPMS/noarch/*.rpm ~/rpmbuild/SRPMS/*.rpm \$dir/
  rpmlint \$dir/$NAME-$VERSION-*.noarch.rpm || true"

podman run --rm -v "$STAGE:/out:Z" deskence-debian13 bash -ec "
  dir=/out/debian-\$(cut -d. -f1 /etc/debian_version)
  mkdir -p \$dir
  cd /tmp && tar -xJf /out/$TARBALL && cd $NAME-$VERSION
  cp -r packaging/debian debian
  dpkg-buildpackage -us -uc -b
  cp ../*.deb \$dir/
  (lintian ../*.deb 2>/dev/null || true)"

# Move the results into place, replacing files of the same name, and
# checksum exactly these files. SHA256SUMS names the files without their
# folder, so the names must be unique.
mapfile -t RESULTS < <(cd "$STAGE" && find . -type f -printf '%P\n' | sort)
duplicates=$(printf '%s\n' "${RESULTS[@]##*/}" | sort | uniq -d)
if [ -n "$duplicates" ]; then
    echo "error: file names occur more than once: $duplicates" >&2
    exit 1
fi
for file in "${RESULTS[@]}"; do
    mkdir -p "$OUT/$(dirname "$file")"
    mv -f "$STAGE/$file" "$OUT/$file"
done
(cd "$OUT" && sha256sum "${RESULTS[@]}" | sed -E 's#^([0-9a-f]+)  (.*/)?#\1  #' > SHA256SUMS.new &&
    mv -f SHA256SUMS.new SHA256SUMS)

# The files attached to a GitHub release carry only the name and version:
# the distribution they are built for is said in the release notes.
RELEASE=$OUT/release
rm -rf "$RELEASE"
mkdir -p "$RELEASE"
cp "$OUT"/fedora-*/"$NAME-$VERSION"-*.noarch.rpm "$RELEASE/$NAME-$VERSION.rpm"
cp "$OUT"/debian-*/"${NAME}_${VERSION}_all.deb" "$RELEASE/$NAME-$VERSION.deb"
(cd "$RELEASE" && sha256sum "$NAME-$VERSION.rpm" "$NAME-$VERSION.deb" > SHA256SUMS)

echo
echo "Built $NAME $VERSION:"
for file in "${RESULTS[@]}" SHA256SUMS; do
    echo "  $OUT/$file"
done
echo "Release files:"
for file in "$NAME-$VERSION.rpm" "$NAME-$VERSION.deb" SHA256SUMS; do
    echo "  $RELEASE/$file"
done
