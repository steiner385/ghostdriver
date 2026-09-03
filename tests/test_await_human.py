"""Handing a step to a person, and knowing when they have done it.

Two things are being asserted. That the wait resumes on something observed
rather than something claimed -- and that the boundary holds: a field which
hides its contents is never typed into, in either direction, by anything
here.
"""

import ctypes
import json
import subprocess
import sys
import threading
import time
from ctypes import wintypes

import psutil
import pytest

from tests.conftest import on_windows

pytestmark = on_windows


@pytest.fixture
def app():
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp"],
        stdout=subprocess.PIPE, text=True,
    )
    handles = json.loads(proc.stdout.readline())
    time.sleep(0.4)
    try:
        yield handles
    finally:
        if handles["pid"] != proc.pid:
            try:
                psutil.Process(handles["pid"]).terminate()
            except psutil.Error:
                pass
        proc.terminate()
        proc.wait(timeout=5)


@pytest.fixture
def box():
    from ghostdriver.session import SessionManager
    from ghostdriver.tools import Toolbox

    return Toolbox(SessionManager())


def read_only(box, pid):
    """Deliberately the lowest tier: asking a person is not actuation."""
    from ghostdriver.policy import ConsentSource, Tier

    box.sessions.record_grant(pid, allowed=True,
                              source=ConsentSource.ELICITED)
    return box.sessions.attach(pid, command_line=["fixtureapp"],
                                tier=Tier.READ_ONLY).session_id


def later(seconds, action):
    """Stand in for the person, doing the thing after a moment."""
    timer = threading.Timer(seconds, action)
    timer.daemon = True
    timer.start()
    return timer


def set_text(hwnd, text):
    user32 = ctypes.WinDLL("user32")
    user32.SetWindowTextW(wintypes.HWND(hwnd), text)


# --- the wait ------------------------------------------------------------

def test_it_resumes_when_the_application_shows_the_step_done(box, app):
    """The whole value over asking in chat: a reply saying "done" is a
    claim, and this is an observation."""
    session = read_only(box, app["pid"])
    later(0.6, lambda: set_text(app["status"], "clicks=0 last=SIGNED IN"))

    result = box.await_human(
        session, "Please sign in.",
        until={"locator": 'class=Static text="clicks=0 last=SIGNED IN"'},
        timeout_s=8,
    )

    assert result["ok"], result.get("error")
    assert result["verified"] is True
    assert result["waited_ms"] >= 400, "it actually waited"


def test_waiting_for_something_to_go_away_counts_too(box, app):
    """A sign-in dialog closing is how you know somebody signed in."""
    session = read_only(box, app["pid"])
    later(0.6, lambda: set_text(app["status"], "gone now"))

    result = box.await_human(
        session, "Close the sign-in box.",
        until={"locator": 'class=Static text="/clicks=/"', "absent": True},
        timeout_s=8,
    )

    assert result["ok"] and result["verified"]


def test_a_person_who_never_does_it_is_reported_as_a_timeout(box, app):
    """A person may be away from the machine, and a tool that waited
    indefinitely would take the session with them."""
    session = read_only(box, app["pid"])

    result = box.await_human(
        session, "Do something that will not happen.",
        until={"locator": 'class=Static text="never going to appear"'},
        timeout_s=1.0,
    )

    assert not result["ok"]
    assert result["error"]["kind"] == "timeout"
    assert result["verified"] is False
    assert "do not attempt the step yourself" in result["error"]["message"]


def test_without_a_condition_it_claims_nothing(box, app):
    """"I asked" and "it happened" are as different here as everywhere else
    in this tool, so the result says which one it has."""
    session = read_only(box, app["pid"])

    result = box.await_human(session, "Have a think about it.")

    assert result["ok"]
    assert result["verified"] is False
    assert "nothing was checked against the target" in result["note"]


def test_an_empty_ask_is_refused(box, app):
    """It is relayed as written, so an empty ask reaches the person as an
    empty ask."""
    session = read_only(box, app["pid"])

    result = box.await_human(session, "   ")

    assert not result["ok"]
    assert "say what the person needs to do" in result["error"]["message"]


def test_a_mistyped_condition_says_so_rather_than_timing_out(box, app):
    """Otherwise it waits the full timeout and reports that the person
    never did it, which is a lie about them."""
    session = read_only(box, app["pid"])

    result = box.await_human(
        session, "Sign in.",
        until={"locator": "class=Static text=unquoted regex here"},
        timeout_s=30,
    )

    assert not result["ok"]
    assert "until is unusable" in result["error"]["message"]
    assert result["error"]["kind"] != "timeout"


def test_the_ask_comes_back_exactly_as_written(box, app):
    """It is relayed to a person, and a server that paraphrased it would be
    putting words in the agent's mouth and the operator's ear."""
    session = read_only(box, app["pid"])
    ask = "Type the password for account SVC-7 and press Tab. Do not tell me."

    result = box.await_human(session, ask)

    assert result["asked"] == ask


# --- the boundary --------------------------------------------------------

def test_a_password_field_cannot_be_read(box, app):
    """Measured, not assumed: the system refuses a cross-process read."""
    session = read_only(box, app["pid"])

    values = box.read(session, "class=Edit")["values"]
    protected = [v for v in values if v.get("protected")]

    assert protected, "the password field is among them"
    assert protected[0]["text"] is None


def test_an_unreadable_password_field_is_not_reported_as_unresponsive(box, app):
    """The misdiagnosis this replaced.

    An unanswered read used to mean one thing: a control that has stopped
    pumping messages. A password field answers perfectly and declines to
    disclose, and a caller told the first goes off diagnosing a hang that is
    not happening.
    """
    session = read_only(box, app["pid"])

    values = box.read(session, "class=Edit")["values"]
    protected = next(v for v in values if v.get("protected"))

    assert protected["answered"] is False
    assert "hides its contents" in protected["reason"]
    assert "await_human" in protected["reason"], "and says what to do instead"


def test_nothing_will_type_into_a_protected_field(box, app):
    """The boundary, in code rather than in a caller's judgement: the value
    would have to pass through this process to be typed."""
    from ghostdriver.policy import ConsentSource, Tier

    box.sessions.record_grant(app["pid"], allowed=True,
                              source=ConsentSource.ELICITED)
    session = box.sessions.attach(app["pid"], command_line=["fixtureapp"],
                                   tier=Tier.INTERACTIVE).session_id
    locator = f'class=Edit index={_password_index(box, session, app)}'

    for attempt in (
        lambda: box.set_value(session, locator, "hunter2"),
        lambda: box.type_text(session, locator, "hunter2"),
        lambda: box.send_keys(session, locator, ["h", "i"]),
    ):
        result = attempt()
        assert not result["ok"]
        assert result["error"]["kind"] == "denied_by_policy"
        assert "await_human" in result["error"]["message"]


def test_named_keys_are_still_allowed_on_a_protected_field(box, app):
    """Tab out of a field a person has filled in, or Enter to submit it.
    Neither carries anything, and refusing them would make the handover
    useless: the agent could not continue the flow it just handed over."""
    from ghostdriver.policy import ConsentSource, Tier

    box.sessions.record_grant(app["pid"], allowed=True,
                              source=ConsentSource.ELICITED)
    session = box.sessions.attach(app["pid"], command_line=["fixtureapp"],
                                   tier=Tier.INTERACTIVE).session_id
    locator = f'class=Edit index={_password_index(box, session, app)}'

    result = box.send_keys(session, locator, ["tab"])

    assert result["ok"], result.get("error")


def test_asking_a_person_needs_no_more_than_a_read_only_session(box, app):
    """Asking is not acting. A read-only session has as much need of it as
    any other -- "please sign in so I can see the screen" is the commonest
    case there is."""
    session = read_only(box, app["pid"])

    result = box.await_human(session, "Please bring the window up.")

    assert result["ok"]


def _password_index(box, session, app):
    """Which `class=Edit` match is the protected one."""
    values = box.read(session, "class=Edit")["values"]
    for index, value in enumerate(values):
        if value.get("protected"):
            return index
    raise AssertionError("no protected field found")
