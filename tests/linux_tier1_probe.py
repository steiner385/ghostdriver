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

from tests.linux_probe_support import emit, settle

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi  # noqa: E402

#: How long to collect events from the fixture's pipe.
#:
#: #163: every drain was a flat 2.0s window -- not a wait for the events, a
#: guess that they had arrived. Under load they had not, and
#: `test_writing_a_value_goes_through_the_toolkit_not_around_it` failed on
#: "the binding never heard of the write", which is D21's Linux-side
#: regression and would be a genuinely important finding if it were true.
#:
#: The drains that expect something now stop as soon as it arrives and can
#: afford a much longer limit for the case where it does not. The one drain
#: that expects *nothing* keeps a fixed window, because there is no polling
#: your way to a negative -- see `drawn_button` below.
DRAIN_S = 15.0

#: The window the owner-drawn control gets to produce an event it should not
#: produce. Unchanged from the original 2.0s: lengthening it would only make
#: the run slower without making the negative any stronger.
NEGATIVE_DRAIN_S = 2.0


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

    events: queue.Queue = queue.Queue()

    def pump():
        for line in app.stdout:
            line = line.strip()
            if line.startswith("{"):
                events.put(json.loads(line))

    threading.Thread(target=pump, daemon=True).start()

    timing = []

    def drain(what, until=None, seconds=DRAIN_S):
        """Collect the fixture's events, and say how long that took.

        `until` is a predicate on what has been collected so far. Given one,
        this returns the moment it holds -- which is a wait for the events,
        not the guess that they have arrived that #163 measured failing. Its
        absence means the caller is asserting a negative, and then the full
        window is the measurement rather than a bound on it.
        """
        out, end = [], time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                out.append(events.get(timeout=0.2))
            except queue.Empty:
                pass
            if until is not None and until(out):
                break
        timing.append(emit({"what": what, "ok": until is None or until(out),
                            "seconds": round(seconds - (end - time.monotonic()), 2),
                            "timeout": seconds, "polls": len(out), "error": None,
                            "dwell": until is None}))
        return out

    Atspi.init()
    desktop = Atspi.get_desktop(0)

    # Was `time.sleep(3)`. The thing being waited for is the application
    # appearing on the accessibility bus -- and the `next()` below raises
    # `StopIteration` if it has not, which inside a probe whose stderr is
    # `DEVNULL` surfaces only as "the tier-1 probe produced no report".
    def _mine():
        return next((desktop.get_child_at_index(i)
                     for i in range(desktop.get_child_count())
                     if desktop.get_child_at_index(i).get_process_id() == announced["pid"]),
                    None)

    timing.append(settle("app_on_the_bus", lambda: _mine() is not None, timeout=30,
                         giveup=lambda: app.poll() is not None))
    mine = _mine()
    if mine is None:
        print(json.dumps({"drawn_button": None, "timing": timing,
                          "aborted": "the fixture never appeared on the accessibility bus"}),
              flush=True)
        app.terminate()
        return 0

    real, drawn = _find(mine, "Apply"), _find(mine, "Recalculate")
    bound = _find(mine, "bound entry")

    def _changed(collected):
        return [e for e in collected if e.get("event") == "bound_changed"]

    report = {
        "real_button": {"actions": _actions(real)},
        "drawn_button": {"actions": _actions(drawn)},
        "bound_entry": {"interfaces": sorted(bound.get_interfaces())},
    }
    report["real_button"]["do_action"] = _do(real)
    report["real_button"]["events"] = drain(
        "real_button_applied", until=lambda out: any(e.get("event") == "applied" for e in out))
    report["drawn_button"]["do_action"] = _do(drawn)
    # No `until`: the claim is that an owner-drawn control produces nothing,
    # and a wait for nothing is just the wait.
    report["drawn_button"]["events"] = drain("drawn_button_quiet", seconds=NEGATIVE_DRAIN_S)

    report["bound_entry"]["before"] = _text(bound)
    try:
        report["bound_entry"]["set_text"] = bool(
            Atspi.EditableText.set_text_contents(bound, "written-by-atspi"))
    except Exception as exc:
        report["bound_entry"]["set_text"] = f"<{type(exc).__name__}>"
    # Both halves of the write, because both are asserted: the clear and the
    # insert, in that order, with the written value last. Waiting for the
    # second is what stops a slow pipe reading as D21's split.
    report["bound_entry"]["events"] = drain(
        "bound_entry_write",
        until=lambda out: len(_changed(out)) >= 2
        and _changed(out)[-1].get("text") == "written-by-atspi",
    )
    # The toolkit has confirmed the write before this is read, rather than
    # this being read at whatever the drain window happened to end at.
    report["bound_entry"]["after"] = _text(bound)
    report["timing"] = timing

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
