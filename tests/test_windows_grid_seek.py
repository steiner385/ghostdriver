"""grid_seek: page an owner-drawn grid, copy each view, match a value.

The deferred item of D63, proven on the fixture's paging grid (nine rows
shown three at a time, one value only on the last page). A grid that
yields its rows to Copy and shows only the view in front of it has no
primitive for "is this value in it, and where"; this is that loop.
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

pytestmark = [on_windows, pytest.mark.clipboard]

GRID = "class=GhostFixtureDataGrid"


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


def full_session(pid):
    box = Toolbox(SessionManager(store=ConsentStore(None)))
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    return box, box.sessions.attach(pid, command_line=["fixtureapp"],
                                    tier=Tier.FULL, clipboard=True).session_id


def test_a_seek_pages_to_a_value_only_on_the_last_page():
    proc, handles = start("--grid-pages")
    try:
        box, session = full_session(handles["pid"])

        found = box.grid_seek(session, GRID, value="PART-0009")

        assert found["ok"], found
        assert found["found"] is True
        assert found["match"]["page"] == 3
        assert "PART-0009" in found["match"]["line"]
        assert found["advanced"] is True and found["pages_read"] == 3
    finally:
        stop(proc, handles)


def test_a_seek_with_no_value_reads_every_row_to_the_end():
    proc, handles = start("--grid-pages")
    try:
        box, session = full_session(handles["pid"])

        read = box.grid_seek(session, GRID)

        assert read["ok"] and read["reached_end"] is True
        assert read["row_count"] == 9, read
        assert read["rows"][0].startswith("PART-0001")
        assert read["rows"][-1].startswith("PART-0009")
    finally:
        stop(proc, handles)


def test_a_value_not_in_the_grid_is_reported_absent_after_the_end():
    proc, handles = start("--grid-pages")
    try:
        box, session = full_session(handles["pid"])

        missing = box.grid_seek(session, GRID, value="PART-9999")

        assert missing["ok"] and missing["found"] is False
        assert missing["reached_end"] is True
        assert "not in the grid" in missing["note"]
    finally:
        stop(proc, handles)


def test_a_grid_that_does_not_page_says_the_view_did_not_change():
    """The default fixture grid ignores PageDown, so the second copy repeats
    the first: honest about not knowing whether it is one page or unfocused."""
    proc, handles = start()
    try:
        box, session = full_session(handles["pid"])

        read = box.grid_seek(session, GRID)

        assert read["ok"] and read["reached_end"] is True
        assert read["advanced"] is False
        assert read["row_count"] == 3
        assert "did not change when advanced" in read["note"]
    finally:
        stop(proc, handles)


def test_grid_seek_needs_the_full_tier():
    proc, handles = start("--grid-pages")
    try:
        box = Toolbox(SessionManager(store=ConsentStore(None)))
        box.sessions.record_grant(handles["pid"], allowed=True,
                                  source=ConsentSource.ELICITED)
        session = box.sessions.attach(handles["pid"], command_line=["fixtureapp"],
                                      tier=Tier.INTERACTIVE).session_id

        refused = box.grid_seek(session, GRID)

        assert not refused["ok"] and "needs tier 'full'" in refused["error"]["message"]
    finally:
        stop(proc, handles)


def test_grid_seek_refuses_an_unknown_advance_key():
    proc, handles = start("--grid-pages")
    try:
        box, session = full_session(handles["pid"])

        refused = box.grid_seek(session, GRID, advance="wheeee")

        assert not refused["ok"] and "named key" in refused["error"]["message"]
    finally:
        stop(proc, handles)
