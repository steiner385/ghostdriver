"""A dialog that opens as the foreground window verifies an `expect`, even
when a main-window postcondition never sees it (#60).

A browser's file-picker is a new top-level in a helper process. Driving one,
`expect=class=#32770 visible=true` reported the *same* `postcondition_failed`
whether the picker opened or not: the main-window resolution could not see a
helper-process top-level in either case, so the postcondition carried no
signal. The only discriminator was the focus block -- `thread_active_window`
was the picker on success and the page on failure.

The fix: when the expectation is purely "a window of this class is up", a
*target-owned* window of that class becoming the foreground window counts as
the effect landing. The guardrails are what keep it honest, and they are the
point of these tests:

- the foreground window's class must match the expected class (not "any
  foreground change passes any expectation"), and
- the foreground window must belong to the target's own process tree (not an
  unrelated same-class dialog the operator happens to have focused).

The real foreground window is never stolen by a fixture (the focus guard
forbids it, and the operator is at the keyboard), so these tests feed the
corroboration a real, known window handle by substituting the backend's
`foreground_window` reader -- `class_name` and `window_pid` stay real, so the
class and process-tree guards are exercised against genuine windows.
"""

import json
import subprocess
import sys
import time

import psutil
import pytest

from ghostdriver.consent import ConsentStore
from ghostdriver.policy import ConsentSource, Tier
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox
from tests.conftest import on_windows

pytestmark = on_windows

GRID = "class=GhostFixtureDataGrid"
MODAL = "class=GhostFixtureModal"


def start(*args):
    proc = subprocess.Popen([sys.executable, "-m", "tests.fixtureapp", *args],
                            stdout=subprocess.PIPE, text=True)
    handles = json.loads(proc.stdout.readline())
    time.sleep(0.4)
    return proc, handles


def stop(proc, handles):
    if handles["pid"] != proc.pid:
        try:
            psutil.Process(handles["pid"]).terminate()
        except psutil.Error:
            pass
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def app():
    proc, handles = start()
    yield handles
    stop(proc, handles)


def session_for(pid):
    box = Toolbox(SessionManager(store=ConsentStore(None)))
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    return box, box.sessions.attach(pid, command_line=["fixtureapp"],
                                    tier=Tier.INTERACTIVE).session_id


def as_foreground(monkeypatch, hwnd: int) -> None:
    """Make the backend read `hwnd` as the foreground window. The modal
    handle exists from startup though the window is hidden, so its class and
    pid are real even before it is shown -- exactly what the corroboration
    reads."""
    from ghostdriver.backends.windows import winapi

    monkeypatch.setattr(winapi, "foreground_window", lambda: hwnd)


def test_a_target_dialog_that_is_foreground_verifies_the_expect(app, monkeypatch):
    """The modal is a separate top-level, so a bare-string `expect` (which
    resolves against the main window only) never finds it -- yet it is the
    target's own window and it is foreground, so the click is verified."""
    box, session = session_for(app["pid"])
    as_foreground(monkeypatch, app["modal"])

    result = box.click(session, GRID, at={"x": 40, "y": 25}, expect=MODAL)

    assert result["ok"] and result["verified"] == "effect", result


def test_a_foreground_of_the_wrong_class_does_not_verify(app, monkeypatch):
    """The class must match: the shell window being foreground is not the
    modal appearing, so the expectation stays unmet."""
    box, session = session_for(app["pid"])
    as_foreground(monkeypatch, app["main"])  # class GhostFixtureShell, not the modal

    result = box.click(session, GRID, at={"x": 40, "y": 25},
                       expect={"locator": MODAL, "timeout_s": 1})

    assert not result["ok"], result
    assert result["verified"] != "effect"
    assert result["error"]["kind"] in ("postcondition_failed", "not_verified", "timeout")


def test_a_same_class_dialog_in_another_process_does_not_verify(app, monkeypatch):
    """The process-tree guard: another program's window of the very same
    class, foreground, is not this target acting. Without the guard this is
    the false-green mirror of the false-red it fixes."""
    from ghostdriver.backends.windows import winapi

    other_proc, other = start()
    try:
        box, session = session_for(app["pid"])
        # other["modal"] is a real GhostFixtureModal window -- same class,
        # different process -- so only the pid guard can reject it.
        assert winapi.class_name(other["modal"]) == "GhostFixtureModal"
        as_foreground(monkeypatch, other["modal"])

        result = box.click(session, GRID, at={"x": 40, "y": 25},
                           expect={"locator": MODAL, "timeout_s": 1})

        assert not result["ok"], result
        assert result["verified"] != "effect"
    finally:
        stop(other_proc, other)


def test_a_text_constraint_is_not_vouched_for_by_the_class_alone(app, monkeypatch):
    """The corroboration only applies to "a window of this class is up". An
    expectation naming specific text is asking about a control the class of
    the foreground window cannot answer for, so it does not short-circuit."""
    box, session = session_for(app["pid"])
    as_foreground(monkeypatch, app["modal"])

    result = box.click(
        session, GRID, at={"x": 40, "y": 25},
        expect={"locator": MODAL, "text": "no field reads this", "timeout_s": 1})

    assert not result["ok"], result
    assert result["verified"] != "effect"
