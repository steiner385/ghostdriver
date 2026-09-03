"""The grid-strategy routes against a real owner-drawn grid.

The fixture's grid paints its rows and answers no text query -- the shape
the whole probe exists for -- and it answers WM_COPY the way many real grids
do. These tests exercise the clipboard: they save what is on it first and
assert it comes back, because the clipboard is shared with whoever is at the
machine and leaving their copy clobbered would be a real harm, not a test
artefact.
"""

import json
import subprocess
import sys
import time

import psutil
import pytest

from tests.conftest import on_windows

pytestmark = on_windows


def start(*args):
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp", *args],
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


def grid_node(pid):
    from ghostdriver.backends.windows.enumerate import enumerate_process
    from ghostdriver.model.window import select_main_tree

    tree = select_main_tree(enumerate_process(pid))
    return next(n for n in tree.walk() if n.class_name == "GhostFixtureDataGrid")


@pytest.fixture
def preserved_clipboard():
    """Whatever the person had copied, put back afterwards no matter what."""
    from ghostdriver.backends.windows.grid import (
        read_clipboard_text,
        write_clipboard_text,
    )

    prior = read_clipboard_text()
    yield prior
    write_clipboard_text(prior)


# --- the routes ----------------------------------------------------------

def test_the_grid_copies_its_rows_and_the_clipboard_is_put_back(
    preserved_clipboard,
):
    from ghostdriver.backends.windows.grid import (
        copy_route,
        read_clipboard_text,
        write_clipboard_text,
    )

    sentinel = "the operator's own clipboard text"
    write_clipboard_text(sentinel)
    proc, handles = start()
    try:
        result = copy_route(grid_node(handles["pid"]), want_text=True)

        assert result.worked, result.detail
        assert result.lines == 3, "three fixture rows"
        assert "PART-0001\tBracket, upper" in result.detail
        assert "shared" in result.caveat
        assert read_clipboard_text() == sentinel, "put back what was there"
    finally:
        stop(proc, handles)


def test_the_probe_reports_shape_not_cells_by_default(preserved_clipboard):
    """A profile records that the route works and how many lines it gave.
    Cell data is the target's business and never lands in the document."""
    from ghostdriver.backends.windows.grid import copy_route

    proc, handles = start()
    try:
        result = copy_route(grid_node(handles["pid"]))

        assert result.worked
        assert "PART-0001" not in result.detail
        assert "3 line(s)" in result.detail
    finally:
        stop(proc, handles)


def test_a_grid_that_ignores_copy_is_reported_honestly(preserved_clipboard):
    """No route working has to come back as exactly that. This is the
    verdict that defers OCR, and it must not be dressed up."""
    from ghostdriver.backends.windows.grid import copy_route

    proc, handles = start("--grid-no-copy")
    try:
        result = copy_route(grid_node(handles["pid"]))

        assert not result.worked
        assert "did not change the clipboard" in result.detail
    finally:
        stop(proc, handles)


def test_focus_reveals_nothing_on_a_painted_grid():
    """True of the fixture, and measured true of a real Profile L1 grid:
    telling it it has focus does not make it grow an accessible tree."""
    from ghostdriver.backends.windows.grid import focus_route

    proc, handles = start()
    try:
        result = focus_route(grid_node(handles["pid"]))
        assert not result.worked
        assert "before focus" in result.detail
    finally:
        stop(proc, handles)


# --- the probe as a whole, cheapest-first --------------------------------

def test_the_free_route_fails_and_the_clipboard_wins(preserved_clipboard):
    from ghostdriver.backends.windows.grid import copy_route, focus_route
    from ghostdriver.gridstrategy import GridProbe, find_grid_strategy

    proc, handles = start()
    try:
        node = grid_node(handles["pid"])
        finding = find_grid_strategy(GridProbe(
            accessible_on_focus=lambda: focus_route(node),
            clipboard_copy=lambda: copy_route(node),
        ))

        assert finding.strategy.value == "clipboard_copy"
        assert [a["route"] for a in finding.attempts] == [
            "accessible_on_focus", "clipboard_copy"]
        assert finding.attempts[0]["worked"] is False
    finally:
        stop(proc, handles)


# --- the tool, with its rails --------------------------------------------

def full_session(box, pid, path=None):
    from ghostdriver.policy import ConsentSource, Tier
    from ghostdriver.session import Profile

    box.sessions.record_grant(pid, allowed=True,
                              source=ConsentSource.ELICITED)
    profile = Profile.load(path) if path else Profile.none()
    return box.sessions.attach(pid, command_line=["fixtureapp"],
                                tier=Tier.FULL, profile=profile).session_id


def test_the_tool_records_the_strategy_in_the_profile(preserved_clipboard,
                                                      tmp_path):
    from ghostdriver.session import SessionManager
    from ghostdriver.tools import Toolbox

    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"matched_profile": "L1", "denylist": [],
                                "_comment": "hand-curated"}),
                    encoding="utf-8")
    proc, handles = start()
    try:
        box = Toolbox(SessionManager())
        session = full_session(box, handles["pid"], path)

        report = box.probe_grid(session, "class=GhostFixtureDataGrid")

        assert report["ok"], report
        assert report["grid_strategy"] == "clipboard_copy"
        assert report["written"] is True
        document = json.loads(path.read_text())
        assert document["grid_strategy"] == "clipboard_copy"
        assert document["_comment"] == "hand-curated", "nothing else disturbed"
        assert "PART-0001" not in json.dumps(document), "no cell data written"
    finally:
        stop(proc, handles)


def test_the_tool_can_be_told_to_leave_the_clipboard_alone():
    """allow_clipboard=false tries only the free route, and reports UNKNOWN
    rather than reaching for the route it was told not to use."""
    from ghostdriver.session import SessionManager
    from ghostdriver.tools import Toolbox

    proc, handles = start()
    try:
        box = Toolbox(SessionManager())
        session = full_session(box, handles["pid"])

        report = box.probe_grid(session, "class=GhostFixtureDataGrid",
                                allow_clipboard=False)

        assert report["ok"]
        assert report["grid_strategy"] == "unknown"
        clip = next(a for a in report["attempts"] if a["route"] == "clipboard_copy")
        assert clip["tried"] is False
    finally:
        stop(proc, handles)


def test_the_tool_refuses_below_the_full_tier():
    from ghostdriver.policy import ConsentSource, Tier
    from ghostdriver.session import SessionManager
    from ghostdriver.tools import Toolbox

    proc, handles = start()
    try:
        box = Toolbox(SessionManager())
        box.sessions.record_grant(handles["pid"], allowed=True,
                                  source=ConsentSource.ELICITED)
        session = box.sessions.attach(handles["pid"], command_line=["x"],
                                       tier=Tier.INTERACTIVE).session_id

        report = box.probe_grid(session, "class=GhostFixtureDataGrid")

        assert not report["ok"]
        assert report["error"]["kind"] == "denied_by_policy"
    finally:
        stop(proc, handles)


def test_the_tool_refuses_a_region_that_read_already_answers():
    """A control with text is not a painted region. Spending a side effect
    on something a free call already reads is exactly the wrong trade."""
    from ghostdriver.session import SessionManager
    from ghostdriver.tools import Toolbox

    proc, handles = start()
    try:
        box = Toolbox(SessionManager())
        session = full_session(box, handles["pid"])

        report = box.probe_grid(
            session, 'class=GhostFixtureCommandButton text="Expand All"')

        assert not report["ok"]
        assert "Use `read`" in report["error"]["message"]
    finally:
        stop(proc, handles)
