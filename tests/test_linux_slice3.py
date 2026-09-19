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
import time

import pytest

from tests.conftest import on_linux

pytestmark = [on_linux, pytest.mark.slow]

DISPLAY = ":64"
NEEDED = ("Xvfb", "dbus-run-session", "gnome-shell", "xprop")
BUS_LAUNCHER = "/usr/libexec/at-spi-bus-launcher"


@pytest.fixture(scope="module")
def slice3():
    missing = [t for t in NEEDED if shutil.which(t) is None]
    if not os.path.exists(BUS_LAUNCHER):
        missing.append(BUS_LAUNCHER)
    if missing:
        pytest.skip("slice 3 needs: " + ", ".join(missing))

    server = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", "1280x800x24"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    inner = ('gnome-shell --x11 >/dev/null 2>&1 & '
             'for i in $(seq 1 30); do '
             'xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -q 0x && break; '
             'sleep 1; done; '
             f'{BUS_LAUNCHER} --launch-immediately & sleep 3; '
             f'exec {sys.executable} -m tests.linux_slice3_probe')
    probe = subprocess.Popen(
        ["dbus-run-session", "--", "bash", "-c", inner],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        start_new_session=True,
        env=dict(os.environ, DISPLAY=DISPLAY, GSETTINGS_BACKEND="memory",
                 GDK_BACKEND="x11", PYTHONPATH="src"),
    )
    line, deadline = None, time.monotonic() + 220
    try:
        for out in probe.stdout:
            if out.startswith("{") and '"during"' in out:
                line = out
                break
            if time.monotonic() > deadline:
                break
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(probe.pid), signal.SIGTERM)
        with contextlib.suppress(subprocess.TimeoutExpired):
            probe.wait(timeout=20)
        server.terminate()
        server.wait(timeout=10)

    if line is None:
        pytest.skip("the slice 3 probe produced no report")
    return json.loads(line)


def _modal(report, when):
    return next((w for w in report[when]["state"] if w["modal"]), None)


def test_the_backend_that_answered_is_the_linux_one(slice3):
    """Cheap, and it catches the whole class of mistake where a probe runs
    against the wrong backend and every other assertion here is vacuous."""
    assert slice3["platform"] == "linux"


def test_top_level_state_reports_the_modal_and_who_it_holds(slice3):
    """The two facts the policy needs, both from the window manager:
    `_NET_WM_STATE_MODAL` and `WM_TRANSIENT_FOR` (D#12)."""
    assert _modal(slice3, "before") is None, "a modal before one was raised"
    modal = _modal(slice3, "during")
    assert modal is not None, slice3["during"]["state"]
    assert modal["text"] == "Confirm"
    assert modal["owner"] == slice3["announced_main"], (
        "owner must be the main window's X id -- the same space as `handle`, "
        "or `find_modal_blocks` looks it up and finds nothing"
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
    assert slice3["before"]["blocks"]["blocks"] == []
    blocks = slice3["during"]["blocks"]["blocks"]
    assert len(blocks) == 1, blocks
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
    assert slice3["before"]["blocking_ancestor"] is None
    during = slice3["during"]["blocking_ancestor"]
    assert during is not None, "the modal is up and the control reports nothing"
    assert during == _modal(slice3, "during")["handle"], (
        "blocking_ancestor must name the modal, not the window it holds "
        "-- the Windows one returns the disabled ancestor, and here there "
        "is no such thing (D#12)"
    )


def test_snapshot_names_what_is_holding_the_target(slice3):
    """What `Actuator.observe` compares against. `blocked_by` is the field a
    caller reads to find out it should deal with a dialog first."""
    assert slice3["before"]["snapshot"]["alive"]
    assert slice3["before"]["snapshot"]["blocked_by"] == []
    assert slice3["during"]["snapshot"]["blocked_by"] == ["Confirm"]
    assert set(slice3["during"]["snapshot"]["windows"].values()) == {
        "Ghostdriver GTK fixture", "Confirm",
    }


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
