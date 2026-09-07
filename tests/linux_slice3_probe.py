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
import time


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
         "--modal-after", "9000", "--quit-after", "70000"],
        stdout=subprocess.PIPE, text=True,
        env=dict(os.environ, GDK_BACKEND="x11"),
    )
    announced = json.loads(app.stdout.readline())
    pid = announced["pid"]
    time.sleep(3)

    from ghostdriver.backends import current

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

    # Wait for the modal.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if any(w["modal"] for w in _state(pid)):
            break
        time.sleep(0.5)
    time.sleep(1.0)

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
