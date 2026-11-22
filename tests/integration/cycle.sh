#!/bin/bash
# Reinstall into the test prefix and restart the isolated shell with the
# given extensions enabled. GNOME Shell cannot reload extension code, so
# every iteration needs a fresh shell - just like a re-login for users.
#   cycle.sh BUILD_DIR [uuid...] [-- WxH ...]
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
build=$1; shift
uuids=(); monitors=()
while [ $# -gt 0 ]; do
    if [ "$1" = "--" ]; then shift; monitors=("$@"); break; fi
    uuids+=("$1"); shift
done
meson install -C "$build" > "$build/install.log"
"$HERE/session.sh" stop >/dev/null 2>&1 || true
"$HERE/session.sh" start "${monitors[@]:-1280x800}"
for u in "${uuids[@]}"; do
    "$HERE/session.sh" run gnome-extensions enable "$u"
done
sleep 2
for u in "${uuids[@]}"; do
    "$HERE/session.sh" eval "const e = Main.extensionManager.lookup('$u'); \`$u state=\${e?.state} \${e?.error ?? ''}\`"
done
