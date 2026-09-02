"""Phase 2 against a real target, before it is pointed at anything real.

The fixture is a Profile L1 target on purpose: its buttons are a vendor
class that ignores semantic messages, so what phase 2 should learn about
them is known in advance. If it learns something else, the learning is
wrong rather than the target being surprising.
"""

import json
import subprocess
import sys
import time

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


def profile_with(tmp_path, safe_controls, denylist=(), **extra):
    document = {
        "_comment": "hand-curated; phase 2 must not disturb this",
        "matched_profile": "L1",
        "denylist": list(denylist),
        "safe_controls": safe_controls,
        **extra,
    }
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def full_session(pid, path):
    """A session at the only tier that permits phase 2."""
    from ghostdriver.policy import ConsentSource, Tier
    from ghostdriver.session import Profile, SessionManager
    from ghostdriver.tools import Toolbox

    box = Toolbox(SessionManager())
    box.sessions.record_grant(pid, allowed=True,
                              source=ConsentSource.ELICITED)
    session = box.sessions.attach(pid, command_line=["fixtureapp"],
                                   tier=Tier.FULL,
                                   profile=Profile.load(path)).session_id
    return box, session


def safe(caption, expect_text):
    """A listed control, with what the fixture's status line should read."""
    return {
        "locator": f'class=GhostFixtureCommandButton text="{caption}"',
        "expect": {"locator": f'class=Static text="{expect_text}"'},
        "note": f"view-only: {caption}",
    }


# --- the rails -----------------------------------------------------------

def test_phase_2_is_refused_below_the_full_tier(app, tmp_path):
    """Nothing grants `full` by default, and this is the one tool that acts
    without a task asking it to."""
    from ghostdriver.policy import ConsentSource, Tier
    from ghostdriver.session import Profile, SessionManager
    from ghostdriver.tools import Toolbox

    path = profile_with(tmp_path, [safe("Expand All", "clicks=1 last=Expand All")])
    box = Toolbox(SessionManager())
    box.sessions.record_grant(app["pid"], allowed=True,
                              source=ConsentSource.ELICITED)
    session = box.sessions.attach(app["pid"], command_line=["fixtureapp"],
                                   tier=Tier.INTERACTIVE,
                                   profile=Profile.load(path)).session_id

    result = box.probe_phase2(session)

    assert not result["ok"]
    assert result["error"]["kind"] == "denied_by_policy"


def test_a_target_with_no_list_has_nothing_to_run(app, tmp_path):
    """The probe never selects its own targets, so an empty list is not an
    invitation to pick some."""
    box, session = full_session(app["pid"], profile_with(tmp_path, []))

    result = box.probe_phase2(session)

    assert not result["ok"]
    assert "will only actuate ones an operator has listed" in \
        result["error"]["message"]


def test_only_can_narrow_the_list_but_never_widen_it(app, tmp_path):
    """`only` is a scope, not a way in. A locator absent from the file is
    refused even when passed explicitly."""
    path = profile_with(tmp_path, [safe("Expand All", "clicks=1 last=Expand All")])
    box, session = full_session(app["pid"], path)

    result = box.probe_phase2(
        session, only=['class=GhostFixtureCommandButton text="Complete Task"'])

    assert not result["ok"]
    assert "cannot add to it" in result["error"]["message"]


def test_a_control_both_listed_and_denied_is_refused_not_arbitrated(
    app, tmp_path
):
    """A contradiction in the operator's own policy. Picking a side would
    mean this tool deciding which of their instructions it preferred."""
    path = profile_with(
        tmp_path,
        [safe("Complete Task", "clicks=1 last=Complete Task")],
        denylist=["*complete*"],
    )
    box, session = full_session(app["pid"], path)

    result = box.probe_phase2(session)

    assert result["ok"], result.get("error")
    assert result["learned"] == 0
    assert result["actuation_map"] == {}
    assert "contradiction" in result["refused"][0]["reason"]


def test_an_expectation_that_cannot_be_parsed_refuses_the_whole_run(
    app, tmp_path
):
    """Better than actuating half the list and then discovering the rest is
    unusable -- this tool's mistakes are not free."""
    path = profile_with(tmp_path, [{
        "locator": 'class=GhostFixtureCommandButton text="Expand All"',
    }])
    box, session = full_session(app["pid"], path)

    result = box.probe_phase2(session)

    assert not result["ok"]
    assert "needs an expect" in result["error"]["message"]


# --- what it learns ------------------------------------------------------

def test_it_learns_how_a_vendor_class_actually_actuates(app, tmp_path):
    """The whole point. This class ignores semantic messages and publishes
    no pattern, so the answer should be the input pair -- learned by trying,
    not by being told."""
    path = profile_with(tmp_path, [
        safe("Expand All", "clicks=1 last=Expand All"),
    ])
    box, session = full_session(app["pid"], path)

    result = box.probe_phase2(session)

    assert result["ok"], result.get("error")
    learned = result["actuation_map"]["GhostFixtureCommandButton"]
    assert learned["click"] == "wm_mouse_pair"
    assert learned["verified"] is True


def test_it_records_that_the_higher_tier_was_tried_and_declined(app, tmp_path):
    """"Tier 3 works" is worth less than "tier 1 was offered and did not
    answer" -- the second says something about the target."""
    path = profile_with(tmp_path, [safe("Expand All", "clicks=1 last=Expand All")])
    box, session = full_session(app["pid"], path)

    result = box.probe_phase2(session)

    assert result["learned"] == 1
    assert result["unverified"] == []


def test_several_controls_of_one_class_become_one_entry(app, tmp_path):
    """A class is what the map is keyed on, and repeated agreement is what
    makes an entry worth trusting."""
    path = profile_with(tmp_path, [
        safe("Expand All", "clicks=1 last=Expand All"),
        safe("Collapse All", "clicks=2 last=Collapse All"),
    ])
    box, session = full_session(app["pid"], path)

    result = box.probe_phase2(session)

    entry = result["actuation_map"]["GhostFixtureCommandButton"]
    assert entry["samples"] == 2
    assert entry["verified"] is True


def test_a_wrong_expectation_is_reported_as_possibly_the_guess(app, tmp_path):
    """Drafting the expectations is what makes this usable on a real target,
    and this is the safeguard that makes drafting honest."""
    control = safe("Expand All", "this will never be the status line")
    control["expect_source"] = "drafted"
    box, session = full_session(app["pid"], profile_with(tmp_path, [control]))

    result = box.probe_phase2(session)

    assert result["ok"], result.get("error")
    # Not learned: a tier that cannot be shown to have worked is not a tier
    # that works, so nothing about this class reaches the map.
    assert result["learned"] == 0
    assert result["actuation_map"] == {}
    # But it was acted on, and that is reported rather than swallowed. An
    # earlier version counted it in neither, so the likeliest outcome of a
    # drafted guess produced silence.
    assert result["actuated_without_learning"] == 1
    assert "may be the guess that is wrong" in \
        result["unverified"][0]["reading"]
    assert result["unverified"][0]["tiers_attempted"] == [1, 3]


# --- what it writes ------------------------------------------------------

def test_what_it_learned_is_written_back(app, tmp_path):
    path = profile_with(tmp_path, [safe("Expand All", "clicks=1 last=Expand All")])
    box, session = full_session(app["pid"], path)

    result = box.probe_phase2(session)

    assert result["written"] is True
    document = json.loads(path.read_text())
    assert document["actuation_map"]["GhostFixtureCommandButton"]["click"] \
        == "wm_mouse_pair"


def test_it_does_not_disturb_the_rest_of_the_profile(app, tmp_path):
    """Least of all `safe_controls`, which is the list granting it
    permission to act in the first place."""
    path = profile_with(tmp_path, [safe("Expand All", "clicks=1 last=Expand All")],
                        denylist=["*delete*"])
    box, session = full_session(app["pid"], path)

    box.probe_phase2(session)

    document = json.loads(path.read_text())
    assert document["denylist"] == ["*delete*"]
    assert len(document["safe_controls"]) == 1
    assert document["_comment"].startswith("hand-curated")


def test_a_run_that_learned_nothing_writes_nothing(app, tmp_path):
    path = profile_with(tmp_path, [safe("Complete Task", "never")],
                        denylist=["*complete*"])
    box, session = full_session(app["pid"], path)

    result = box.probe_phase2(session)

    assert result["written"] is False
    assert "actuation_map" not in json.loads(path.read_text())


def test_focus_behaviour_is_recorded_for_a_target_that_stays_put(
    app, tmp_path
):
    """The fixture does not grab by default, and saying so is worth as much
    as saying it does -- it is what tells a caller the desktop is safe."""
    path = profile_with(tmp_path, [safe("Expand All", "clicks=1 last=Expand All")])
    box, session = full_session(app["pid"], path)

    result = box.probe_phase2(session, settle_ms=400)

    assert result["focus_behavior"]["self_foregrounds_on_click"] is False
    assert result["focus_behavior"]["samples"] == 1
