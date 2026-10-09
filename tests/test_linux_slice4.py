"""Slice 4a of #40: tier 1 acting, and the rungs that do not exist.

D#10 measured the primitives -- `Action.DoAction` drives a real button and
finds nothing behind the owner-drawn one, `EditableText` writes without D21's
split. This runs them through `backends.current().verbs` and the neutral
actuator, which is where a wiring mistake shows and a probe cannot.

It also settles a question D#10 did not ask, and the answer is the one that
needed a guard: **a tier 1 write reaches a modally-held application.**
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
from tests.linux_probe_support import collect

pytestmark = [on_linux, pytest.mark.slow]

NEEDED = NESTED_NEEDED
BUS_LAUNCHER = "/usr/libexec/at-spi-bus-launcher"


@pytest.fixture(scope="module")
def slice4():
    missing = [t for t in NEEDED if shutil.which(t) is None]
    if not os.path.exists(BUS_LAUNCHER):
        missing.append(BUS_LAUNCHER)
    if missing:
        pytest.skip("slice 4 needs: " + ", ".join(missing))

    # A headless gnome-shell's Xwayland, not Xvfb + `gnome-shell --x11`,
    # which GNOME 50 removed (#217). The shell activates its own
    # accessibility bus on the private session bus.
    with nested_env() as env:
        probe = subprocess.Popen(
            ["dbus-run-session", "--", "bash", "-c",
             inner(f"{sys.executable} -m tests.linux_slice4_probe")],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            start_new_session=True, env=env,
        )
        try:
            # A real deadline (collect): the old loop only checked the clock
            # when a line arrived, so a silent probe hung the suite.
            line, _trace = collect(probe.stdout, '"ladders"', 280)
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(probe.pid), signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired):
                probe.wait(timeout=20)

    if line is None:
        pytest.skip("the slice 4 probe produced no report")
    return json.loads(line)


def test_a_real_button_offers_an_action_and_the_drawn_one_does_not(slice4):
    """D#10 through the contract. The negative is the sharper half: it is not
    that the action fails on the owner-drawn control, it is that there is no
    Action interface behind it at all. A role does not imply an
    implementation -- the fixture gives that `DrawingArea` an accessible
    role of *button*, and it enumerates as `push button` while offering
    nothing to call."""
    assert slice4["button_actions"] == ["click"]
    assert slice4["drawn_actions"] == []
    assert slice4["drawn_act_returned"] is False


def test_the_accessibility_api_will_not_focus_a_control(slice4):
    """`Component.grab_focus` raises (D#10), so this reports False.

    Asserted rather than left as a comment because its absence is
    load-bearing for whoever builds tier 4: that rung needs the target
    focused (D#11), and focus therefore has to come from the window manager
    and keyboard navigation. Anything that starts by assuming the easy route
    exists should fail here first.
    """
    assert slice4["focus_via_component"] is False


def test_the_ladders_are_one_rung_or_empty(slice4):
    """The shape D#11 forced. Tier 3 does not exist on GTK4/X11 and tier 4
    has no isolation to run inside until slice 5b, so a verb either has its
    tier 1 route or it has nothing.

    The zeros are the interesting entries. A right click or a held modifier
    falls to tier 3 on Windows, which posts a real button pair and so knows
    which button and which modifiers. An AT-SPI action takes an index and
    nothing else, and offering tier 1 anyway would perform a *left* click
    and report it as a successful right one.
    """
    assert slice4["ladders"] == {
        "click": 1,
        "right_click": 0,
        "click_with_modifier": 0,
        "set_text": 1,
        "send_keys": 0,
    }


def test_an_empty_ladder_is_a_result_and_not_an_exception(slice4):
    """Errors are results that explain themselves (D10), and that has to hold
    for a verb no tier implements.

    The distinction against a rung that merely declines matters: a decline
    reports "tried and failed", which invites a retry. `TIER_EXHAUSTED` says
    nothing permitted implements this at all, which is the true statement and
    the one that stops a retry loop (D53).
    """
    result = slice4["send_keys_result"]
    assert result["ok"] is False
    assert result["error"]["kind"] == "tier_exhausted"
    assert "offers []" in result["error"]["message"]


def test_set_text_runs_at_tier_one_through_the_neutral_actuator(slice4):
    """The wiring, end to end. Tier 1 is the *preferred* write path here,
    which inverts the Windows conclusion on D#10's measurement: there a
    programmatic write splits display from bound value (D21), here it goes
    through `GtkEditable` and the binding sees it."""
    result = slice4["set_text_result"]
    assert result["ok"] is True
    assert result["tier_used"] == 1
    assert result["tiers_attempted"] == [1]


def test_the_binding_hears_the_write_and_hears_an_empty_value_first(slice4):
    """Two facts in one assertion, because they arrive together.

    The write reaches the toolkit's own `changed` signal, which is what a GTK
    binding listens to -- so there is no D21 split here.

    And `set_text_contents` clears before it inserts, so `changed` fires
    **twice** and the first carries an empty value nobody wrote. Harmless
    against a mirror; not harmless against a field that rejects empty or runs
    a lookup per change. D#10 pinned it on the raw call; this pins it through
    the contract, because it is not something the backend can hide.
    """
    events = slice4["events_after_write"]
    assert [e["text"] for e in events] == ["", "slice4-wrote-this"], events


def test_a_tier_one_write_reaches_a_modally_held_application(slice4):
    """**The finding.** The same hazard as Windows, by a different route.

    There, `unblocked` exists because a posted message bypasses the modal
    loop: real input to a held application is swallowed by the system, but a
    posted message goes straight to the window procedure. There are no
    posted messages here -- tier 1 is a D-Bus call into the application's own
    process -- so whether the toolkit refuses it while held was an open
    question with two very different answers.

    It does not refuse. The call returns true and the binding emits its
    `changed` signal with the written value, while a modal holds the window.

    So `unblocked` is **load-bearing on this platform**, not a courtesy that
    produces a better error: it is the only thing standing between a driver
    and a held application. And it can only do that job because
    `blocking_ancestor` looks for something *modal transient-for* the frame
    rather than for a disabled ancestor -- there is never a disabled one
    (D#12).
    """
    if not slice4.get("modal_is_up"):
        pytest.skip("the modal never came up, so there is nothing to hold the "
                    "application with")
    during = slice4["during_modal"]
    assert during["blocking_ancestor"] is not None, (
        "nothing reported as holding the application while a modal is up"
    )
    assert during["unblocked_holds"] is False, (
        "the precondition did not notice the modal"
    )
    assert during["set_text_returned"] is True, (
        "if this ever becomes False the toolkit started refusing held writes, "
        "and `unblocked` stops being the only guard -- worth knowing"
    )
    assert [e["text"] for e in during["events"]] == ["", "written-while-held"], (
        during["events"]
    )


def test_a_written_value_cannot_be_read_back_and_that_blocks_verification(slice4):
    """A gap this slice inherits, asserted so it is visible rather than
    rediscovered.

    `read_window_text` answers **None** for the entry both before and after a
    successful write. Not a failure: D#34b withholds by class, because
    nothing on this platform distinguishes a plain entry from a password
    field, so the policy declines to disclose either.

    The consequence for acting is that a write's *effect* cannot be confirmed
    through the contract at all -- this suite has to read the fixture's own
    `changed` events instead, which a real caller does not have. Issue #43 is
    the fix (a `disclose=True` opt-in through the contract), and this test is
    why it blocks more than reading.
    """
    assert slice4["entry"]["value"] is None
    assert slice4["entry_after"]["value"] is None
