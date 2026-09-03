"""The launch path, and driving a hidden-desktop session through the tools.

These prove the wiring: a session opened by launch_isolated routes every
backend call onto the desktop-bound thread, so the ordinary tools --
describe, read, click, capture -- work against a target that is invisible
to the operator's desktop. No opt-in flag: a hidden-desktop target cannot
disturb anyone, which is the point.
"""

import ctypes
import sys
from ctypes import wintypes

import pytest

from tests.conftest import on_windows

pytestmark = on_windows

user32 = ctypes.WinDLL("user32", use_last_error=True)

COMMAND = [sys.executable, "-u", "-m", "tests.fixtureapp", "--onscreen"]


@pytest.fixture
def box():
    from ghostdriver.session import SessionManager
    from ghostdriver.tools import Toolbox

    tb = Toolbox(SessionManager())
    yield tb
    # Any session left open gets its desktop torn down.
    for sid in list(tb._desktops):
        tb.release(sid)


def approved(box):
    box.sessions.record_launch_grant(COMMAND, allowed=True)


# --- the consent gate ----------------------------------------------------

def test_launching_without_approval_asks_rather_than_launches(box):
    """Launching a process is the tool's widest authority; it does not
    happen until the operator has approved the exact command."""
    result = box.launch_isolated(COMMAND, tier="read_only", announces_pid=True)

    assert not result["ok"]
    assert result["needs_consent"] is True
    assert result["command"] == COMMAND


def test_a_declined_command_is_refused(box):
    box.sessions.record_launch_grant(COMMAND, allowed=False,
                                     note="not this one")
    result = box.launch_isolated(COMMAND, tier="read_only", announces_pid=True)

    assert not result["ok"]
    assert "declined" in result["error"]["message"]


def test_approval_is_for_the_exact_command(box):
    """Consent is keyed by the command. Approving one does not approve a
    neighbour with an extra argument."""
    box.sessions.record_launch_grant(COMMAND, allowed=True)

    other = box.launch_isolated(COMMAND + ["--modal-after", "500"],
                                tier="read_only", announces_pid=True)
    assert other["needs_consent"] is True


# --- launch, drive through the ordinary tools, release -------------------

def test_a_launched_target_is_driven_through_the_normal_tools(box):
    approved(box)
    launched = box.launch_isolated(COMMAND, tier="interactive", announces_pid=True)
    assert launched["ok"], launched
    assert launched["isolation"] == "hidden_desktop"
    session = launched["session_id"]

    # describe routes enumeration onto the desktop thread and sees the tree.
    described = box.describe(session)
    assert described["ok"]
    assert described["windows"], "the tree is visible through the session"

    # A click, through the same routing, lands on the hidden desktop.
    before = box.read(session, 'class=Static text="/clicks=/"')
    clicked = box.click(
        session, 'class=GhostFixtureCommandButton text="Expand All"',
        expect={"locator": 'class=Static text="/clicks=1 last=Expand All/"'})
    assert clicked["ok"], clicked
    assert clicked["verified"] == "effect"


def test_the_launched_target_is_invisible_from_the_operators_desktop(box):
    """The structural guarantee, seen from the tool layer: nothing the
    session drives is reachable -- or stealable -- from the input desktop."""
    from ghostdriver.backends.windows.enumerate import top_level_windows

    approved(box)
    fg_before = user32.GetForegroundWindow()
    launched = box.launch_isolated(COMMAND, tier="interactive", announces_pid=True)
    pid = launched["launched_pid"]

    # From this thread (the Default desktop) the target does not exist,
    # even while the session is driving it.
    assert top_level_windows(pid) == []
    box.click(launched["session_id"],
              'class=GhostFixtureCommandButton text="Apply"')
    assert user32.GetForegroundWindow() == fg_before, "foreground never moved"


def test_capture_of_a_hidden_target_is_a_real_png(box):
    approved(box)
    launched = box.launch_isolated(COMMAND, tier="read_only", announces_pid=True)

    shot = box.capture(launched["session_id"])

    assert shot["ok"], shot
    assert shot["width"] > 0
    import base64
    assert base64.b64decode(shot["base64"])[:8] == b"\x89PNG\r\n\x1a\n"


def test_releasing_closes_the_target_and_the_desktop(box):
    import psutil

    approved(box)
    launched = box.launch_isolated(COMMAND, tier="read_only", announces_pid=True)
    pid = launched["launched_pid"]
    assert psutil.pid_exists(pid)

    box.release(launched["session_id"])
    import time
    time.sleep(0.5)
    assert not psutil.pid_exists(pid) or not psutil.Process(pid).is_running()
    assert launched["session_id"] not in box._desktops


def test_an_ordinary_session_is_unaffected_by_the_routing(box):
    """The routing seam must be transparent: a normal attached session runs
    its calls on the calling thread exactly as before. Proven here by
    reading a normally-launched fixture through a plain session."""
    import json
    import subprocess
    import time

    from ghostdriver.policy import ConsentSource

    proc = subprocess.Popen(COMMAND, stdout=subprocess.PIPE, text=True)
    handles = json.loads(proc.stdout.readline())
    time.sleep(0.4)
    try:
        box.sessions.record_grant(handles["pid"], allowed=True,
                                  source=ConsentSource.ELICITED)
        session = box.attach(handles["pid"])["session_id"]
        described = box.describe(session)
        assert described["ok"] and described["windows"]
    finally:
        import psutil
        try:
            psutil.Process(handles["pid"]).terminate()
        except psutil.Error:
            pass
        proc.terminate()
        proc.wait(timeout=5)
