"""L5: how a driver can tell an application is held by a modal.

D48 measured the Windows shape: a modal disables the *top-level* and leaves
every control inside reporting enabled, so a driver that asks the control
alone sees nothing wrong and actuates into a held application. The question
here is what the equivalent signals are, and whether that asymmetry repeats.

L5's third question -- whether a sent event to a held window is honoured --
is already answered: D#11 measured that sent events are ignored in every
configuration, held or not, so there is nothing modality can add to it.
"""

import json
import os
import subprocess
import sys
import time

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi  # noqa: E402


def _states(node, names):
    got = node.get_state_set()
    return sorted(n for n in names if got.contains(getattr(Atspi.StateType, n)))


WATCHED = ("SENSITIVE", "ENABLED", "MODAL", "SHOWING", "VISIBLE", "ACTIVE", "FOCUSABLE")


def _walk(node, out=None, depth=0):
    out = out if out is not None else []
    out.append((depth, node))
    for i in range(node.get_child_count()):
        child = node.get_child_at_index(i)
        if child is not None:
            _walk(child, out, depth + 1)
    return out


def _snapshot(app):
    frames = []
    for depth, node in _walk(app):
        if depth > 2 and node.get_role_name() not in ("dialog", "alert", "frame"):
            continue
        frames.append({
            "depth": depth,
            "role": node.get_role_name(),
            "name": node.get_name(),
            "states": _states(node, WATCHED),
        })
    return frames


def _xprop(xid, name):
    got = subprocess.run(["xprop", "-id", str(xid), name],
                         capture_output=True, text=True, timeout=10)
    return got.stdout.strip()


def main():
    app = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp_gtk",
         "--modal-after", "9000", "--quit-after", "70000"],
        stdout=subprocess.PIPE, text=True,
        env=dict(os.environ, GDK_BACKEND="x11"),
    )
    announced = json.loads(app.stdout.readline())
    time.sleep(3)

    Atspi.init()
    desktop = Atspi.get_desktop(0)
    mine = next(desktop.get_child_at_index(i) for i in range(desktop.get_child_count())
                if desktop.get_child_at_index(i).get_process_id() == announced["pid"])

    report = {"pid": announced["pid"], "main_xid": announced["main"]}

    # Wait for the window manager to have focused the fixture before taking
    # the baseline. `ACTIVE` is one of the states this measurement compares,
    # and a baseline snapshotted before the WM got round to focusing the
    # window records "not active" and then compares it against "not active"
    # -- which is not a finding, it is a race. Recorded rather than assumed:
    # if it never becomes active the report says so and the test skips.
    settle = time.monotonic() + 20
    while time.monotonic() < settle:
        frame = next((f for f in _snapshot(mine)
                      if f["role"] == "frame" and "fixture" in f["name"]), None)
        if frame and "ACTIVE" in frame["states"]:
            break
        time.sleep(0.5)
    report["before"] = _snapshot(mine)
    report["baseline_was_active"] = any(
        f["role"] == "frame" and "fixture" in f["name"] and "ACTIVE" in f["states"]
        for f in report["before"]
    )

    # Wait for the modal, then look again.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if any(f["role"] in ("dialog", "alert") for f in _snapshot(mine)):
            break
        time.sleep(0.5)
    time.sleep(1.5)
    report["during"] = _snapshot(mine)

    # X's side of the same question. The client list, not `xwininfo
    # -children`: a modal is a managed top-level and the window manager is
    # what knows about it, which is also why a bare Xvfb has none of this
    # (D75).
    listing = subprocess.run(["xprop", "-root", "_NET_CLIENT_LIST"],
                             capture_output=True, text=True, timeout=10)
    xids = [x.strip() for x in listing.stdout.rsplit("#", 1)[-1].split(",")] \
        if "#" in listing.stdout else []
    report["x"] = {}
    for xid in xids:
        if not xid:
            continue
        report["x"][xid] = {
            "name": _xprop(xid, "_NET_WM_NAME"),
            "pid": _xprop(xid, "_NET_WM_PID"),
            "wm_state": _xprop(xid, "_NET_WM_STATE"),
            "transient_for": _xprop(xid, "WM_TRANSIENT_FOR"),
        }

    print(json.dumps(report), flush=True)
    app.terminate()
    app.wait(timeout=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
