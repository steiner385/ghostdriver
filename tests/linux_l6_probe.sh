#!/usr/bin/env bash
# L6: the operator's foreground must never move, and the watchdog.
#
# Runs inside a nested display with its own session bus and window manager
# (tests/test_linux_foreground.py sets that up). The operator's display is
# read, never driven -- reading _NET_ACTIVE_WINDOW on :0 is the whole point,
# and touching it would be the bug this measures for.
#
# The control runs FIRST and the script aborts if it fails. "The foreground
# did not move" is trivially true of a harness that did nothing at all, so
# the drive has to be shown to work before its non-effect means anything.
set -u
OP=${GHOSTDRIVER_OPERATOR_DISPLAY:-:0}

gnome-shell --x11 >/dev/null 2>&1 & WM_PID=$!
for i in $(seq 1 30); do
  xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -q 0x && break; sleep 1; done

python3 -m tests.fixtureapp_gtk --present-after 45000 --quit-after 120000 \
  2>/dev/null > /tmp/gd-l6-probe.json & B_PID=$!
sleep 6

j(){ head -1 /tmp/gd-l6-probe.json | python3 -c "import json,sys;d=json.load(sys.stdin);print($1)"; }
XB=$(j 'd["main"]')
BX=$(j 'd["bounds"]["drawn_button"]["x"]+d["bounds"]["drawn_button"]["w"]//2')
BY=$(j 'd["bounds"]["drawn_button"]["y"]+d["bounds"]["drawn_button"]["h"]//2')
want=$(printf 0x%x "$XB")

opact(){ DISPLAY=$OP xprop -root _NET_ACTIVE_WINDOW 2>/dev/null | sed 's/.*# //'; }
nsact(){ xprop -root _NET_ACTIVE_WINDOW 2>/dev/null | sed 's/.*# //'; }
ev(){ grep -c recalculated /tmp/gd-l6-probe.json || true; }
hidden(){ xprop -id "$XB" _NET_WM_STATE 2>/dev/null | grep -c HIDDEN; }
colours(){ xwd -id "$XB" -silent > "/tmp/gd-l6-$1.xwd" 2>/dev/null
           convert "/tmp/gd-l6-$1.xwd" -format "%k" info: 2>/dev/null || echo 0; }

OP0=$(opact); echo "OPERATOR baseline $OP0"
for i in $(seq 1 10); do xdotool windowactivate "$XB" 2>/dev/null; sleep 1
  [ "$(nsact)" = "$want" ] && break; done
[ "$(nsact)" = "$want" ] && echo "CONTROL focus ok" || { echo "ABORT focus"; exit 1; }

b=$(ev); xdotool mousemove --window "$XB" "$BX" "$BY" 2>/dev/null; sleep 0.6
xdotool click 1 2>/dev/null; sleep 1.5
[ "$(ev)" = "$b" ] && { echo "ABORT the drive did nothing; a still foreground proves nothing"; exit 1; }
echo "CONTROL drive $b -> $(ev)"
echo "== controls pass =="

echo "RESULT operator_after_drive $(opact)"
echo "RESULT mapped hidden=$(hidden) colours=$(colours mapped)"
xdotool windowminimize "$XB" 2>/dev/null; sleep 3
echo "RESULT iconified hidden=$(hidden) colours=$(colours icon)"
echo "RESULT operator_after_iconify $(opact)"

for i in $(seq 1 60); do grep -q grabbed /tmp/gd-l6-probe.json 2>/dev/null && break; sleep 1; done
sleep 2
echo "RESULT after_present hidden=$(hidden) nested_active=$(nsact) target=$want"
echo "RESULT operator_after_present $(opact)"
xdotool windowminimize "$XB" 2>/dev/null; sleep 2.5
echo "RESULT re_iconified hidden=$(hidden) colours=$(colours reicon)"
echo "RESULT operator_final $(opact)"

kill "$WM_PID" "$B_PID" 2>/dev/null || true
wait "$WM_PID" "$B_PID" 2>/dev/null || true
exit 0
