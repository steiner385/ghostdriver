#!/usr/bin/env bash
# L7: does un-hiding a window make the window manager focus it?
#
# D55 says assume it does until measured, and D4 permits `restore` at
# read_only precisely because it is the operator's own escape hatch -- the
# one place a focus change is legitimate. So the answer decides whether
# restore actually hands the window back, or only makes it visible.
#
# The two routes are kept apart on purpose. `windowactivate` maps *and*
# focuses, which would answer the question by assuming it; `windowmap` maps
# and asks for nothing. What the window manager does after a bare map is the
# measurement.
#
# Controls run first: a run where the window never hid, or never had focus to
# lose, cannot say anything about what restoring it does.
set -u
gnome-shell --x11 >/dev/null 2>&1 & WM_PID=$!
for i in $(seq 1 30); do
  xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -q 0x && break; sleep 1; done

python3 -m tests.fixtureapp_gtk --quit-after 120000 2>/dev/null > /tmp/gd-l7.json & A_PID=$!
sleep 5
python3 -m tests.fixtureapp_gtk --quit-after 120000 2>/dev/null > /tmp/gd-l7b.json & B_PID=$!
sleep 5
XA=$(head -1 /tmp/gd-l7.json  | python3 -c 'import json,sys;print(json.load(sys.stdin)["main"])')
XB=$(head -1 /tmp/gd-l7b.json | python3 -c 'import json,sys;print(json.load(sys.stdin)["main"])')

act(){ xprop -root _NET_ACTIVE_WINDOW | sed 's/.*# //'; }
hidden(){ xprop -id "$1" _NET_WM_STATE 2>/dev/null | grep -c HIDDEN; }
focus(){ w=$(printf 0x%x "$1"); for i in $(seq 1 10); do xdotool windowactivate "$1" 2>/dev/null
  sleep 1; [ "$(act)" = "$w" ] && return 0; done; return 1; }

focus "$XA" || { echo "ABORT could not focus A"; exit 1; }
echo "CONTROL focus A ok active=$(act)"
xdotool windowminimize "$XA" 2>/dev/null; sleep 2.5
[ "$(hidden "$XA")" = "1" ] || { echo "ABORT A did not hide"; exit 1; }
echo "CONTROL A hidden ok"

# B takes the foreground, so A cannot be restored *into* a focus it already had
focus "$XB" || { echo "ABORT could not focus B"; exit 1; }
echo "CONTROL focus B ok active=$(act)"
echo "== controls pass =="

BEFORE=$(act)
echo "RESULT before_restore active=$BEFORE a_hidden=$(hidden "$XA") target=$(printf 0x%x "$XA")"

# The measurement: map A without asking for focus.
xdotool windowmap "$XA" 2>/dev/null; sleep 3
echo "RESULT after_map a_hidden=$(hidden "$XA") active=$(act) was=$BEFORE"

# And the route that does ask, for comparison.
xdotool windowactivate "$XA" 2>/dev/null; sleep 2
echo "RESULT after_activate a_hidden=$(hidden "$XA") active=$(act)"

kill "$WM_PID" "$A_PID" "$B_PID" 2>/dev/null || true
wait "$WM_PID" "$A_PID" "$B_PID" 2>/dev/null || true
exit 0
