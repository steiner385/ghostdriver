"""A missing accessibility bus is a result, not a dead process (#58).

`Atspi.init()` reports a bus it cannot reach through GLib's `g_error()`, and
`g_error()` is fatal by contract: it aborts with SIGTRAP. No Python
exception, no result, no server. One `list_targets` on a headless box took
the whole process down and every open session with it.

That is D10 -- "errors are results, not exceptions" -- broken in the most
extreme way the runtime allows, and it stayed invisible because the suite
that would have caught it was skipping on a bad version gate (#53).

**Run in a subprocess with the bus addresses removed.** It has to be a real
child: the failure being tested is process death, which cannot be asserted
from inside the process it kills, and a `g_error` in this interpreter would
take the test runner with it. The child's exit code is the assertion.
"""

import os
import subprocess
import sys

import pytest

from tests.conftest import on_linux

pytestmark = [on_linux, pytest.mark.slow]

#: Ask for the tree with no bus to reach, and report what came back.
#: Deliberately goes through the tool surface rather than the backend: the
#: promise is that a *caller* gets a result, and the wrapper that turns the
#: exception into one is part of what is being tested.
_PROBE = """
import json
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox

result = Toolbox(SessionManager()).list_targets()
print(json.dumps({"ok": result.get("ok"),
                  "kind": (result.get("error") or {}).get("kind"),
                  "message": (result.get("error") or {}).get("message", "")[:200]}))
"""


def _without_a_bus() -> dict:
    """The child's environment: no display, no session bus, no a11y bus."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS",
                        "AT_SPI_BUS_ADDRESS")}
    env["PYTHONPATH"] = "src"
    # Without this, GLib may try to *start* a session bus by running
    # dbus-launch, and on a box that has it the child would find a bus after
    # all -- testing nothing. Refusing autolaunch is what makes the absence
    # reliable rather than incidental.
    env["DBUS_SESSION_BUS_ADDRESS"] = "disabled:"
    return env


@pytest.fixture(scope="module")
def answered() -> dict:
    done = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True, text=True, timeout=120, env=_without_a_bus(),
    )
    if done.returncode != 0:
        pytest.fail(
            "asking for the window tree with no accessibility bus killed the "
            f"process: exit {done.returncode}"
            + (" (SIGTRAP -- this is the g_error abort #58 fixed)"
               if done.returncode in (-5, 133) else "")
            + f"\nstderr: {done.stderr[-600:]}"
        )
    line = next((x for x in done.stdout.splitlines() if x.startswith("{")), None)
    if line is None:
        pytest.fail(f"the probe printed no result. stderr: {done.stderr[-600:]}")
    import json
    return json.loads(line)


def test_the_process_survives_and_answers(answered):
    """The whole point: something came back.

    The fixture already fails on a non-zero exit, so reaching here means the
    child lived. This asserts it also *said* something -- a process that
    survives by returning nothing is not much better than one that dies.
    """
    assert answered["ok"] is False


def test_the_refusal_says_what_is_missing_and_what_to_do(answered):
    """A refusal an agent can act on, which is the point of D10.

    "not_actionable" rather than an internal error: nothing is broken, a
    service this backend depends on is not running. The message names the
    remedy, because a caller that cannot start a bus should at least be able
    to tell an operator which one is missing.
    """
    assert answered["kind"] == "not_actionable"
    message = answered["message"].lower()

    # Either missing service is a correct answer. This backend needs two --
    # the accessibility bus and the X display -- and a machine can lack
    # either independently, so pinning which one is reported first would
    # make this pass on one box and fail on the next for no real reason.
    assert ("accessibility" in message or "d-bus" in message
            or "display" in message), answered

    # What is not negotiable: the refusal names something to *do* about it.
    assert ("at-spi-bus-launcher" in message or "xvfb" in message), answered
