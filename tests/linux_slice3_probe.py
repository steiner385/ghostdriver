"""Slice 3 through the contract, against a live target on the nested display.

The measurements said what the signals are (D#12: modality is declared, and
nothing goes disabled). This asks the different and later question: do the
*contract functions* answer for real when called the way the tool layer calls
them?

That distinction is the reason this file exists rather than more assertions
in `test_linux_modality.py`. The probe there reads AT-SPI and X directly and
compares them. This one calls `backends.current()` and nothing else, so a
wiring mistake -- a name bound to the wrong module, an owner reported in the
wrong identifier space -- shows up here and cannot show up there.

Prints one JSON line. Nothing here is imported by the test process.
"""

import json
import os
import subprocess
import sys

from tests.linux_probe_support import Budget, settle

#: When the fixture raises its modal, in milliseconds from its own start.
#:
#: #163: this was 9000, and the `before` block below has to finish inside it
#: -- three contract calls and a full `enumerate_process` tree walk. Alone
#: that fits easily; under a full suite the walk overran, the modal was
#: already up when the calm state was sampled, and the four tests that read
#: `before` failed saying "a modal before one was raised". They were right:
#: there was one. The harness had simply lost the race to a timer nothing in
#: the probe acknowledged.
#:
#: Raised to a budget the walk fits under even on a loaded box. The number on
#: its own would only be a better guess, so `before_budget` in the report
#: says how much of it was actually used -- if that margin ever goes
#: negative again the report names the overrun instead of blaming the modal.
MODAL_AFTER_MS = 30000

#: The fixture prints its announce line on a 120ms timer armed alongside the
#: modal's, so the budget the probe really has is that much shorter than
#: `MODAL_AFTER_MS`. Small, and subtracted rather than ignored because a
#: budget that is quietly optimistic is what this is replacing.
ANNOUNCE_DELAY_S = 0.12


def _state(pid):
    from ghostdriver.backends import current

    return [
        {
            "handle": w.handle,
            "text": w.text,
            "visible": w.visible,
            "enabled": w.enabled,
            "owner": w.owner,
            "modal": w.modal,
        }
        for w in current().top_level_state(pid)
    ]


def _blocks(pid):
    from ghostdriver.backends import current
    from ghostdriver.modality import find_modal_blocks

    blocks, unexplained = find_modal_blocks(current().top_level_state(pid))
    return {
        "blocks": [{"dialog": b.dialog.text, "blocked": b.blocked.text,
                    "describe": b.describe()} for b in blocks],
        "unexplained": [u.blocked.text for u in unexplained],
    }


def _snapshot(pid):
    from ghostdriver.backends import current

    got = current().snapshot(pid)
    return {
        "windows": {str(k): v for k, v in got.windows.items()},
        "blocked_by": list(got.blocked_by),
        "foreground": got.foreground,
        "alive": got.alive,
    }


def main():
    app = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp_gtk",
         "--modal-after", str(MODAL_AFTER_MS), "--quit-after", "90000"],
        stdout=subprocess.PIPE, text=True,
        env=dict(os.environ, GDK_BACKEND="x11"),
    )
    announced = json.loads(app.stdout.readline())
    pid = announced["pid"]

    from ghostdriver.backends import current

    timing = []
    # Everything from here to the end of the `before` block is racing the
    # fixture's modal timer, so the clock starts with the announce line.
    before_budget = Budget("before_budget", MODAL_AFTER_MS / 1000 - ANNOUNCE_DELAY_S)

    # Nothing below can happen once the fixture has exited, so every wait
    # stops when it does rather than serving out its limit.
    def gone():
        return app.poll() is not None

    # Was `time.sleep(3)`, a guess at how long the window takes to appear on
    # the nested display. The thing actually being waited for is the
    # application having a top-level the backend can see, so wait for that.
    timing.append(settle("app_visible", lambda: bool(_state(pid)), timeout=30, giveup=gone))

    report = {"pid": pid, "announced_main": announced["main"]}
    report["platform"] = current().platform

    report["before"] = {
        "state": _state(pid),
        "blocks": _blocks(pid),
        "snapshot": _snapshot(pid),
    }

    # `blocking_ancestor` takes a handle from the *tree*, not from
    # `top_level_state`. Asking it with a real `WindowNode.handle` is the
    # whole point: that is the identifier the tool layer has, and the
    # crossing between the two spaces is the part that can silently fail.
    trees = current().enumerate_process(pid)
    entry = None
    for tree in trees:
        stack = [tree]
        while stack:
            node = stack.pop()
            if node.class_name in ("entry", "text", "password text"):
                entry = node
                break
            stack.extend(node.children)
        if entry:
            break
    report["entry"] = None if entry is None else {
        "handle": entry.handle, "class_name": entry.class_name,
        "text": entry.text,
    }
    if entry is not None:
        report["before"]["blocking_ancestor"] = current().blocking_ancestor(entry.handle)
        report["before"]["surface_of"] = current().surface_of(entry.handle)

    # The calm state is sampled. Whether it *was* calm is now a recorded fact
    # rather than an assumption: a negative margin means the modal fired
    # while the tree walk above was still running, and every assertion about
    # `before` is then describing the overrun.
    timing.append(before_budget.record())

    # Wait for the modal, then for it to be attached to its owner. The second
    # wait was `time.sleep(1.0)` -- the owner comes from `WM_TRANSIENT_FOR`,
    # which the window manager sets shortly after the window maps, so the
    # real precondition is that the property has arrived, not that a second
    # has passed.
    timing.append(settle("modal_up", lambda: any(w["modal"] for w in _state(pid)),
                         timeout=40, giveup=gone))
    timing.append(settle(
        "modal_owned",
        lambda: any(w["modal"] and w["owner"] is not None for w in _state(pid)),
        timeout=15, giveup=gone,
    ))

    report["timing"] = timing
    report["during"] = {
        "state": _state(pid),
        "blocks": _blocks(pid),
        "snapshot": _snapshot(pid),
    }
    if entry is not None:
        # The same control, the same call. Before: nothing holding it.
        # After: the modal. If this does not move, a driver actuates into a
        # held application and D#12's warning has landed for real.
        report["during"]["blocking_ancestor"] = current().blocking_ancestor(entry.handle)

    print(json.dumps(report), flush=True)
    app.terminate()
    app.wait(timeout=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
