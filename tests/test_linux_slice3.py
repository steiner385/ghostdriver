"""Slice 3 of #40 through the contract, not through the measurement.

`test_linux_modality.py` proves what the *signals* are: the modal declares
itself, the owner never goes insensitive, and the information is in the
window manager rather than the accessibility tree (D#12). This proves the
different and later thing -- that `backends.current()` answers those
questions for real when called the way the tool layer calls them.

The gap between those two is where a slice actually fails. Every signal can
be present and correct while a contract function reports an owner in the
wrong identifier space, or binds a name to the wrong module, and the
measurement suite cannot see any of it because it never calls the contract.

The identifier crossing is the specific hazard here, and it is why
`test_blocking_ancestor_answers_for_a_handle_from_the_tree` exists. Linux has
two spaces -- minted AT-SPI handles for the tree, X window ids for everything
the window manager knows -- and `blocking_ancestor` takes one and answers in
the other. Get it wrong and it returns None forever, which reads exactly like
a healthy application (D#12).
"""

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys

import pytest

from tests.conftest import on_linux
from tests.linux_nested_shell import NEEDED as NESTED_NEEDED
from tests.linux_nested_shell import inner, nested_env
from tests.linux_probe_support import collect, describe

pytestmark = [on_linux, pytest.mark.slow]

NEEDED = NESTED_NEEDED
BUS_LAUNCHER = "/usr/libexec/at-spi-bus-launcher"


@pytest.fixture(scope="module")
def slice3():
    missing = [t for t in NEEDED if shutil.which(t) is None]
    if not os.path.exists(BUS_LAUNCHER):
        missing.append(BUS_LAUNCHER)
    if missing:
        pytest.skip("slice 3 needs: " + ", ".join(missing))

    # A headless gnome-shell's Xwayland, not Xvfb + `gnome-shell --x11`,
    # which GNOME 50 removed (#217). The shell activates its own
    # accessibility bus on the private session bus.
    with nested_env() as env:
        probe = subprocess.Popen(
            ["dbus-run-session", "--", "bash", "-c",
             inner(f"{sys.executable} -m tests.linux_slice3_probe")],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            start_new_session=True, env=env,
        )
        # The deadline is raised with the probe's modal budget (#163): the
        # fixture now waits 30s before raising its modal rather than 9s, so the
        # old 220s left less headroom than it looks like it does.
        #
        # `collect` reads on a thread against a real deadline and keeps the
        # streamed timing records, so a probe that stalls still leaves a trace
        # and a probe that goes silent does not block the run (#163). The loop
        # this replaces checked its deadline inside `for out in probe.stdout:`,
        # which only expires when a line arrives.
        try:
            line, trace = collect(probe.stdout, '"during"', 260)
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(probe.pid), signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired):
                probe.wait(timeout=20)

    if line is None:
        pytest.skip("the slice 3 probe produced no report. What it did get through:\n"
                    + describe(trace))
    report = json.loads(line)

    # #163. Four of the tests below read `before` -- the state of the
    # application while nothing is holding it -- and the fixture raises its
    # modal on an absolute timer from its own start. If the probe's setup
    # overran that timer then `before` was sampled with the modal already up,
    # and all four fail saying "a modal before one was raised". They are
    # describing the harness, not the backend.
    #
    # Skipped rather than failed, on the precedent `test_linux_restore.py`
    # sets: a harness that could not reach the state a test is about has
    # measured nothing, and nothing is not a defect. Skipped *loudly*, with
    # the overrun in the message, because the other way this goes wrong is a
    # budget that quietly stops being met and takes the coverage with it.
    budget = next((t for t in report.get("timing", []) if "budget" in t), None)
    if budget is not None and not budget["ok"]:
        pytest.skip(
            "the slice 3 probe lost its race with the fixture's modal timer, so the "
            "'before' state it recorded is not a state with no modal in it:\n"
            + describe(report["timing"])
        )
    return report


def _modal(report, when):
    return next((w for w in report[when]["state"] if w["modal"]), None)


def _why(report):
    """The probe's clock, appended to the assertions that can be starved by a
    loaded box rather than by a real defect (#163)."""
    return "\nprobe timings:\n" + describe(report.get("timing"))


def test_the_backend_that_answered_is_the_linux_one(slice3):
    """Cheap, and it catches the whole class of mistake where a probe runs
    against the wrong backend and every other assertion here is vacuous."""
    assert slice3["platform"] == "linux"


def test_top_level_state_reports_the_modal_and_who_it_holds(slice3):
    """The two facts the policy needs, both from the window manager:
    `_NET_WM_STATE_MODAL` and `WM_TRANSIENT_FOR` (D#12)."""
    assert _modal(slice3, "before") is None, "a modal before one was raised" + _why(slice3)
    modal = _modal(slice3, "during")
    assert modal is not None, str(slice3["during"]["state"]) + _why(slice3)
    assert modal["text"] == "Confirm"
    assert modal["owner"] == slice3["announced_main"], (
        "owner must be the main window's X id -- the same space as `handle`, "
        "or `find_modal_blocks` looks it up and finds nothing" + _why(slice3)
    )


def test_nothing_is_reported_disabled_even_while_held(slice3):
    """The finding, asserted through the contract rather than the probe.

    If this ever fails, the Windows mechanism ports after all and the
    `modal` signature added for D#12 is unnecessary. That would be worth
    knowing, so it is a test rather than a comment.
    """
    assert all(w["enabled"] for w in slice3["during"]["state"]), (
        slice3["during"]["state"]
    )


def test_the_neutral_policy_finds_the_block_from_the_declaration(slice3):
    """`find_modal_blocks` fed real backend output. The policy is neutral and
    unit-tested; this is the half that proves the backend fills it in a shape
    the policy can actually read."""
    assert slice3["before"]["blocks"]["blocks"] == [], _why(slice3)
    blocks = slice3["during"]["blocks"]["blocks"]
    assert len(blocks) == 1, str(blocks) + _why(slice3)
    assert blocks[0]["dialog"] == "Confirm"
    assert blocks[0]["blocked"] == "Ghostdriver GTK fixture"
    assert blocks[0]["describe"] == (
        "'Confirm' is holding 'Ghostdriver GTK fixture'"
    )


def test_nothing_is_reported_as_an_unexplained_block(slice3):
    """An `UnexplainedBlock` is a disabled window with no dialog to account
    for it, and nothing here is ever disabled -- so on this platform the
    category is unreachable rather than merely empty.

    Recorded because the absence is a property of the platform, not of this
    fixture: a caller that treats "no unexplained blocks" as evidence the
    application is healthy would be reading a constant.
    """
    assert slice3["before"]["blocks"]["unexplained"] == []
    assert slice3["during"]["blocks"]["unexplained"] == []


def test_blocking_ancestor_answers_for_a_handle_from_the_tree(slice3):
    """The identifier crossing, which is the part that fails silently.

    The handle passed in is a `WindowNode.handle` -- a minted AT-SPI id, the
    only identifier the tool layer has. The answer is an X window id, because
    that is what a modal *is* here. Nothing above the backend knows or needs
    to know that the two are different spaces.

    Before: None. During: the modal. A driver reading None throughout
    actuates into a held application with every state it can read saying the
    application is fine, which is exactly what D#12 warns about.
    """
    if slice3["entry"] is None:
        pytest.skip("no entry control found in the fixture tree to ask about")
    assert slice3["before"]["blocking_ancestor"] is None, _why(slice3)
    during = slice3["during"]["blocking_ancestor"]
    assert during is not None, (
        "the modal is up and the control reports nothing" + _why(slice3)
    )
    assert during == _modal(slice3, "during")["handle"], (
        "blocking_ancestor must name the modal, not the window it holds "
        "-- the Windows one returns the disabled ancestor, and here there "
        "is no such thing (D#12)"
    )


def test_snapshot_names_what_is_holding_the_target(slice3):
    """What `Actuator.observe` compares against. `blocked_by` is the field a
    caller reads to find out it should deal with a dialog first."""
    assert slice3["before"]["snapshot"]["alive"]
    assert slice3["before"]["snapshot"]["blocked_by"] == [], _why(slice3)
    assert slice3["during"]["snapshot"]["blocked_by"] == ["Confirm"], _why(slice3)
    assert set(slice3["during"]["snapshot"]["windows"].values()) == {
        "Ghostdriver GTK fixture", "Confirm",
    }, _why(slice3)


def test_surface_of_says_native_because_this_control_is_not_a_document(slice3):
    """The negative half of the web-role check, on a real native control.

    L8 (#15, D#15) measured what an embedded document reports (`document
    web`) and added it to `WEB_HOST_CLASSES`; see `test_surface.py` for the
    positive case. This fixture entry is a plain GTK control, not a
    document, so it should still answer "native" -- which is what this
    pins, now that the role it could have matched against is measured
    rather than absent.
    """
    if slice3["entry"] is None:
        pytest.skip("no entry control found in the fixture tree to ask about")
    assert slice3["before"]["surface_of"] == "native"
