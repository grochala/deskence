#!/bin/bash
# Regression check: GNOME Shell starts with the Deskence dock enabled and the
# session takes input afterwards. Restarts only gnome-shell of a running
# isolated session (session.sh start), with the extensions already enabled
# like at login, for every combination of animations on/off and "Start on
# the desktop" on/off, and checks that GNOME finished its startup (its
# input blocker over the screen, layout.js _coverPane, is gone) and that a
# click on the top bar reaches the top bar.
#
#   startup-input.sh [extra extension uuid...]
# Environment: ANIMATIONS and START_ON_DESKTOP ("true false" by default)
# choose the combinations, REPEAT how many starts each (the startup is a
# race, so one good start proves little).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
H="$HERE/session.sh"
T=${DESKENCE_TEST_DIR:-${TMPDIR:-/tmp}/deskence-test}
MONITOR=${DESKENCE_TEST_MONITOR:-1280x800}
extensions="'deskence-test-helper@local', 'dock@deskence.github.io'"
for u in "$@"; do extensions+=", '$u'"; done

restart_shell() {
    "$H" run gsettings set org.gnome.shell enabled-extensions "[$extensions]"
    kill "$(cat "$T/shell-pid")"
    sleep 2
    "$H" run bash -c "nohup gnome-shell --headless --wayland --no-x11 \
        --wayland-display wayland-deskence-test --virtual-monitor $MONITOR \
        > '$T/shell.log' 2>&1 & echo \$! > '$T/shell-pid'"
    for _ in $(seq 60); do
        "$H" eval true >/dev/null 2>&1 && break
        sleep 0.5
    done
    sleep 4
}

STATE='JSON.stringify({startingUp: Main.layoutManager._startingUp,
  blocker: Boolean(Main.layoutManager._coverPane),
  topBar: Main.panel.contains(global.stage.get_actor_at_pos(imports.gi.Clutter.PickMode.REACTIVE,
    Main.layoutManager.primaryMonitor.x + Main.layoutManager.primaryMonitor.width / 2,
    Main.layoutManager.primaryMonitor.y + 5))})'

failed=0
for animations in ${ANIMATIONS:-true false}; do
    for desktop in ${START_ON_DESKTOP:-true false}; do
      for run in $(seq "${REPEAT:-1}"); do
        "$H" run gsettings set org.gnome.desktop.interface enable-animations $animations
        "$H" run gsettings set io.github.deskence.Deskence show-desktop-at-login $desktop
        restart_shell
        # The overview, when shown at startup, would take the click itself.
        "$H" eval 'Main.overview.hide(); true' >/dev/null
        sleep 1
        state=$("$H" eval "$STATE" | tr -d '\\"')
        if [[ $state == *'startingUp:false'* && $state == *'blocker:false'* &&
              $state == *'topBar:true'* ]]; then
            echo "ok: animations=$animations start-on-desktop=$desktop run=$run"
        else
            echo "FAIL: animations=$animations start-on-desktop=$desktop run=$run $state"
            failed=1
        fi
      done
    done
done
"$H" run gsettings reset org.gnome.desktop.interface enable-animations
exit $failed
