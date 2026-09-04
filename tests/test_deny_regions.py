"""A denylist entry can be a place (D72).

A grid cell, a row in an owner-drawn list, a painted button: no caption,
no identity, but a rectangle inside a window the profile can name. An
actuation aimed inside one is refused, whether aimed by `at` or landing
there by a control's centre.
"""

import json
import subprocess
import sys
import time

import psutil
import pytest

from ghostdriver.consent import ConsentStore
from ghostdriver.model.result import GhostdriverError
from ghostdriver.policy import ConsentSource, Tier
from ghostdriver.session import Profile, SessionManager
from ghostdriver.tools import Toolbox
from tests.conftest import on_windows

pytestmark = on_windows

GRID = "class=GhostFixtureDataGrid"
EDIT = "class=GhostFixturePlainEdit"
#: The fixture's grid rows are 20px from y=4; row 1 is y 24..43.
ROW_1_BAND = {"left": 0, "top": 24, "right": 600, "bottom": 44}


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


def profile_with(tmp_path, *entries):
    path = tmp_path / "deny.json"
    path.write_text(json.dumps({"matched_profile": "fixture", "denylist": list(entries)}),
                    encoding="utf-8")
    return Profile.load(path)


def session_for(pid, profile):
    box = Toolbox(SessionManager(store=ConsentStore(None)))
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    return box, box.sessions.attach(pid, command_line=["fixtureapp"], tier=Tier.INTERACTIVE,
                                    profile=profile).session_id


def test_a_click_aimed_into_a_denied_row_is_refused_and_the_row_above_is_not(app, tmp_path):
    profile = profile_with(tmp_path, "*Delete*",
                           {"within": GRID, "region": ROW_1_BAND, "note": "the release row"})
    box, session = session_for(app["pid"], profile)

    refused = box.click(session, GRID, at={"x": 30, "y": 25})
    allowed = box.click(session, GRID, at={"x": 30, "y": 8},
                        expect={"locator": 'class=Static text="/last=grid row=0$/"'})

    assert not refused["ok"] and refused["error"]["kind"] == "denied_by_policy"
    assert "the release row" in refused["error"]["message"]
    assert allowed["ok"], allowed


def test_a_control_whose_centre_lies_in_a_denied_region_is_refused_for_any_actuation(app, tmp_path):
    profile = profile_with(tmp_path, {"within": EDIT, "region": {"left": 0, "top": 0,
                                                                  "right": 400, "bottom": 40},
                                       "note": "the field itself"})
    box, session = session_for(app["pid"], profile)

    typed = box.set_value(session, EDIT, "anything")
    keyed = box.send_keys(session, EDIT, ["home"])

    assert not typed["ok"] and "the field itself" in typed["error"]["message"]
    assert not keyed["ok"] and keyed["error"]["kind"] == "denied_by_policy"


def test_a_region_in_another_window_does_not_touch_this_one(app, tmp_path):
    profile = profile_with(tmp_path, {"within": EDIT, "region": {"left": 0, "top": 0,
                                                                  "right": 400, "bottom": 40}})
    box, session = session_for(app["pid"], profile)

    clicked = box.click(session, GRID, at={"x": 30, "y": 25},
                        expect={"locator": 'class=Static text="/last=grid row=1$/"'})

    assert clicked["ok"], clicked


def test_a_malformed_region_entry_fails_the_profile_load(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"denylist": [{"within": GRID, "region": {"left": 0}}]}),
                    encoding="utf-8")

    with pytest.raises(GhostdriverError, match="unreadable denylist entry"):
        Profile.load(path)


def test_attach_counts_the_regions(app, tmp_path):
    profile = profile_with(tmp_path, "*Delete*",
                           {"within": GRID, "region": ROW_1_BAND})
    box, session = session_for(app["pid"], profile)

    summary = box.sessions.get(session)

    assert len(summary.profile.denylist) == 1 and len(summary.profile.deny_regions) == 1
