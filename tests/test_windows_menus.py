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


def explain(result: dict) -> str:
    """The fields that say why a choice failed, for the assertion message:
    pytest truncates the whole result and hid exactly these (#145)."""
    # Text, not a dict: pytest abbreviates a dict in an assertion message
    # with '...', and hid the one field that mattered on the first CI
    # occurrence after this was added (#145).
    return json.dumps({k: result.get(k) for k in ("error", "declined", "tiers_attempted",
                                       "routes_attempted", "disturbances")}, indent=1, default=str)


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

    assert chosen["ok"], explain(chosen)


def test_an_owner_drawn_item_is_clicked_by_position(app):
    """index= counts matches from 0; the separator is its own type, so the
    second item a person sees is index=1 among MenuItems."""
    box, session = session_for(app["pid"])
    open_menu(box, session)

    chosen = box.click(session, f"type=MenuItem index=1 within=({MENU})", all_windows=True,
                       expect={"locator": 'class=Static text="/last=menu=owner-drawn/"'})

    assert chosen["ok"], explain(chosen)


# --- the menu chooses its own item (#135) --------------------------------------

def test_an_item_is_chosen_through_the_menu_s_own_keyboard_route(app):
    """The posted pair at an item's rectangle is hit-tested by the menu loop
    against the real pointer and closes the menu instead. The menu's
    keyboard route -- select by position, Return -- ends the menu and hands
    the command to the owner exactly as a person's choice would."""
    box, session = session_for(app["pid"])
    open_menu(box, session)

    result = box.click(session, 'type=MenuItem name="Copy row values"', all_windows=True,
                       expect={"locator": 'class=Static text="/last=menu=Copy row values/"'})

    assert result["ok"] and result["verified"] == "effect", explain(result)
    assert result["route"] == "menu_keys" and result["tiers_attempted"] == [3]


def test_an_owner_drawn_item_is_chosen_by_position_the_same_way(app):
    box, session = session_for(app["pid"])
    open_menu(box, session)

    result = box.click(session, f"type=MenuItem index=1 within=({MENU})",
                       all_windows=True,
                       expect={"locator": 'class=Static text="/last=menu=owner-drawn/"'})

    assert result["ok"], explain(result)
    assert result["route"] == "menu_keys"


# --- each phase of the menu's keyboard route is confirmed (#145) ---------------

class FakeMenu:
    """The menu as `menu_choose` sees it: when the item starts reading as
    highlighted, and when the window goes away after Return."""

    def __init__(self, *, highlight_after=1, ends_after=1, vanishes=False):
        self.highlight_after, self.ends_after, self.vanishes = highlight_after, ends_after, vanishes
        self.selects = self.showing_reads = self.posted = 0
        self.t = 0.0

    def install(self, monkeypatch):
        from ghostdriver.backends.windows import elements
        from ghostdriver.backends.windows import input as win_input

        monkeypatch.setattr(elements.winapi, "popup_menu_select", self.select)
        monkeypatch.setattr(elements.winapi, "popup_menu_item_state", self.state)
        monkeypatch.setattr(elements.winapi, "popup_menu_showing", self.showing)
        monkeypatch.setattr(win_input.user32, "PostMessageW", self.post)
        return elements

    def select(self, hwnd, index, **kw):
        self.selects += 1
        return True

    def state(self, hwnd, index, **kw):
        if self.vanishes:
            return None
        return {"enabled": True, "submenu": False,
                "highlighted": self.selects >= self.highlight_after}

    def showing(self, hwnd):
        self.showing_reads += 1
        return self.showing_reads < self.ends_after

    def post(self, hwnd, msg, wparam, lparam):
        self.posted += 1
        return 1

    def sleep(self, seconds):
        self.t += seconds

    def now(self):
        return self.t


def item():
    from ghostdriver.model.element import AccessibleElement

    return AccessibleElement(
        runtime_id=(0x1234, 2), control_type="MenuItem", name="", automation_id="owner-drawn",
        class_name="#32768", rect=(0, 0, 10, 10), enabled=True, offscreen=False, patterns=(),
        host_handle=0x1234, host_class="#32768", sibling_index=2, pid=1)


def test_return_is_posted_once_the_item_reads_as_highlighted(monkeypatch):
    menu = FakeMenu(highlight_after=3, ends_after=2)
    elements = menu.install(monkeypatch)

    assert elements.menu_choose(item(), sleep=menu.sleep, now=menu.now) is True
    assert menu.selects == 3, "re-selecting is idempotent; it waited for the highlight"
    assert menu.posted == 2, "one Return: a down and an up"


def test_an_item_that_never_highlights_is_named_and_return_is_not_posted(monkeypatch):
    menu = FakeMenu(highlight_after=10**9)
    elements = menu.install(monkeypatch)

    with pytest.raises(LookupError, match="never read back as highlighted"):
        elements.menu_choose(item(), sleep=menu.sleep, now=menu.now)
    assert menu.posted == 0


def test_a_menu_that_does_not_end_after_return_is_named(monkeypatch):
    menu = FakeMenu(ends_after=10**9)
    elements = menu.install(monkeypatch)

    with pytest.raises(LookupError, match="still showing"):
        elements.menu_choose(item(), sleep=menu.sleep, now=menu.now)
    assert menu.posted == 2, "Return was posted once, not repeated"


def test_a_menu_that_vanishes_mid_selection_is_named(monkeypatch):
    menu = FakeMenu(vanishes=True)
    elements = menu.install(monkeypatch)
    # the first state read happens before selection, so let that one through
    real_state, calls = menu.state, {"n": 0}

    def state(hwnd, index, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"enabled": True, "submenu": False, "highlighted": False}
        return real_state(hwnd, index, **kw)

    monkeypatch.setattr(elements.winapi, "popup_menu_item_state", state)
    with pytest.raises(LookupError, match="stopped showing"):
        elements.menu_choose(item(), sleep=menu.sleep, now=menu.now)


def test_a_failed_choice_says_which_routes_ran(app):
    """The result carries the route of every attempt and why each declined,
    so a CI failure explains itself without a rerun."""
    box, session = session_for(app["pid"])
    open_menu(box, session)

    result = box.click(session, 'type=MenuItem name="Copy row values"', all_windows=True,
                       expect={"locator": 'class=Static text="/this never appears/"',
                               "timeout_s": 0.3})

    assert not result["ok"]
    assert result["routes_attempted"][0] == "menu_keys"
    assert result["tiers_attempted"] == [3] * len(result["routes_attempted"])
