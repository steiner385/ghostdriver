"""Actuation against the fixture: this iteration's validation gate.

The gate asks two things -- that the fixture's induced failure modes are
handled, and that actuation succeeds without moving the cursor -- so both are
asserted here rather than described.

`tests/test_actuate.py` covers the ladder as policy, with the primitives
injected. Everything here needs a real target: a window that ignores semantic
messages, a field whose bound value and displayed text disagree, a modal that
holds the application, and an application that grabs the foreground.
"""

import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes

import psutil
import pytest

from tests.conftest import on_windows

pytestmark = on_windows


def start(*args):
    """The fixture process, and its announced handles."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp", *args],
        stdout=subprocess.PIPE, text=True,
    )
    announced = proc.stdout.readline()
    if not announced.startswith("{"):
        proc.terminate()
        raise RuntimeError(f"fixture did not start: {announced!r}")
    handles = json.loads(announced)
    time.sleep(0.4)  # let the child windows finish being created
    return proc, handles


def stop(proc, handles):
    # The interpreter that owns the windows is not always the one Popen
    # started: a venv launcher stub re-execs, so the fixture announces the
    # pid that actually matters and it gets terminated by handle.
    if handles["pid"] != proc.pid:
        try:
            psutil.Process(handles["pid"]).terminate()
        except psutil.Error:
            pass
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def app():
    """Function-scoped, unlike the read-only fixture tests.

    These tests click things and commit values, so each one gets a target
    whose state nothing else has touched.
    """
    proc, handles = start()
    try:
        yield handles
    finally:
        stop(proc, handles)


def find(pid, cls, text=None):
    from ghostdriver.backends.windows.enumerate import enumerate_process
    from ghostdriver.model.window import select_main_tree

    tree = select_main_tree(enumerate_process(pid))
    return [n for n in tree.walk()
            if n.class_name == cls and (text is None or n.text == text)]


def reads(hwnd):
    """A callable that re-reads a window's text, for use as a condition."""
    from ghostdriver.backends.windows.text import read_window_text

    return lambda: read_window_text(hwnd) or ""


def cursor():
    point = wintypes.POINT()
    ctypes.WinDLL("user32").GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def require_a_still_cursor():
    """Skip rather than fail when someone is using the machine.

    "The cursor did not move" can only be asserted about a cursor nobody
    else is moving, and this suite runs on a desktop with a person on it --
    a hand on the mouse would otherwise report a passing tool as failing.
    Sampling twice is enough to tell the two apart: our code either moves
    the cursor at the moment it acts or never, while a hand keeps moving.
    """
    first = cursor()
    time.sleep(0.15)
    if cursor() != first:
        pytest.skip("the cursor is being moved by hand; nothing to assert")
    return first


# --- click ---------------------------------------------------------------

def test_a_click_actuates_and_can_prove_it(app):
    """The postcondition is what turns "the message went out" into "it
    worked", and the counter is what makes that observable."""
    from ghostdriver.actuate import Actuator, Condition
    from ghostdriver.backends.windows import verbs

    button = find(app["pid"], "GhostFixtureCommandButton", "Expand All")[0]
    status = reads(app["status"])
    before = status()

    result = Actuator().perform(
        verbs.click(button.handle),
        expect_after=Condition(lambda: status() != before,
                               "the status line changed"),
    )

    assert result.ok, result.error
    assert result.postcondition_verified is True
    assert "last=Expand All" in status()


def test_the_click_falls_through_to_window_messages(app):
    """Tier 1 is offered and declines.

    The fixture publishes no Invoke pattern, which is what Profile L1 means
    -- so this asserts the ladder was actually walked rather than skipped
    straight to the tier that works.
    """
    from ghostdriver.actuate import Actuator, Condition
    from ghostdriver.backends.windows import verbs

    button = find(app["pid"], "GhostFixtureCommandButton", "Collapse All")[0]
    status = reads(app["status"])
    before = status()

    result = Actuator().perform(
        verbs.click(button.handle),
        expect_after=Condition(lambda: status() != before,
                               "the status line changed"),
    )

    assert result.tiers_attempted == [1, 3], "tier 1 was offered first"
    assert result.tier_used == 3, "and the window message is what acted"


def test_actuation_leaves_the_cursor_and_the_foreground_alone(app):
    """Half the validation gate, and the reason tier 4 is opt-in.

    A target is entitled to take the foreground itself -- the opt-in test
    below covers that -- but nothing the driver sends may cause it. This
    fixture does not grab, so any change here would be ours.
    """
    from ghostdriver.actuate import Actuator
    from ghostdriver.backends.windows import verbs
    from ghostdriver.backends.windows.winapi import foreground_window

    button = find(app["pid"], "GhostFixtureCommandButton", "Complete Task")[0]
    field = find(app["pid"], "GhostFixtureBoundEdit")[0]
    before_fg = foreground_window()
    before_cursor = require_a_still_cursor()

    Actuator().perform(verbs.click(button.handle))
    Actuator().perform(verbs.set_text(field.handle, "NO-FOCUS"))
    Actuator().perform(verbs.send_keys(field.handle, ["enter"]))
    time.sleep(0.3)

    if cursor() != before_cursor:
        require_a_still_cursor()  # skips if a hand is on it, fails if not
        pytest.fail("actuation moved the cursor")
    assert foreground_window() == before_fg


def test_two_identical_buttons_are_told_apart_by_their_ancestor(app):
    """Every page carries an "Apply" at the same offset, so a coordinate
    cannot separate them and the tree can."""
    from ghostdriver.actuate import Actuator, Condition
    from ghostdriver.backends.windows import verbs
    from ghostdriver.backends.windows.enumerate import enumerate_process
    from ghostdriver.model.locator import Locator
    from ghostdriver.model.window import select_main_tree
    from ghostdriver.resolve import resolve

    tree = select_main_tree(enumerate_process(app["pid"]))
    scoped = resolve(tree, Locator(
        text="Apply",
        visible=None,
        within=Locator(class_name="GhostFixturePage", text="Components",
                       visible=None),
    ))
    assert len(scoped) == 1, "the ancestor scopes it to one"

    status = reads(app["status"])
    before = status()
    result = Actuator().perform(
        verbs.click(scoped[0].handle),
        expect_after=Condition(lambda: status() != before,
                               "the status line changed"),
    )

    assert result.ok, result.error


# --- set_text: the question the spec left open ---------------------------

def test_typing_is_the_default_and_commits_the_bound_value(app):
    """Settles the spec's open `set_text` question.

    The typed sequence travels the toolkit's own keyboard path, so whatever
    the toolkit does on input -- here, committing to a bound field -- happens
    exactly as it would for a person.
    """
    from ghostdriver.actuate import Actuator, Condition
    from ghostdriver.backends.windows import verbs

    field = find(app["pid"], "GhostFixtureBoundEdit")[0]
    committed = reads(app["bound_mirror"])

    result = Actuator().perform(
        verbs.set_text(field.handle, "TYPED-VALUE"),
        expect_after=Condition(lambda: "TYPED-VALUE" in committed(),
                               "the bound value was committed"),
    )

    assert result.ok, result.error
    assert result.tier_used == 3
    assert committed() == "committed:TYPED-VALUE"


def test_the_fast_path_delivers_without_committing_and_gives_way(app):
    """The failure that makes typing the default, and the ladder recovering
    from it.

    `WM_SETTEXT` changes what the field displays while the application never
    sees a keystroke, so the bound value does not move. The postcondition
    asks about the committed value rather than the display, the fast path
    fails verification, and typing runs behind it -- which is the fall-
    through doing the exact job it exists for, on a real target.
    """
    from ghostdriver.actuate import Actuator, Condition
    from ghostdriver.backends.windows import verbs

    field = find(app["pid"], "GhostFixtureBoundEdit")[0]
    committed = reads(app["bound_mirror"])

    result = Actuator().perform(
        verbs.set_text(field.handle, "FASTPATH", fast_path=True),
        expect_after=Condition(lambda: "FASTPATH" in committed(),
                               "the bound value was committed"),
    )

    assert result.ok, result.error
    assert committed() == "committed:FASTPATH", "typing rescued it"


def test_reading_the_display_back_would_have_reported_a_false_pass(app):
    """Why a postcondition has to name the thing that matters.

    The same fast path, verified against the display, reports success --
    while the application still holds the old value. This is the false pass
    the design exists to prevent, and nothing but choosing the right
    expectation prevents it.
    """
    from ghostdriver.actuate import Actuator, Attempt, Condition, Tier
    from ghostdriver.backends.windows.input import set_text_by_message

    field = find(app["pid"], "GhostFixtureBoundEdit")[0]
    display = reads(field.handle)
    committed = reads(app["bound_mirror"])
    before = committed()

    result = Actuator().perform(
        [Attempt(Tier.WINDOW_MESSAGE,
                 lambda: set_text_by_message(field.handle, "DISPLAY-ONLY"))],
        expect_after=Condition(lambda: display() == "DISPLAY-ONLY",
                               "the field shows the new text"),
    )

    assert result.ok, "the weak expectation is satisfied"
    assert committed() == before, (
        "while the application still holds the old value"
    )


def test_a_field_with_nothing_bound_behind_it_is_answered_at_tier_1(app):
    """Where the ladder stops when nothing is bound behind the field.

    The bridge synthesises a Value pattern for anything derived from a
    native EDIT, so tier 1 answers -- and with nothing to commit, setting
    the display *is* setting the value. The lower rungs are never reached.
    """
    from ghostdriver.actuate import Actuator, Condition
    from ghostdriver.backends.windows import verbs

    field = find(app["pid"], "GhostFixturePlainEdit")[0]
    display = reads(field.handle)

    result = Actuator().perform(
        verbs.set_text(field.handle, "FAST"),
        expect_after=Condition(lambda: display() == "FAST",
                               "the field shows the new text"),
    )

    assert result.ok, result.error
    assert result.tiers_attempted == [1]


def test_tier_1_carries_the_same_hazard_as_the_fast_path(app):
    """The finding that makes the postcondition non-optional here.

    A bridge-synthesised Value pattern is not the toolkit's own surface: it
    writes the control's text and the keyboard path never runs, so the
    binding does not move. Measured, and asserted rather than assumed --
    the same silent split as `WM_SETTEXT`, one rung higher and not opt-in.
    """
    from ghostdriver.backends.windows.input import set_value_via_uia

    field = find(app["pid"], "GhostFixtureBoundEdit")[0]
    display = reads(field.handle)
    committed = reads(app["bound_mirror"])
    before = committed()

    assert set_value_via_uia(field.handle, "UIA-VALUE"), "tier 1 answers"
    time.sleep(0.3)

    assert display() == "UIA-VALUE", "the control shows it"
    assert committed() == before, "and the application never saw it"


def test_send_keys_reaches_the_binding_the_same_way_typing_does(app):
    """A keystroke is a keystroke: the verb with no tier 1 still commits."""
    from ghostdriver.actuate import Actuator, Condition
    from ghostdriver.backends.windows import verbs

    field = find(app["pid"], "GhostFixtureBoundEdit")[0]
    committed = reads(app["bound_mirror"])

    result = Actuator().perform(
        verbs.send_keys(field.handle, ["X", "Y"]),
        # At the caret, not appended: the field opens with the caret at the
        # start, so the characters land in front of what is already there.
        # A verb that sends keystrokes types where the control is, and a
        # caller who wants the whole value replaced wants `set_text`.
        expect_after=Condition(lambda: committed() == "committed:XYPART-0001",
                               "the typed characters were committed"),
    )

    assert result.ok, result.error


# --- induced failure: a modal mid-run (spec section 10, item 7) ----------

def test_a_modal_blocks_actuation_and_names_what_is_holding_the_app():
    """Item 7 handled.

    Two separate claims, and both matter. The precondition refuses to act,
    so nothing is attempted into a held application; and the modality
    detector says which dialog is responsible, which is what an operator
    needs in order to do anything about it.
    """
    from ghostdriver.actuate import Actuator
    from ghostdriver.backends.windows import verbs
    from ghostdriver.backends.windows.modality import top_level_state
    from ghostdriver.model.result import ErrorKind
    from ghostdriver.modality import find_modal_blocks

    proc, handles = start("--modal-after", "300")
    try:
        time.sleep(0.6)
        blocks, _ = find_modal_blocks(top_level_state(handles["pid"]))
        assert blocks, "the modal is up"
        assert blocks[0].dialog.text == "Confirm Delete Record"

        button = find(handles["pid"], "GhostFixtureCommandButton",
                      "Expand All")[0]
        status = reads(handles["status"])
        before = status()

        result = Actuator().perform(
            verbs.click(button.handle),
            expect_before=verbs.unblocked(button.handle),
        )

        assert not result.ok
        assert result.precondition_verified is False
        assert result.error["kind"] == ErrorKind.NOT_ACTIONABLE.value
        assert status() == before, "and nothing was attempted"
    finally:
        stop(proc, handles)


def test_the_control_itself_reports_enabled_while_the_shell_is_held():
    """Why the precondition walks the chain instead of asking the control.

    Measured, not assumed: with the modal up the top-level reports disabled
    and its buttons report *enabled*, because a modal disables the top-level
    and the children are only unreachable through it. A driver that asked
    the control alone would see nothing wrong.
    """
    from ghostdriver.backends.windows import winapi
    from ghostdriver.backends.windows.modality import blocking_ancestor

    proc, handles = start("--modal-after", "300")
    try:
        time.sleep(0.6)
        button = find(handles["pid"], "GhostFixtureCommandButton",
                      "Expand All")[0]

        assert winapi.user32.IsWindowEnabled(wintypes.HWND(button.handle))
        assert not winapi.user32.IsWindowEnabled(wintypes.HWND(handles["main"]))
        assert blocking_ancestor(button.handle) == handles["main"]
    finally:
        stop(proc, handles)


def test_without_the_precondition_a_posted_click_is_still_refused():
    """The control's own check, and the honest reason it is not enough.

    A posted message reaches a window procedure whether or not the
    application is held -- the system's input block never sees it. This
    fixture's button checks, as standard controls do, so the action fails
    its postcondition rather than succeeding. But *whether* a control checks
    is up to the control, so the failure a real target produces here is
    unpredictable. That is the argument for the precondition: it does not
    depend on the target being well behaved.
    """
    from ghostdriver.actuate import Actuator, Condition
    from ghostdriver.backends.windows import verbs
    from ghostdriver.model.result import ErrorKind

    proc, handles = start("--modal-after", "300")
    try:
        time.sleep(0.6)
        button = find(handles["pid"], "GhostFixtureCommandButton",
                      "Expand All")[0]
        status = reads(handles["status"])
        before = status()

        result = Actuator().perform(
            verbs.click(button.handle),
            expect_after=Condition(lambda: status() != before,
                                   "the status line changed"),
        )

        assert not result.ok
        assert result.error["kind"] == ErrorKind.POSTCONDITION_FAILED.value
        assert result.tiers_attempted == [1, 3], "every tier was spent on it"
    finally:
        stop(proc, handles)


def test_the_precondition_holds_again_once_the_modal_is_dismissed():
    """The block is a state, not a verdict on the target.

    Worth asserting because a driver that latched on the first modal it saw
    would refuse to act for the rest of a session.
    """
    from ghostdriver.actuate import Actuator, Condition
    from ghostdriver.backends.windows import verbs
    from ghostdriver.backends.windows.input import click as post_click

    proc, handles = start("--modal-after", "300")
    try:
        time.sleep(0.6)
        button = find(handles["pid"], "GhostFixtureCommandButton",
                      "Expand All")[0]
        assert not verbs.unblocked(button.handle).holds()

        post_click(handles["modal"])  # the fixture dismisses on a click
        time.sleep(0.3)
        assert verbs.unblocked(button.handle).holds()

        status = reads(handles["status"])
        before = status()
        result = Actuator().perform(
            verbs.click(button.handle),
            expect_before=verbs.unblocked(button.handle),
            expect_after=Condition(lambda: status() != before,
                                   "the status line changed"),
        )
        assert result.ok, result.error
    finally:
        stop(proc, handles)


# --- induced failure: the target grabs the foreground (item 5) -----------

@pytest.mark.skipif(
    os.environ.get("GHOSTDRIVER_ALLOW_FOCUS_TESTS") != "1",
    reason=(
        "the target pulls itself frontmost, so it is opt-in: set "
        "GHOSTDRIVER_ALLOW_FOCUS_TESTS=1 to run it. Everything else in this "
        "suite leaves the desktop alone."
    ),
)
def test_a_target_that_grabs_the_foreground_is_detected_not_caused():
    """Item 5 handled, and the distinction that makes it handleable.

    The fixture pulls itself frontmost 200ms *after* being clicked, which is
    behaviour a driver cannot prevent -- the target is entitled to do it.
    What a driver can do is know it happened, so an operator is told their
    desktop was disturbed by the target rather than left to assume the tool
    did it. The preceding tests establish the other half: actuation by
    itself never touches the foreground.
    """
    from ghostdriver.actuate import Actuator, Condition
    from ghostdriver.backends.windows import verbs
    from ghostdriver.backends.windows.winapi import foreground_window

    proc, handles = start("--onscreen", "--grab-foreground-after", "200")
    try:
        before_fg = foreground_window()
        before_cursor = cursor()
        button = find(handles["pid"], "GhostFixtureCommandButton",
                      "Expand All")[0]
        status = reads(handles["status"])
        before = status()

        result = Actuator().perform(
            verbs.click(button.handle),
            expect_after=Condition(lambda: status() != before,
                                   "the status line changed"),
        )
        assert result.ok, result.error

        time.sleep(0.6)  # past the grab
        assert foreground_window() != before_fg, "the target took the front"
        assert cursor() == before_cursor, "and not by anything we sent"
    finally:
        stop(proc, handles)
        time.sleep(0.2)
