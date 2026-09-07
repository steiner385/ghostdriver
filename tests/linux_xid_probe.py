"""Slice 3, the correlation this backend does not have: an AT-SPI frame to
its X window.

Windows has one identifier space. An `hwnd` is what the accessibility layer
talks about *and* what the window manager talks about, so `top_level_state`
can report `owner` and `handle` in the same currency without thinking about
it.

Linux has two. The tree mints handles for AT-SPI accessibles (`tree._mint`);
modality lives in `_NET_WM_STATE_MODAL` and `WM_TRANSIENT_FOR`, which are X
properties on an *xid*. `find_modal_blocks` does `by_handle[window.owner]`,
so a backend that reported `owner` as an xid would look every owner up in
the wrong space and find nothing -- which fails exactly the way D#12 warns
about, silently, with every state it can read saying the application is fine.

`reading._toplevel_xid` already needs this and answers it by shelling out to
`xwininfo -root -children` and then `xprop` per candidate, matching on pid.
That is two processes per call (the shape D#40c called a fork bomb) and it
cannot tell two windows of the *same* process apart -- it returns the first
pid match, which is the wrong answer whenever there is a modal up, because a
modal is a second window of the same process.

So: what actually identifies which frame is which? Four routes, measured
rather than assumed.

1. `Atspi.Accessible.get_attributes()` -- GTK puts toolkit metadata here and
   some versions include a window id outright. If it does, everything else
   in this file is unnecessary.
2. The `Component` interface's extents, against X geometry. Position and
   size are a strong key and need no name.
3. The accessible name against `_NET_WM_NAME`. Cheap, and ambiguous the
   moment two windows share a title -- which D33 says to refuse rather than
   guess at.
4. Ordering -- the nth frame is the nth client. Recorded only to show
   whether it holds; relying on it would be modelling.

Prints one JSON line. Nothing here is imported by the test process.
"""

import json
import os
import subprocess
import sys
import time

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi  # noqa: E402

from Xlib import display as xdisplay  # noqa: E402

WATCHED = ("SENSITIVE", "MODAL", "SHOWING", "VISIBLE", "ACTIVE")


def _states(node):
    got = node.get_state_set()
    return sorted(n for n in WATCHED if got.contains(getattr(Atspi.StateType, n)))


def _attributes(node):
    """`get_attributes` is the cheapest possible answer if it carries an id."""
    try:
        got = node.get_attributes()
    except Exception as exc:  # noqa: BLE001 -- the probe records, never fails
        return {"error": repr(exc)}
    return dict(got) if got else {}


def _extents(node):
    try:
        got = node.get_extents(Atspi.CoordType.SCREEN)
    except Exception as exc:  # noqa: BLE001
        return {"error": repr(exc)}
    return {"x": got.x, "y": got.y, "w": got.width, "h": got.height}


def _frames(app):
    """The app's top-level children -- frames and dialogs, not the tree."""
    out = []
    for index in range(app.get_child_count()):
        node = app.get_child_at_index(index)
        if node is None:
            continue
        out.append({
            "index": index,
            "role": node.get_role_name(),
            "name": node.get_name(),
            "states": _states(node),
            "attributes": _attributes(node),
            "extents": _extents(node),
        })
    return out


def _x_side(pid):
    """Every managed top-level of `pid`, over one real X connection.

    `_NET_CLIENT_LIST` rather than `xwininfo -children`: a modal is a managed
    top-level and the window manager is what knows about it, which is why a
    bare Xvfb has none of this (D75).
    """
    dsp = xdisplay.Display()
    root = dsp.screen().root

    def atom(name):
        return dsp.intern_atom(name)

    def prop(window, name):
        try:
            got = window.get_full_property(atom(name), 0)
        except Exception:  # noqa: BLE001
            return None
        return got.value if got is not None else None

    listed = prop(root, "_NET_CLIENT_LIST") or []
    out = {}
    for xid in [int(x) for x in listed]:
        window = dsp.create_resource_object("window", xid)
        got_pid = prop(window, "_NET_WM_PID")
        if not got_pid or int(got_pid[0]) != pid:
            continue
        name = prop(window, "_NET_WM_NAME")
        transient = prop(window, "WM_TRANSIENT_FOR")
        states = [dsp.get_atom_name(s) for s in (prop(window, "_NET_WM_STATE") or [])]
        try:
            geometry = window.get_geometry()
            # A reparenting WM puts the client inside a frame, so the
            # client's own x/y are relative to that frame and useless for
            # comparing against AT-SPI's screen coordinates. Translate.
            coords = root.translate_coords(window, 0, 0)
            box = {"x": coords.x, "y": coords.y,
                   "w": geometry.width, "h": geometry.height}
        except Exception as exc:  # noqa: BLE001
            box = {"error": repr(exc)}
        out[str(xid)] = {
            "name": bytes(name).decode("utf-8", "replace") if name else None,
            "transient_for": int(transient[0]) if transient else None,
            "states": states,
            "box": box,
        }
    return out


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
    mine = next(
        desktop.get_child_at_index(i) for i in range(desktop.get_child_count())
        if desktop.get_child_at_index(i).get_process_id() == announced["pid"]
    )
    pid = announced["pid"]

    report = {"pid": pid, "announced": announced}
    report["before"] = {"frames": _frames(mine), "x": _x_side(pid)}

    # With the modal up there are two windows of one process, which is the
    # case the pid-matching route cannot answer and the whole reason this
    # measurement exists.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if any(f["role"] in ("dialog", "alert") for f in _frames(mine)):
            break
        time.sleep(0.5)
    time.sleep(1.5)
    report["during"] = {"frames": _frames(mine), "x": _x_side(pid)}

    print(json.dumps(report), flush=True)
    app.terminate()
    app.wait(timeout=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
