#!/bin/bash
# Isolated headless GNOME Shell session for integration testing.
#
# Everything (HOME, D-Bus session bus, XDG_RUNTIME_DIR, dconf database,
# install prefix) lives under $DESKENCE_TEST_DIR, so the developer's running
# session is never touched.
#
#   session.sh start [WxH ...]   start dbus + headless gnome-shell
#   session.sh env               print exports for the test session
#   session.sh eval 'js code'    run JS in the shell (test helper enables it)
#   session.sh shot file.png     take a screenshot of the virtual monitor(s)
#   session.sh run cmd args...   run a command inside the test session
#   session.sh log               print the shell log
#   session.sh stop              stop everything
#
# The project must be installed into $DESKENCE_TEST_DIR/prefix first
# (see docs/testing.md).
set -euo pipefail

DESKENCE_TEST_DIR=${DESKENCE_TEST_DIR:-${TMPDIR:-/tmp}/deskence-test}
# Wayland socket paths are limited to 108 bytes, keep the runtime dir short.
DESKENCE_RUNTIME_DIR=${DESKENCE_RUNTIME_DIR:-${TMPDIR:-/tmp}/deskence-rt-$UID}
HERE=$(cd "$(dirname "$0")" && pwd)

T=$DESKENCE_TEST_DIR
PREFIX=$T/prefix

session_env() {
    echo "export HOME='$T/home'"
    echo "export XDG_RUNTIME_DIR='$DESKENCE_RUNTIME_DIR'"
    echo "export XDG_CONFIG_HOME='$T/home/.config'"
    echo "export XDG_DATA_HOME='$T/home/.local/share'"
    echo "export XDG_CACHE_HOME='$T/home/.cache'"
    echo "export XDG_STATE_HOME='$T/home/.local/state'"
    echo "export XDG_DATA_DIRS='$PREFIX/share:/usr/local/share:/usr/share'"
    echo "export XDG_CURRENT_DESKTOP=GNOME"
    echo "export XDG_SESSION_TYPE=wayland"
    echo "export GSETTINGS_SCHEMA_DIR='$PREFIX/share/glib-2.0/schemas'"
    echo "export PYTHONPATH='$(find "$PREFIX" -type d -name site-packages 2>/dev/null | head -1)'"
    echo "export PATH='$PREFIX/bin:/usr/bin:/bin'"
    echo "export WAYLAND_DISPLAY=wayland-deskence-test"
    echo "export GDK_BACKEND=wayland"
    if [ -f "$T/bus-address" ]; then
        echo "export DBUS_SESSION_BUS_ADDRESS='$(cat "$T/bus-address")'"
    fi
    echo "export LANG=${DESKENCE_TEST_LANG:-pl_PL.UTF-8}"
}

in_session() {
    env -i bash -c "$(session_env); exec \"\$@\"" bash "$@"
}

cmd=${1:-}
shift || true

case "$cmd" in
start)
    mkdir -p "$T/home/.local/share/gnome-shell/extensions" "$T/home/.config" "$T/home/Pulpit"
    rm -rf "$DESKENCE_RUNTIME_DIR"
    mkdir -p "$DESKENCE_RUNTIME_DIR"
    chmod 700 "$DESKENCE_RUNTIME_DIR"
    # Non-default XDG desktop dir name on purpose: the product must not
    # assume "Desktop".
    printf 'XDG_DESKTOP_DIR="$HOME/Pulpit"\n' > "$T/home/.config/user-dirs.dirs"
    cp -r "$HERE/test-helper" "$T/home/.local/share/gnome-shell/extensions/deskence-test-helper@local"
    rm -f "$T/bus-address"
    addr=$(in_session dbus-daemon --session --fork --print-address=1 --print-pid=3 3>"$T/bus-pid")
    echo "$addr" > "$T/bus-address"
    monitors=()
    for m in "${@:-1600x900}"; do monitors+=(--virtual-monitor "$m"); done
    in_session gsettings set org.gnome.shell enabled-extensions "['deskence-test-helper@local']"
    in_session gsettings set org.gnome.shell welcome-dialog-last-shown-version '999'
    in_session gsettings set org.gnome.desktop.interface enable-hot-corners false
    in_session bash -c "nohup gnome-shell --headless --wayland --no-x11 \
        --wayland-display wayland-deskence-test ${monitors[*]} > '$T/shell.log' 2>&1 & echo \$! > '$T/shell-pid'"
    for _ in $(seq 60); do
        if in_session gdbus call --session -d org.gnome.Shell -o /org/gnome/Shell \
            -m org.gnome.Shell.Eval 'true' 2>/dev/null | grep -q "(true"; then
            echo "shell ready"
            exit 0
        fi
        sleep 0.5
    done
    echo "shell did not become ready, see $T/shell.log" >&2
    exit 1
    ;;
env)
    session_env
    ;;
eval)
    out=$(in_session gdbus call --session -d org.gnome.Shell -o /org/gnome/Shell \
        -m org.gnome.Shell.Eval "$1")
    echo "$out"
    case "$out" in "(true,"*) ;; *) exit 1 ;; esac
    ;;
shot)
    in_session gdbus call --session -d org.gnome.Shell.Screenshot \
        -o /org/gnome/Shell/Screenshot -m org.gnome.Shell.Screenshot.Screenshot \
        false false "$(realpath -m "$1")" > /dev/null
    echo "$1"
    ;;
run)
    in_session "$@"
    ;;
log)
    cat "$T/shell.log"
    ;;
stop)
    [ -f "$T/shell-pid" ] && kill "$(cat "$T/shell-pid")" 2>/dev/null || true
    sleep 1
    [ -f "$T/bus-pid" ] && kill "$(cat "$T/bus-pid")" 2>/dev/null || true
    rm -f "$T/shell-pid" "$T/bus-pid" "$T/bus-address"
    # The document portal mounts a FUSE filesystem in the runtime dir.
    fusermount3 -u "$DESKENCE_RUNTIME_DIR/doc" 2>/dev/null || fusermount -u "$DESKENCE_RUNTIME_DIR/doc" 2>/dev/null || true
    rm -rf "$DESKENCE_RUNTIME_DIR"
    ;;
*)
    sed -n '2,20p' "$0"
    exit 2
    ;;
esac
