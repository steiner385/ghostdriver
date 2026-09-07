#!/usr/bin/env bash
# L4: does GTK act on a sent event? Run inside a nested display with its own
# session bus (see tests/test_linux_tier3.py, which sets that up).
#
# Controls run FIRST and the script aborts if they fail. A negative result
# from a harness that could not have produced a positive one is worthless,
# and this measurement produced three such results before the controls were
# put in front: once with no window manager, once with the pointer aimed at
# coordinates the window manager had moved, and once with focus that never
# took. Every line below prints what it did, so a reader can tell an
# experiment that failed from a harness that did.
set -u
gnome-shell --x11 >/dev/null 2>&1 &
WM_PID=$!
for i in $(seq 1 30); do
  xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -q 0x && break; sleep 1; done
python3 -m tests.fixtureapp_gtk --grid-no-copy --quit-after 100000 2>/dev/null > /tmp/gd-A.json &
A_PID=$!
sleep 5
python3 -m tests.fixtureapp_gtk             --quit-after 100000 2>/dev/null > /tmp/gd-B.json &
B_PID=$!
sleep 6
j() { head -1 "$1" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d$2)"; }
XA=$(j /tmp/gd-A.json '["main"]'); XB=$(j /tmp/gd-B.json '["main"]')
BX=$(j /tmp/gd-B.json '["bounds"]["drawn_button"]["x"]+d["bounds"]["drawn_button"]["w"]//2')
BY=$(j /tmp/gd-B.json '["bounds"]["drawn_button"]["y"]+d["bounds"]["drawn_button"]["h"]//2')
act(){ xprop -root _NET_ACTIVE_WINDOW | sed 's/.*# //'; }
ev(){ grep -c recalculated /tmp/gd-B.json || true; }
focus(){ w=$(printf 0x%x "$1"); for i in $(seq 1 10); do xdotool windowactivate "$1" 2>/dev/null; sleep 1
  [ "$(act)" = "$w" ] && return 0; done; return 1; }

focus "$XB" || { echo "ABORT focus B"; exit 1; }
printf C1 | xclip -selection clipboard; sleep 0.3; xdotool key ctrl+c 2>/dev/null; sleep 1.2
K=$(xclip -selection clipboard -o 2>/dev/null|head -1); echo "CONTROL xtest-key [$K]"
[ "$K" = "C1" ] && { echo "ABORT xtest-key"; exit 1; }
b=$(ev); xdotool mousemove --window "$XB" "$BX" "$BY" 2>/dev/null; sleep 0.6; xdotool click 1 2>/dev/null; sleep 1.5
[ "$(ev)" = "$b" ] && { echo "ABORT xtest-click"; exit 1; }
echo "CONTROL xtest-click $b -> $(ev)"; echo "== controls pass =="

printf E1 | xclip -selection clipboard; sleep 0.3
xdotool key --window "$XB" ctrl+c 2>/dev/null; sleep 1.5
echo "EXPT A sent-key target-FOCUSED   [$(xclip -selection clipboard -o 2>/dev/null|head -1)]"
b=$(ev); xdotool mousemove 1250 790 2>/dev/null; sleep 0.4; xdotool click --window "$XB" 1 2>/dev/null; sleep 1.5
echo "EXPT B sent-button target-FOCUSED pointer-away $b -> $(ev)"

focus "$XA" || { echo "ABORT focus A"; exit 1; }
echo "-- A now active ($(act)) --"
printf E3 | xclip -selection clipboard; sleep 0.3
xdotool key --window "$XB" ctrl+c 2>/dev/null; sleep 1.5
echo "EXPT C sent-key target-UNFOCUSED [$(xclip -selection clipboard -o 2>/dev/null|head -1)]"
b=$(ev); xdotool mousemove 1250 790 2>/dev/null; sleep 0.4; xdotool click --window "$XB" 1 2>/dev/null; sleep 1.5
echo "EXPT D sent-button target-UNFOCUSED pointer-away $b -> $(ev)"

# Explicit teardown, by pid and only by pid: bash waits on its background
# jobs, so without this the script outlives the measurement by the fixtures'
# lifetime. Deliberately not `pkill -f`: the operator is running their own
# desktop on their own display, and a pattern broad enough to catch this
# shell's gnome-shell is broad enough to catch theirs. Taking the operator's
# desktop is the one thing this project exists not to do.
kill "$WM_PID" "$A_PID" "$B_PID" 2>/dev/null || true
wait "$WM_PID" "$A_PID" "$B_PID" 2>/dev/null || true
exit 0
