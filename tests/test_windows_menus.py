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
import warnings

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
                       menu_by_keyboard=True,
                       expect={"locator": 'class=Static text="/last=menu=Copy row values/"'})

    if not result["ok"]:
        # The keyboard route fails on CI about one run in three and passes
        # every local run; the cause is open (#190). Recorded, not blocking:
        # a warning reaches the log under -q where an xfail reason does not,
        # and the full explanation is the evidence D45 says to keep.
        warnings.warn(f"#190 menu_keys failed on this run: {explain(result)}", stacklevel=1)
        pytest.xfail("#190: the menu's keyboard route failed; explanation in the warnings")
    assert result["verified"] == "effect", explain(result)
    assert result["route"] == "menu_keys" and result["tiers_attempted"] == [3]


# --- each phase of the menu's keyboard route is confirmed (#145) ---------------

class FakeMenu:
    """The menu as `menu_choose` sees it: whether a read is answered at
    all, when the item starts reading as highlighted, and when the window
    goes away -- before Return was posted, or after it.

    `silent_reads` and `silent_selects` are the loaded machine (#190): the
    window is there and has simply not answered inside the timeout. That
    is a third thing, distinct from `vanishes` -- the window answering
    that there is no such menu item -- and from `window_gone`, the window
    not being up at all."""

    def __init__(self, *, highlight_after=1, ends_after=1, vanishes=False,
                 silent_reads=0, silent_selects=0, window_gone=False):
        self.highlight_after, self.ends_after, self.vanishes = highlight_after, ends_after, vanishes
        self.silent_reads, self.silent_selects = silent_reads, silent_selects
        self.window_gone = window_gone
        self.selects = self.reads = self.showing_reads = self.end_reads = self.posted = 0
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
        return self.selects > self.silent_selects

    def state(self, hwnd, index, **kw):
        self.reads += 1
        if self.reads <= self.silent_reads:
            return None
        if self.vanishes:
            return {"present": False}
        return {"present": True, "enabled": True, "submenu": False,
                "highlighted": self.selects >= self.highlight_after}

    def showing(self, hwnd):
        self.showing_reads += 1
        if not self.posted:
            # Before Return: the reads that ask whether the window is up at
            # all -- to settle an unanswered read, and once more just before
            # Return goes out. `ends_after` counts only the reads after it,
            # as it always did.
            return not self.window_gone
        self.end_reads += 1
        return self.end_reads < self.ends_after

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
            return {"present": True, "enabled": True, "submenu": False, "highlighted": False}
        return real_state(hwnd, index, **kw)

    monkeypatch.setattr(elements.winapi, "popup_menu_item_state", state)
    with pytest.raises(LookupError, match="stopped showing"):
        elements.menu_choose(item(), sleep=menu.sleep, now=menu.now)


# --- a menu that has not answered is not a menu that has gone (#190) ----------

def test_a_menu_that_answers_late_is_waited_for_rather_than_called_gone(monkeypatch):
    """The read goes out with a timeout, so a loaded machine can fail to
    answer it. That is what #190 looks like from here, and it must not
    spend the one diagnosis a caller cannot act on."""
    menu = FakeMenu(silent_reads=3)
    elements = menu.install(monkeypatch)

    assert elements.menu_choose(item(), sleep=menu.sleep, now=menu.now) is True
    assert menu.reads > 3, "it kept asking instead of concluding from silence"


def test_a_menu_that_never_answers_is_named_as_unanswered_not_as_gone(monkeypatch):
    menu = FakeMenu(silent_reads=10**9)
    elements = menu.install(monkeypatch)

    with pytest.raises(LookupError, match="did not answer") as raised:
        elements.menu_choose(item(), sleep=menu.sleep, now=menu.now)
    assert "no longer showing" not in str(raised.value), (
        "silence is not the menu saying it has gone, and the advice that goes "
        "with that says to reopen a menu which may never have closed")
    assert menu.posted == 0, "nothing is sent to a window that has not answered"


def test_a_menu_that_answers_that_it_has_gone_says_how_to_ask_for_the_keyboard(monkeypatch):
    """The other side of the same read: an answer of 'no such item' is the
    one-way failure D#189 left a way out of, and it is still prompt."""
    menu = FakeMenu(vanishes=True)
    elements = menu.install(monkeypatch)

    with pytest.raises(LookupError, match="no longer showing"):
        elements.menu_choose(item(), sleep=menu.sleep, now=menu.now)
    assert menu.reads == 1, "an answered read is decisive; there is nothing to wait for"


def test_silence_from_a_window_that_is_not_up_is_settled_without_waiting(monkeypatch):
    """A destroyed window cannot answer a message either, so waiting on it
    would spend the whole window to reach the wrong conclusion. `IsWindow`
    needs no message and cannot time out, so it settles what the read
    cannot -- and the caller gets the answer it can act on."""
    menu = FakeMenu(silent_reads=10**9, window_gone=True)
    elements = menu.install(monkeypatch)

    with pytest.raises(LookupError, match="no longer showing"):
        elements.menu_choose(item(), sleep=menu.sleep, now=menu.now)
    assert menu.t == 0.0, "it did not wait out MENU_ANSWER_S to say so"


def test_a_menu_that_ends_before_return_is_posted_is_named(monkeypatch):
    """The gap between the phases D#145 added: the item read as highlighted
    and the menu went away anyway, so it ended with nothing chosen and no
    keystroke of ours to account for it."""
    menu = FakeMenu(window_gone=True)
    elements = menu.install(monkeypatch)

    with pytest.raises(LookupError, match="before Return was posted"):
        elements.menu_choose(item(), sleep=menu.sleep, now=menu.now)
    assert menu.posted == 0


def test_the_unanswered_reads_and_selects_are_counted_in_what_is_raised(monkeypatch):
    menu = FakeMenu(highlight_after=10**9, silent_selects=10**9)
    elements = menu.install(monkeypatch)

    with pytest.raises(LookupError, match="unacknowledged") as raised:
        elements.menu_choose(item(), sleep=menu.sleep, now=menu.now)
    assert f"{menu.selects} selects" in str(raised.value)


def test_the_read_tells_an_unanswering_window_from_one_with_no_menu(monkeypatch):
    """The seam the conflation lived at: `send_message_timeout` answers
    None for a window that did not reply and 0 for one that replied with
    no menu, and both used to arrive as `None` (#190)."""
    from ghostdriver.backends.windows import winapi

    monkeypatch.setattr(winapi, "send_message_timeout", lambda *a, **kw: None)
    assert winapi.popup_menu_item_state(0x1234, 0) is None

    monkeypatch.setattr(winapi, "send_message_timeout", lambda *a, **kw: 0)
    assert winapi.popup_menu_item_state(0x1234, 0) == {"present": False}

    monkeypatch.setattr(winapi, "send_message_timeout", lambda *a, **kw: 0x99)
    monkeypatch.setattr(winapi.user32, "GetMenuState", lambda *a: 0xFFFFFFFF)
    assert winapi.popup_menu_item_state(0x1234, 0) == {"present": False}

    monkeypatch.setattr(winapi.user32, "GetMenuState", lambda *a: winapi.MF_HILITE)
    assert winapi.popup_menu_item_state(0x1234, 0) == {
        "present": True, "enabled": True, "submenu": False, "highlighted": True}


def test_a_select_the_menu_did_not_acknowledge_is_reported_as_such(monkeypatch):
    from ghostdriver.backends.windows import winapi

    monkeypatch.setattr(winapi, "send_message_timeout", lambda *a, **kw: None)
    assert winapi.popup_menu_select(0x1234, 0) is False

    monkeypatch.setattr(winapi, "send_message_timeout", lambda *a, **kw: 0)
    assert winapi.popup_menu_select(0x1234, 0) is True, "0 is an answer; None is silence"


def test_a_failed_choice_says_which_routes_ran(app):
    """The result carries the route of every attempt and why each declined,
    so a CI failure explains itself without a rerun."""
    box, session = session_for(app["pid"])
    open_menu(box, session)

    result = box.click(session, 'type=MenuItem name="Copy row values"', all_windows=True,
                       expect={"locator": 'class=Static text="/this never appears/"',
                               "timeout_s": 0.3})

    assert not result["ok"]
    assert result["routes_attempted"][0] == "posted", "the posted pair is the default first rung"
    assert result["tiers_attempted"] == [3] * len(result["routes_attempted"])


# --- which route goes first is a fact about the target (#189) -------------------

def test_an_ordinary_menu_is_chosen_by_the_posted_pair_by_default(app):
    box, session = session_for(app["pid"])
    open_menu(box, session)

    result = box.click(session, 'type=MenuItem name="Copy row values"', all_windows=True,
                       expect={"locator": 'class=Static text="/last=menu=Copy row values/"'})

    assert result["ok"] and result["verified"] == "effect", explain(result)
    assert result["route"] == "posted" and result["routes_attempted"] == ["posted"]


def test_the_order_of_the_two_routes():
    from ghostdriver.backends.windows import verbs

    def order(**kw):
        attempts = verbs.click_element(item(), **kw)
        return [a.name for a in sorted(attempts, key=lambda a: (a.rank, a.tier))]

    assert order() == ["posted", "menu_keys"]
    assert order(menu_by_keyboard=True) == ["menu_keys", "posted"]


def test_a_profile_can_declare_that_its_menus_need_the_keyboard(tmp_path):
    from ghostdriver.model.result import GhostdriverError
    from ghostdriver.session import Profile

    path = tmp_path / "p.json"
    path.write_text(json.dumps({"menus_by_keyboard": True}))
    assert Profile.load(path).menus_by_keyboard is True
    assert Profile().menus_by_keyboard is False

    path.write_text(json.dumps({"menus_by_keyboard": "yes"}))
    with pytest.raises(GhostdriverError, match="menus_by_keyboard"):
        Profile.load(path)
