#!/bin/bash
# Drive a virtual pointer in the test shell.
#   pointer.sh move X Y | click X Y [button] | down X Y | up [button]
H=$(dirname "$0")/session.sh
SETUP="{ const C = imports.gi.Clutter; const G = imports.gi.GLib;
if (!global._deskenceVp) global._deskenceVp = global.stage.context.get_backend().get_default_seat().create_virtual_device(C.InputDeviceType.POINTER_DEVICE);
const vp = global._deskenceVp; const t = () => G.get_monotonic_time();"
END="'ok'; }"
case $1 in
move) "$H" eval "$SETUP vp.notify_absolute_motion(t(), $2, $3); $END" >/dev/null ;;
click) b=${4:-1}
    "$H" eval "$SETUP vp.notify_absolute_motion(t(), $2, $3); $END" >/dev/null; sleep 0.15
    "$H" eval "$SETUP vp.notify_button(t(), $b, C.ButtonState.PRESSED); $END" >/dev/null; sleep 0.08
    "$H" eval "$SETUP vp.notify_button(t(), $b, C.ButtonState.RELEASED); $END" >/dev/null ;;
down) "$H" eval "$SETUP vp.notify_absolute_motion(t(), $2, $3); vp.notify_button(t(), ${4:-1}, C.ButtonState.PRESSED); $END" >/dev/null ;;
up) "$H" eval "$SETUP vp.notify_button(t(), ${2:-1}, C.ButtonState.RELEASED); $END" >/dev/null ;;
esac
# Keyboard: pointer.sh type "text" | key KEYNAME [modifier...]
KSETUP="{ const C = imports.gi.Clutter; const G = imports.gi.GLib;
if (!global._deskenceVk) global._deskenceVk = global.stage.context.get_backend().get_default_seat().create_virtual_device(C.InputDeviceType.KEYBOARD_DEVICE);
const vk = global._deskenceVk; const t = () => G.get_monotonic_time();
const tap = k => { vk.notify_keyval(t(), k, C.KeyState.PRESSED); vk.notify_keyval(t(), k, C.KeyState.RELEASED); };"
case $1 in
type) text=$(printf '%s' "$2" | sed "s/'/\\\\'/g")
    "$H" eval "$KSETUP for (const ch of '$text') tap(C.unicode_to_keysym(ch.codePointAt(0))); 'ok'; }" >/dev/null ;;
key) shift; key=$1; shift; mods=("$@")
    js="$KSETUP const mods = [$(for m in "${mods[@]}"; do printf "C.KEY_%s," "$m"; done)];
    for (const m of mods) vk.notify_keyval(t(), m, C.KeyState.PRESSED);
    tap(C.KEY_$key);
    for (const m of mods.reverse()) vk.notify_keyval(t(), m, C.KeyState.RELEASED); 'ok'; }"
    "$H" eval "$js" >/dev/null ;;
esac
