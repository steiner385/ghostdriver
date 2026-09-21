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

pytestmark = [on_windows, pytest.mark.slow]
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
        assert "person" in result.caveat
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
                                tier=Tier.FULL, profile=profile, clipboard=True).session_id


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
    """A button's caption *is* its content, so `read` answers it and
    spending a side effect on it is exactly the wrong trade. (That the text
    answered does not, on its own, make the region unpainted -- this button
    paints its caption, and a real grid painted its rows behind one: D#141.
    The refusal survives that correction; its reasoning is what changed.)"""
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


# --- a grid whose text query answers with a label (#141, D#141) ----------
#
# `--labelled-grid` paints the same rows as the grid above and answers
# WM_GETTEXT with a fixed "Component Grid", the shape measured on a real
# target (D#1). Before it existed the fixture could not reproduce the
# defect at all: every control here answered with its real caption, so the
# refusal looked right everywhere it could be tested.

LABELLED = "class=GhostFixtureLabelledGrid"


def labelled_profile(tmp_path, *classes):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"matched_profile": "L1",
                                "text_is_label": list(classes)}),
                    encoding="utf-8")
    return path


def test_read_on_the_labelled_grid_answers_with_the_label_not_the_rows():
    """Why the old refusal's advice was worse than no advice: a caller who
    follows it gets a plausible answer that is the same whatever the grid
    holds, and nothing in the result says so."""
    from ghostdriver.session import SessionManager
    from ghostdriver.tools import Toolbox

    proc, handles = start("--labelled-grid")
    try:
        box = Toolbox(SessionManager())
        session = full_session(box, handles["pid"])

        values = box.read(session, LABELLED)["values"]

        assert [v["text"] for v in values] == [handles["grid_label"]]
        assert values[0]["answered"], "it answers -- that is the whole trap"
        assert "PART-0001" not in values[0]["text"], "not one painted row"
    finally:
        stop(proc, handles)


def test_an_undeclared_labelled_grid_is_still_refused(preserved_clipboard):
    """The guard is not loosened for everything that looks like a grid. With
    nothing declared, the tool refuses and says what would change that."""
    from ghostdriver.session import SessionManager
    from ghostdriver.tools import Toolbox

    proc, handles = start("--labelled-grid")
    try:
        box = Toolbox(SessionManager())
        session = full_session(box, handles["pid"])

        report = box.probe_grid(session, LABELLED)

        assert not report["ok"]
        message = report["error"]["message"]
        assert "GhostFixtureLabelledGrid" in message
        assert "text_is_label" in message
    finally:
        stop(proc, handles)


def test_a_declared_labelled_grid_is_probed_and_its_copy_route_found(
    preserved_clipboard, tmp_path,
):
    """The regression case for #141: the same control, the same text, one
    declaration -- and the probe reaches the routes it exists to try. Run
    against the fixture's grid because a real target's answer is `unknown`
    (D#1) and `unknown` cannot tell "the guard was passed" from "the guard
    refused": both leave a caller with nothing."""
    from ghostdriver.session import SessionManager
    from ghostdriver.tools import Toolbox

    proc, handles = start("--labelled-grid")
    try:
        box = Toolbox(SessionManager())
        session = full_session(
            box, handles["pid"],
            labelled_profile(tmp_path, "GhostFixtureLabelledGrid"))

        report = box.probe_grid(session, LABELLED)

        assert report["ok"], report
        assert report["grid_strategy"] == "clipboard_copy"
        assert "Component Grid" in report["text_is_label"]
        assert "text_is_label" in report["text_is_label"], "says why it ran"
    finally:
        stop(proc, handles)


def test_the_declaration_is_read_as_a_class_pattern(preserved_clipboard,
                                                    tmp_path):
    from ghostdriver.session import SessionManager
    from ghostdriver.tools import Toolbox

    proc, handles = start("--labelled-grid")
    try:
        box = Toolbox(SessionManager())
        session = full_session(box, handles["pid"],
                               labelled_profile(tmp_path, "GhostFixture*Grid"))

        report = box.probe_grid(session, LABELLED)

        assert report["ok"], report
    finally:
        stop(proc, handles)


def test_a_declaration_does_not_waive_the_guard_for_another_class(tmp_path):
    """Declared per class, not per session. The button next to the grid is
    still refused, because its caption really is its content."""
    from ghostdriver.session import SessionManager
    from ghostdriver.tools import Toolbox

    proc, handles = start("--labelled-grid")
    try:
        box = Toolbox(SessionManager())
        session = full_session(
            box, handles["pid"],
            labelled_profile(tmp_path, "GhostFixtureLabelledGrid"))

        report = box.probe_grid(
            session, 'class=GhostFixtureCommandButton text="Expand All"')

        assert not report["ok"]
        assert "Use `read`" in report["error"]["message"]
    finally:
        stop(proc, handles)


# --- capture's per-control pixel-judged flag (D#63, issue #63) -----------

def test_capturing_the_painted_grid_is_flagged_judge_by_pixels():
    """The grid paints its own rows and exposes no accessibility tree
    beneath it -- exactly the shape D#51 found `enabled` lying about.
    `capture`, given the grid's own locator, already resolved this one
    node; classifying it costs nothing extra, so the result says so."""
    from ghostdriver.session import SessionManager
    from ghostdriver.tools import Toolbox

    proc, handles = start()
    try:
        box = Toolbox(SessionManager())
        session = full_session(box, handles["pid"])

        result = box.capture(
            session,
            locator='class=GhostFixtureDataGrid '
                    'within=(class=GhostFixturePage text="Operations")')

        assert result["ok"], result
        assert result["surface"]["kind"] == "owner-drawn"
        assert result["surface"]["access"] == "pixels"
        assert "pixels" in result["surface"]["note"]
    finally:
        stop(proc, handles)


def test_capturing_a_real_button_carries_no_pixel_judged_flag():
    """A control a window tree already answers for is not the case D#51
    named -- the field would be noise with nothing to warn about."""
    from ghostdriver.session import SessionManager
    from ghostdriver.tools import Toolbox

    proc, handles = start()
    try:
        box = Toolbox(SessionManager())
        session = full_session(box, handles["pid"])

        result = box.capture(
            session, locator='class=GhostFixtureCommandButton text="Expand All"')

        assert result["ok"], result
        assert "surface" not in result
    finally:
        stop(proc, handles)
