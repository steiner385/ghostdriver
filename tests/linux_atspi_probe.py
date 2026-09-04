"""Runs *inside* the nested session bus and reports what AT-SPI sees, as JSON.

A separate process on purpose. The pytest process must not join the nested
bus: the whole point of the nested display is that what is on it is not what
is on the operator's, and a test runner that joined it would be able to see
both, which is exactly the confusion the isolation exists to prevent.

Never imported -- it is run as `python -m tests.linux_atspi_probe` under
`dbus-run-session`, so its module-scope `gi` import is deliberate.
"""

import json
import os
import subprocess
import sys
import time

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi  # noqa: E402

#: States L2 cares about. Note what is *not* here: AT-SPI has no PROTECTED
#: state at all -- 45 members and none of them names one -- which is why
#: `is_protected` cannot be answered the way the Windows backend answers it.
_STATES = ("EDITABLE", "FOCUSABLE", "SENSITIVE", "SHOWING", "VISIBLE",
           "READ_ONLY", "SINGLE_LINE")


def _text_of(node, interfaces):
    """What the Text interface gives back, or why it gave nothing."""
    if "Text" not in interfaces:
        return None
    try:
        count = Atspi.Text.get_character_count(node)
        return Atspi.Text.get_text(node, 0, count)
    except Exception as exc:
        return f"<{type(exc).__name__}>"


def _walk(node, depth=0, out=None):
    out = out if out is not None else []
    try:
        interfaces = sorted(node.get_interfaces())
        states = node.get_state_set()
        out.append({"depth": depth, "role": node.get_role_name(),
                    "name": node.get_name(),
                    "children": node.get_child_count(),
                    "interfaces": interfaces,
                    "text": _text_of(node, interfaces),
                    "states": [s for s in _STATES
                               if states.contains(getattr(Atspi.StateType, s))]})
    except Exception:
        return out
    for i in range(node.get_child_count()):
        child = node.get_child_at_index(i)
        if child is not None:
            _walk(child, depth + 1, out)
    return out


def _states(node):
    saw = node.get_state_set()
    return sorted(name for name in ("STATE_FOCUSABLE", "STATE_EDITABLE",
                                    "STATE_SENSITIVE", "STATE_SHOWING")
                  if saw.contains(getattr(Atspi.StateType, name[6:])))


def main():
    app = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp_gtk", "--quit-after", "25000"],
        stdout=subprocess.PIPE, text=True,
        env=dict(os.environ, GDK_BACKEND="x11"),
    )
    announced = json.loads(app.stdout.readline())
    time.sleep(3)

    Atspi.init()
    desktop = Atspi.get_desktop(0)
    apps = []
    mine = None
    for i in range(desktop.get_child_count()):
        child = desktop.get_child_at_index(i)
        try:
            entry = {"name": child.get_name(), "pid": child.get_process_id()}
        except Exception:
            continue
        apps.append(entry)
        if entry["pid"] == announced["pid"]:
            mine = child

    report = {"announced": announced, "desktop_children": len(apps),
              "apps": apps, "found": mine is not None}
    if mine is not None:
        nodes = _walk(mine)
        report["tree"] = nodes
        report["by_name"] = {n["name"]: n for n in nodes if n["name"]}
    print(json.dumps(report), flush=True)
    app.terminate()
    app.wait(timeout=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
