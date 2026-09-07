"""Slice 4a through the contract, plus the one question it raised.

D#10 measured that tier 1 works: `Action.DoAction` drives a real button,
does nothing at all on the owner-drawn one, and `EditableText` writes without
D21's split. This runs those through `backends.current().verbs` and the
neutral actuator, which is where a wiring mistake would show.

**And it asks something D#10 did not.** The Windows `unblocked` precondition
exists because posted messages do not respect modality -- real input to a
held application is swallowed by the system, but a posted message goes
straight to the window procedure, so a driver can drive a window the person
cannot touch and never notice.

There are no posted messages here. Tier 1 is a D-Bus call into the
application's own process, and **whether the toolkit refuses it while a modal
is up is unmeasured.** Both answers matter:

* If the call is refused, modality protects itself and `unblocked` is a
  courtesy that produces a better error.
* If the call goes through, this platform has the *same* hazard as Windows
  arriving by a completely different route, and `unblocked` is load-bearing
  -- the only thing standing between a driver and a held application.

Guessing would be modelling. Prints one JSON line.
"""

import json
import os
import subprocess
import sys
import time


def _find(pid, class_names, name_contains=None):
    from ghostdriver.backends import current

    for tree in current().enumerate_process(pid):
        stack = [tree]
        while stack:
            node = stack.pop()
            if node.class_name in class_names and (
                name_contains is None or name_contains in (node.text or "")
            ):
                return node
            stack.extend(node.children)
    return None


def _describe(node):
    return None if node is None else {
        "handle": node.handle, "class_name": node.class_name,
        "text": node.text, "enabled": node.enabled,
    }


def main():
    app = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp_gtk",
         "--modal-after", "22000", "--quit-after", "80000"],
        stdout=subprocess.PIPE, text=True,
        env=dict(os.environ, GDK_BACKEND="x11"),
    )
    announced = json.loads(app.stdout.readline())
    pid = announced["pid"]
    time.sleep(3)

    from ghostdriver.actuate import Actuator
    from ghostdriver.backends import current

    backend = current()
    report = {"pid": pid, "platform": backend.platform}

    button = _find(pid, ("push button",), "Recalculate")
    entry = _find(pid, ("text", "entry"), "bound entry")
    report["button"] = _describe(button)
    report["entry"] = _describe(entry)

    # --- what the ladders offer, before anything is run ------------------
    report["ladders"] = {
        "click": len(backend.verbs.click(button.handle)) if button else None,
        "right_click": (
            len(backend.verbs.click(button.handle, button="right"))
            if button else None
        ),
        "set_text": (
            len(backend.verbs.set_text(entry.handle, "x")) if entry else None
        ),
        "send_keys": (
            len(backend.verbs.send_keys(entry.handle, ["a"])) if entry else None
        ),
        "type_text_element": None,
    }

    # --- tier 1 actually acting ------------------------------------------
    from ghostdriver.backends.linux import input as linux_input

    if button is not None:
        report["button_actions"] = linux_input.action_names(button.handle)
    drawn = _find(pid, ("push button", "drawing area"), "Recalculate")
    report["drawn_probe"] = _describe(drawn)

    if entry is not None:
        actuator = Actuator(observe=lambda: backend.snapshot(pid))
        result = actuator.perform(backend.verbs.set_text(entry.handle, "slice4-wrote-this"))
        report["set_text_result"] = {
            "ok": result.ok,
            "tier_used": result.tier_used,
            "tiers_attempted": result.tiers_attempted,
            "error": result.error,
        }
        time.sleep(0.5)
        after = _find(pid, ("text", "entry"), "bound entry")
        report["entry_after"] = _describe(after)
        # The mirror label is what proves the binding heard it -- a write
        # that only changed the display would leave this stale (D21).
        mirror = _find(pid, ("label",), "slice4-wrote-this")
        report["mirror_saw_it"] = mirror is not None

    # --- an empty ladder is a result, not an exception (D10) -------------
    if entry is not None:
        actuator = Actuator(observe=lambda: backend.snapshot(pid))
        empty = actuator.perform(backend.verbs.send_keys(entry.handle, ["a"]))
        report["send_keys_result"] = {
            "ok": empty.ok,
            "error": empty.error,
        }

    # --- the unmeasured question: does tier 1 respect modality? ----------
    report["before_modal"] = {
        "blocking_ancestor": (
            backend.blocking_ancestor(entry.handle) if entry else None
        ),
    }
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if any(w.modal for w in backend.top_level_state(pid)):
            break
        time.sleep(0.5)
    time.sleep(1.0)

    held = any(w.modal for w in backend.top_level_state(pid))
    report["modal_is_up"] = held
    if held and entry is not None:
        report["during_modal"] = {
            "blocking_ancestor": backend.blocking_ancestor(entry.handle),
            "unblocked_holds": backend.verbs.unblocked(entry.handle).holds(),
        }
        # Straight at the tier-1 call, deliberately bypassing the
        # precondition: the question is what the *toolkit* does, not what
        # our own guard does.
        wrote = linux_input.set_text_via_editable(entry.handle, "written-while-held")
        time.sleep(0.5)
        after = _find(pid, ("text", "entry"), "bound entry")
        report["during_modal"]["set_text_returned"] = wrote
        report["during_modal"]["entry_after"] = _describe(after)
        report["during_modal"]["mirror_saw_it"] = (
            _find(pid, ("label",), "written-while-held") is not None
        )

    print(json.dumps(report), flush=True)
    app.terminate()
    app.wait(timeout=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
