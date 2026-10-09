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
#
# #163: the measurement steps used to be fixed sleeps -- `sleep 2.5` after
# minimize, `sleep 2` after activate -- and under a full suite's load GNOME
# Shell had not finished by the time the probe read the answer, so
# `test_restoring_a_window_necessarily_focuses_it` failed on every full run
# and passed when the module ran alone. `focus` below already had the right
# shape and the measurements did not; they do now. Each step reports how long
# it took on a TIMING line, so a limit that is generous today and tight next
# year says so rather than becoming the next flake.
set -u
# A headless gnome-shell's Xwayland, not Xvfb + `gnome-shell --x11` (#217).
. "$(dirname "$0")/linux_nested_shell.sh"
gd_start_nested_shell || { echo "ABORT nested shell did not start"; exit 1; }
WM_PID=$GD_SHELL_PID

now_ms(){ date +%s%3N; }

# Poll a condition until it holds, then return. This is not a retried
# measurement (D45): the condition is the window manager finishing the action
# just asked for, and the measurement is taken once, afterwards. The elapsed
# time is reported either way, which is the part a fixed sleep threw away.
settle(){
  local what=$1 limit=$2 start ms polls=0
  shift 2
  start=$(now_ms)
  while :; do
    polls=$((polls+1))
    if "$@"; then
      ms=$(( $(now_ms) - start ))
      echo "TIMING $what ok=1 ms=$ms limit=${limit}s polls=$polls"
      return 0
    fi
    ms=$(( $(now_ms) - start ))
    if [ "$ms" -ge $(( limit * 1000 )) ]; then
      echo "TIMING $what ok=0 ms=$ms limit=${limit}s polls=$polls"
      return 1
    fi
    sleep 0.25
  done
}

act(){ xprop -root _NET_ACTIVE_WINDOW | sed 's/.*# //'; }
hidden(){ xprop -id "$1" _NET_WM_STATE 2>/dev/null | grep -c HIDDEN; }
announced(){ head -1 "$1" 2>/dev/null | grep -q '"main"'; }
is_hidden(){ [ "$(hidden "$1")" = "1" ]; }
is_shown(){ [ "$(hidden "$1")" = "0" ]; }
is_active(){ [ "$(act)" = "$(printf 0x%x "$1")" ]; }
restored(){ is_shown "$1" && is_active "$1"; }
focus(){ settle "focus_$2" 40 _focus_once "$1"; }
_focus_once(){ xdotool windowactivate "$1" 2>/dev/null; is_active "$1"; }

# The window manager has taken the window on. The fixture announces its X id
# on a 120ms timer, which is well before GNOME Shell has adopted the window
# -- so the announce line is not the precondition for activating it, and
# treating it as one asks the window manager about something it has never
# heard of. The old `sleep 5` per application covered this by accident.
managed(){ xprop -root _NET_CLIENT_LIST 2>/dev/null \
  | tr ' ,' '\n\n' | grep -qx "$(printf 0x%x "$1")"; }

# A directory of its own, rather than two fixed paths in /tmp. The announce
# wait is a condition on file *contents* now, and a previous run's leftovers
# satisfy it instantly -- which hands the measurement two window ids that no
# longer exist and aborts on a control that had nothing wrong with it.
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT

python3 -m tests.fixtureapp_gtk --quit-after 120000 2>/dev/null > "$OUT/a.json" & A_PID=$!
settle announce_a 30 announced "$OUT/a.json" || { echo "ABORT A never announced"; exit 1; }
XA=$(head -1 "$OUT/a.json" | python3 -c 'import json,sys;print(json.load(sys.stdin)["main"])')
settle managed_a 30 managed "$XA" || { echo "ABORT A was never managed"; exit 1; }

python3 -m tests.fixtureapp_gtk --quit-after 120000 2>/dev/null > "$OUT/b.json" & B_PID=$!
settle announce_b 30 announced "$OUT/b.json" || { echo "ABORT B never announced"; exit 1; }
XB=$(head -1 "$OUT/b.json" | python3 -c 'import json,sys;print(json.load(sys.stdin)["main"])')
settle managed_b 30 managed "$XB" || { echo "ABORT B was never managed"; exit 1; }

focus "$XA" a || { echo "ABORT could not focus A"; exit 1; }
echo "CONTROL focus A ok active=$(act)"
xdotool windowminimize "$XA" 2>/dev/null
settle hide_a 30 is_hidden "$XA" || { echo "ABORT A did not hide"; exit 1; }
echo "CONTROL A hidden ok"

# B takes the foreground, so A cannot be restored *into* a focus it already had
focus "$XB" b || { echo "ABORT could not focus B"; exit 1; }
echo "CONTROL focus B ok active=$(act)"
echo "== controls pass =="

BEFORE=$(act)
echo "RESULT before_restore active=$BEFORE a_hidden=$(hidden "$XA") target=$(printf 0x%x "$XA")"

# The measurement: map A without asking for focus.
#
# The one step that stays a fixed wait, on purpose. The claim is a negative --
# the map changes *nothing* -- and there is no condition to poll for a thing
# that should not happen; polling would only spend the whole limit and then
# report the same state. So the dwell is part of what the answer means: "three
# seconds after a bare map, still hidden". Reported as a dwell rather than a
# settle so a reader can see which steps are still guessing.
xdotool windowmap "$XA" 2>/dev/null; sleep 3
echo "TIMING map_dwell ok=1 ms=3000 dwell=1"
echo "RESULT after_map a_hidden=$(hidden "$XA") active=$(act) was=$BEFORE"

# And the route that does ask, for comparison. A positive claim, so this one
# waits for the window manager instead of assuming two seconds of it.
xdotool windowactivate "$XA" 2>/dev/null
settle restore_a 30 restored "$XA" || true
echo "RESULT after_activate a_hidden=$(hidden "$XA") active=$(act)"

kill "$WM_PID" "$A_PID" "$B_PID" 2>/dev/null || true
wait "$WM_PID" "$A_PID" "$B_PID" 2>/dev/null || true
exit 0
