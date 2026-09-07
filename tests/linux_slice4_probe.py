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

Guessing would be modelling.

**Handles are enumeration-scoped, and this file has to respect that.**
`enumerate_process` calls `tree._reset()`, so every handle minted by an
earlier enumeration dies. An earlier draft of this probe re-enumerated to
look a value up and then reused a handle from before, which raised -- and
correctly. So each phase below enumerates once and uses only handles from
that pass, and `_snap` exists to make that explicit rather than accidental.

Prints one JSON line.
"""

import json
import os
import subprocess
import sys
import time


def _snap(pid):
    """One enumeration, and every node from it. Handles minted here are
    valid until the next call and no longer."""
    from ghostdriver.backends import current

    found = []
    for tree in current().enumerate_process(pid):
        stack = [tree]
        while stack:
            node = stack.pop()
            found.append(node)
            stack.extend(node.children)
    return found


def _pick(nodes, class_names, name_contains=None):
    for node in nodes:
        if node.class_name in class_names and (
            name_contains is None or name_contains in (node.text or "")
        ):
            return node
    return None


def _describe(node, *, value=False):
    """`node.text` is the accessible *name*, not the contents.

    For an entry the name is its label -- "bound entry" -- and stays that
    whatever is typed into it. Reading what a control actually holds is
    `read_window_text`, which is a different call through a different
    interface, and confusing the two makes a write look like it did nothing.
    """
    if node is None:
        return None
    out = {
        "handle": node.handle, "class_name": node.class_name,
        "name": node.text, "enabled": node.enabled,
    }
    if value:
        from ghostdriver.backends import current

        out["value"] = current().read_window_text(node.handle)
    return out


def _roles(nodes):
    seen = {}
    for node in nodes:
        seen[node.class_name] = seen.get(node.class_name, 0) + 1
    return seen


def main():
    app = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp_gtk",
         "--modal-after", "25000", "--quit-after", "90000"],
        stdout=subprocess.PIPE, text=True,
        env=dict(os.environ, GDK_BACKEND="x11"),
    )
    announced = json.loads(app.stdout.readline())
    pid = announced["pid"]
    time.sleep(3)

    from ghostdriver.actuate import Actuator
    from ghostdriver.backends import current
    from ghostdriver.backends.linux import input as linux_input

    backend = current()
    report = {"pid": pid, "platform": backend.platform}

    # --- phase 1: one enumeration, everything that needs a live handle ----
    nodes = _snap(pid)
    report["roles"] = _roles(nodes)
    button = _pick(nodes, ("push button",), "Apply")
    entry = _pick(nodes, ("text", "entry"), "bound entry")
    report["button"] = _describe(button)
    report["entry"] = _describe(entry, value=True)

    if button is not None:
        report["button_actions"] = linux_input.action_names(button.handle)
        # D#10 measured this raising. Recorded rather than assumed, because
        # tier 4 will need focus from somewhere and this is the route that
        # does not provide it.
        report["focus_via_component"] = linux_input.focus_via_component(button.handle)

    drawn = _pick(nodes, ("push button", "drawing area"), "Recalculate")
    report["drawn"] = _describe(drawn)
    if drawn is not None:
        report["drawn_actions"] = linux_input.action_names(drawn.handle)
        report["drawn_act_returned"] = linux_input.act_via_action(drawn.handle)

    # --- what the ladders offer, before anything runs --------------------
    if button is not None and entry is not None:
        report["ladders"] = {
            "click": len(backend.verbs.click(button.handle)),
            "right_click": len(backend.verbs.click(button.handle, button="right")),
            "click_with_modifier": len(
                backend.verbs.click(button.handle, modifiers=("ctrl",))
            ),
            "set_text": len(backend.verbs.set_text(entry.handle, "x")),
            "send_keys": len(backend.verbs.send_keys(entry.handle, ["a"])),
        }

    # --- tier 1 acting, through the neutral actuator ---------------------
    if entry is not None:
        actuator = Actuator(observe=lambda: backend.snapshot(pid))
        result = actuator.perform(
            backend.verbs.set_text(entry.handle, "slice4-wrote-this")
        )
        report["set_text_result"] = {
            "ok": result.ok,
            "tier_used": result.tier_used,
            "tiers_attempted": result.tiers_attempted,
            "error": result.error,
        }

        # An empty ladder is a result, not an exception (D10).
        empty = actuator.perform(backend.verbs.send_keys(entry.handle, ["a"]))
        report["send_keys_result"] = {"ok": empty.ok, "error": empty.error}

        report["before_modal_blocking_ancestor"] = backend.blocking_ancestor(
            entry.handle
        )

    # --- phase 2: re-enumerate to read the write back --------------------
    time.sleep(0.6)
    nodes = _snap(pid)
    report["entry_after"] = _describe(
        _pick(nodes, ("text", "entry"), "bound entry"), value=True)
    # The mirror label proves the *binding* heard it. A write that only
    # changed the display would leave this stale -- that is D21 on Windows,
    # and per D#10 it does not happen here.
    report["mirror_saw_it"] = _pick(nodes, ("label",), "slice4-wrote-this") is not None

    # --- phase 3: the unmeasured question --------------------------------
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if any(w.modal for w in backend.top_level_state(pid)):
            break
        time.sleep(0.5)
    time.sleep(1.0)

    held = any(w.modal for w in backend.top_level_state(pid))
    report["modal_is_up"] = held
    if held:
        nodes = _snap(pid)
        entry = _pick(nodes, ("text", "entry"), "bound entry")
        during = {"entry_found": entry is not None}
        if entry is not None:
            during["blocking_ancestor"] = backend.blocking_ancestor(entry.handle)
            during["unblocked_holds"] = backend.verbs.unblocked(entry.handle).holds()
            # Straight at the tier-1 call, deliberately bypassing the
            # precondition: the question is what the *toolkit* does while
            # held, not what our own guard does.
            during["set_text_returned"] = linux_input.set_text_via_editable(
                entry.handle, "written-while-held"
            )
            time.sleep(0.6)
            nodes = _snap(pid)
            during["entry_after"] = _describe(
                _pick(nodes, ("text", "entry"), "bound entry"), value=True
            )
            during["mirror_saw_it"] = (
                _pick(nodes, ("label",), "written-while-held") is not None
            )
        report["during_modal"] = during

    print(json.dumps(report), flush=True)
    app.terminate()
    app.wait(timeout=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
