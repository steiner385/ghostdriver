"""A context menu's items are elements, read from the menu itself.

The report (D65): `find` returned nothing for the items of a `#32768`
window and the session clicked "Copy row values" by an offset measured
off a screenshot. The menu handle names every item's rectangle, and the
caption of every item that has one; an owner-drawn item has a position.
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
MENU = "class=#32768"


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


def open_menu(box, session):
    opened = box.click(session, GRID, button="right", at=ROW_1,
                       expect={"locator": 'class=Static text="/last=grid row=1 button=right/"'})
    assert opened["ok"], opened
    shown = box.wait_for(session, MENU, condition="visible", timeout_s=3, all_windows=True)
    assert shown["ok"], shown


def test_the_menu_lists_its_items_with_rectangles_and_captions(app):
    box, session = session_for(app["pid"])
    open_menu(box, session)

    found = box.find(session, f"type=MenuItem within=({MENU})", all_windows=True)

    items = found["elements"]
    assert [i["name"] for i in items] == ["Copy row values", ""], items
    assert items[1]["automation_id"] == "owner-drawn"
    assert all(i["rect"]["right"] > i["rect"]["left"] for i in items)
    assert len(box.find(session, f"type=Separator within=({MENU})", all_windows=True)["elements"]) == 1


def test_a_captioned_item_is_clicked_by_name(app):
    box, session = session_for(app["pid"])
    open_menu(box, session)

    chosen = box.click(session, 'type=MenuItem name="Copy row values"', all_windows=True,
                       expect={"locator": 'class=Static text="/last=menu=Copy row values/"'})

    assert chosen["ok"], chosen


def test_an_owner_drawn_item_is_clicked_by_position(app):
    """index= counts matches from 0; the separator is its own type, so the
    second item a person sees is index=1 among MenuItems."""
    box, session = session_for(app["pid"])
    open_menu(box, session)

    chosen = box.click(session, f"type=MenuItem index=1 within=({MENU})", all_windows=True,
                       expect={"locator": 'class=Static text="/last=menu=owner-drawn/"'})

    assert chosen["ok"], chosen
