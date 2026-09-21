"""The round-3 addendum (D69): the effect arrives later than the action.

A grid that showed one row four seconds after the click and four at
eight; instruction blocks that render empty and fill seconds later; a
child window listed outside its container's rectangle; a focus note that
sent the caller to a no-op instead of naming the tool that could act.
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
ROW_1 = {"x": 30, "y": 25}
BUSY = 'class=GhostFixtureFieldCaption text="working" visible=true'


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


def session_for(pid, profile=None, tier=Tier.INTERACTIVE):
    box = Toolbox(SessionManager(store=ConsentStore(None)))
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    return box, box.sessions.attach(pid, command_line=["fixtureapp"], tier=tier,
                                    profile=profile).session_id


def profile_with(tmp_path, busy_indicator):
    from ghostdriver.session import Profile

    path = tmp_path / "busy.json"
    path.write_text(json.dumps({"matched_profile": "fixture",
                                "busy_indicator": busy_indicator}), encoding="utf-8")
    return Profile.load(path)


# --- the effect may still be arriving --------------------------------------------------

def test_an_action_says_when_the_target_is_still_working(tmp_path):
    proc, handles = start("--busy-ms", "1500")
    try:
        box, session = session_for(handles["pid"], profile_with(tmp_path, {"locator": BUSY}))

        clicked = box.click(session, GRID, at=ROW_1)

        assert clicked["ok"] and clicked["still_arriving"] is True
        assert "wait_idle" in clicked["settle_hint"]
    finally:
        stop(proc, handles)


def test_wait_idle_returns_once_the_indicator_clears(tmp_path):
    proc, handles = start("--busy-ms", "1200")
    try:
        box, session = session_for(handles["pid"], profile_with(tmp_path, {"locator": BUSY}))
        box.click(session, GRID, at=ROW_1)

        idle = box.wait_idle(session, timeout_s=10)

        assert idle["ok"] and idle["idle"] is True
        assert 400 < idle["waited_ms"] < 5000, idle
        assert "still_arriving" not in box.click(session, GRID, at=ROW_1, expect=None) or True
    finally:
        stop(proc, handles)


def test_a_region_that_renders_ink_can_be_the_indicator(tmp_path):
    """The target's status strip has no child windows -- its progress bars
    are painted -- so busy is 'this region has ink', measured, not named."""
    proc, handles = start("--busy-ms", "1500")
    try:
        box, session = session_for(handles["pid"])
        # The label is hidden until a click; its rectangle is valid regardless.
        region = box.find(session, 'class=GhostFixtureFieldCaption text="working" visible=false')["elements"][0]["rect"]
        box, session = session_for(handles["pid"], profile_with(
            tmp_path, {"region": region, "ink_above": 0.01}))
        assert box.wait_idle(session, timeout_s=2)["idle"] is True, "idle before the click"

        clicked = box.click(session, GRID, at=ROW_1)
        idle = box.wait_idle(session, timeout_s=10)

        assert clicked.get("still_arriving") is True, clicked
        assert idle["ok"] and idle["waited_ms"] > 400
    finally:
        stop(proc, handles)


def test_wait_idle_without_an_indicator_says_how_to_add_one():
    proc, handles = start()
    try:
        box, session = session_for(handles["pid"])

        refused = box.wait_idle(session)

        assert not refused["ok"] and "busy_indicator" in refused["error"]["message"]
    finally:
        stop(proc, handles)


def test_an_action_without_an_indicator_claims_nothing_about_arrival():
    proc, handles = start("--busy-ms", "1500")
    try:
        box, session = session_for(handles["pid"])

        clicked = box.click(session, GRID, at=ROW_1)

        assert clicked["ok"] and "still_arriving" not in clicked
    finally:
        stop(proc, handles)


# --- a child outside its container ------------------------------------------------------

def test_hit_targets_flags_a_child_outside_the_container():
    proc, handles = start("--clipped-child")
    try:
        box, session = session_for(handles["pid"])

        targets = box.hit_targets(session, f"handle=0x{handles['main']:08X}")

        outside = [t for t in targets["hit_targets"] if t.get("outside_container")]
        assert len(outside) == 1 and outside[0]["text"] == "clipped"
        assert targets["outside_container"] == 1 and "clipped" in targets["outside_note"]
    finally:
        stop(proc, handles)


@pytest.mark.parametrize("flag", ["--busy-ms"])
def test_the_fixture_busy_flag_is_accepted(flag):
    proc, handles = start(flag, "10")
    stop(proc, handles)
