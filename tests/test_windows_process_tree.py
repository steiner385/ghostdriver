"""A session sees its target's process tree, and consent covers it.

The shape that prompted this: a browser opens its file dialog in a helper
process with its own pid. Under per-pid consent the operator was asked to
approve the application they had just approved, and under per-pid
enumeration the dialog was invisible to the session. The fixture reproduces
the shape by spawning a second fixture in a child process; the parent
announces the child's pid on a second stdout line.
"""

import json
import subprocess
import sys
import time

import psutil
import pytest

from ghostdriver.policy import ConsentSource
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox
from tests.conftest import on_windows

pytestmark = [on_windows, pytest.mark.slow]
@pytest.fixture
def family():
    """(parent handles, child pid): a target that owns a window in a child process."""
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "tests.fixtureapp", "--child-after", "200"],
        stdout=subprocess.PIPE, text=True)
    parent = json.loads(proc.stdout.readline())
    child = json.loads(proc.stdout.readline())["child"]
    time.sleep(0.5)
    yield parent, child
    for pid in (child, parent["pid"]):
        try:
            psutil.Process(pid).terminate()
        except psutil.Error:
            pass
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def box():
    return Toolbox(SessionManager())


def approved(box, pid, tier="interactive"):
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    result = box.attach(pid, tier=tier)
    assert result["ok"], result
    return result["session_id"]


def test_the_child_really_is_a_descendant(family):
    """Through the virtualenv's launcher stub, which sits between them: the
    announced parent is an ancestor, not necessarily the direct parent --
    the shape the consent walk and the descendant walk both handle."""
    parent, child = family
    ancestors = [p.pid for p in psutil.Process(child).parents()]
    assert parent["pid"] in ancestors


# --- seeing the tree ------------------------------------------------------------

def test_all_windows_includes_the_windows_a_child_process_owns(box, family):
    parent, child = family
    session = approved(box, parent["pid"])

    described = box.describe(session, all_windows=True)

    shells = [w for w in described["windows"] if w["class"] == "GhostFixtureShell"]
    assert {w["pid"] for w in shells} == {parent["pid"], child}
    assert described["windows"][0]["pid"] == parent["pid"], "the main window is the target's own"


def test_the_main_window_stays_the_targets_own(box, family):
    parent, _ = family
    session = approved(box, parent["pid"])

    described = box.describe(session)

    assert [w["pid"] for w in described["windows"]] == [parent["pid"]]


def test_a_control_in_the_child_process_is_found_and_driven_from_the_parents_session(
        box, family):
    """No second attach, no second question: the dialog's button is the
    application's button."""
    parent, child = family
    session = approved(box, parent["pid"])

    found = box.find(session, 'class=Static text="/clicks=/"', all_windows=True)
    assert found["match_count"] == 2
    in_child = [e for e in found["elements"] if e["pid"] == child]
    assert len(in_child) == 1

    # The two fixtures are identical, so the child's button is named by
    # position among the matches; a real dialog has its own classes.
    buttons = box.find(session, 'class=GhostFixtureCommandButton text="Expand All"',
                       all_windows=True)
    index = next(i for i, e in enumerate(buttons["elements"]) if e["pid"] == child)
    clicked = box.click(
        session, f'class=GhostFixtureCommandButton text="Expand All" index={index}',
        all_windows=True,
        expect={"locator": 'class=Static text="/clicks=1 last=Expand All/"',
                "all_windows": True})

    assert clicked["ok"], clicked
    assert clicked["element"]["pid"] == child
    after = box.find(session, 'class=Static text="/clicks=1/"', all_windows=True)
    assert [e["pid"] for e in after["elements"]] == [child], "the child's counter moved, not the parent's"


# --- consent covers the tree -------------------------------------------------------

def test_attaching_to_the_child_needs_no_second_approval(box, family):
    parent, child = family
    box.sessions.record_grant(parent["pid"], allowed=True, source=ConsentSource.ELICITED)

    attached = box.attach(child)

    assert attached["ok"], attached
    assert attached["consent"]["source"] == "elicited"


def test_list_targets_shows_the_child_as_covered_by_its_parent(box, family):
    parent, child = family
    box.sessions.record_grant(parent["pid"], allowed=True, source=ConsentSource.ELICITED)

    targets = {t["pid"]: t for t in box.list_targets()["targets"]}

    assert targets[parent["pid"]]["consent"] == "allowed"
    assert targets[child]["consent"] == "allowed"
