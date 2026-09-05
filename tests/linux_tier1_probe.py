"""L3: tier 1 -- what the accessibility API can drive on its own.

Runs inside the nested session bus as its own process, like the other Linux
probes. Reports one JSON line. Never imported.
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi  # noqa: E402


def _find(node, name):
    if node.get_name() == name:
        return node
    for i in range(node.get_child_count()):
        child = node.get_child_at_index(i)
        if child is not None:
            found = _find(child, name)
            if found is not None:
                return found
    return None


def _actions(node):
    try:
        return [Atspi.Action.get_action_name(node, i)
                for i in range(Atspi.Action.get_n_actions(node))]
    except Exception as exc:
        return [f"<{type(exc).__name__}>"]


def _do(node):
    try:
        return bool(Atspi.Action.do_action(node, 0))
    except Exception as exc:
        return f"<{type(exc).__name__}>"


def _text(node):
    try:
        return Atspi.Text.get_text(node, 0, Atspi.Text.get_character_count(node))
    except Exception as exc:
        return f"<{type(exc).__name__}>"


def main():
    app = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp_gtk", "--quit-after", "60000"],
        stdout=subprocess.PIPE, text=True,
        env=dict(os.environ, GDK_BACKEND="x11"),
    )
    announced = json.loads(app.stdout.readline())
    time.sleep(3)

    events: queue.Queue = queue.Queue()

    def pump():
        for line in app.stdout:
            line = line.strip()
            if line.startswith("{"):
                events.put(json.loads(line))

    threading.Thread(target=pump, daemon=True).start()

    def drain(seconds=2.0):
        out, end = [], time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                out.append(events.get(timeout=0.2))
            except queue.Empty:
                pass
        return out

    Atspi.init()
    desktop = Atspi.get_desktop(0)
    mine = next(desktop.get_child_at_index(i) for i in range(desktop.get_child_count())
                if desktop.get_child_at_index(i).get_process_id() == announced["pid"])

    real, drawn = _find(mine, "Apply"), _find(mine, "Recalculate")
    bound = _find(mine, "bound entry")

    report = {
        "real_button": {"actions": _actions(real)},
        "drawn_button": {"actions": _actions(drawn)},
        "bound_entry": {"interfaces": sorted(bound.get_interfaces())},
    }
    report["real_button"]["do_action"] = _do(real)
    report["real_button"]["events"] = drain()
    report["drawn_button"]["do_action"] = _do(drawn)
    report["drawn_button"]["events"] = drain()

    report["bound_entry"]["before"] = _text(bound)
    try:
        report["bound_entry"]["set_text"] = bool(
            Atspi.EditableText.set_text_contents(bound, "written-by-atspi"))
    except Exception as exc:
        report["bound_entry"]["set_text"] = f"<{type(exc).__name__}>"
    report["bound_entry"]["events"] = drain()
    report["bound_entry"]["after"] = _text(bound)

    try:
        Atspi.Component.grab_focus(bound)
        report["grab_focus"] = True
    except Exception as exc:
        report["grab_focus"] = f"<{type(exc).__name__}>"

    print(json.dumps(report), flush=True)
    app.terminate()
    app.wait(timeout=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
