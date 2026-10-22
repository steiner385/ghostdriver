"""Elements that are not windows, against the fixture's real ones.

The fixture carries a SysTabControl32 whose tab items switch its pages and
a ToolbarWindow32 of unlabelled buttons. To the window tree both are one
window with nothing inside; on the accessibility surface they are TabItem
elements with a SelectionItem pattern and MenuItem elements with Invoke.
These prove the walk, the resolution through the tools, actuation by
pattern and by posted click, the selection expectation, and the denylist
naming an element by what it is.
"""

import json
import subprocess
import sys
import time

import psutil
import pytest

from ghostdriver.policy import ConsentSource
from ghostdriver.session import Profile, SessionManager
from ghostdriver.tools import Toolbox
from tests.conftest import on_windows

pytestmark = on_windows


@pytest.fixture
def app():
    proc = subprocess.Popen([sys.executable, "-m", "tests.fixtureapp"],
                            stdout=subprocess.PIPE, text=True)
    handles = json.loads(proc.stdout.readline())
    time.sleep(0.4)
    yield handles
    if handles["pid"] != proc.pid:
        try:
            psutil.Process(handles["pid"]).terminate()
        except psutil.Error:
            pass
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def box():
    return Toolbox(SessionManager())


def session_on(box, pid, *, denylist=()):
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    profile = Profile(denylist=tuple(denylist)) if denylist else Profile.none()
    return box.sessions.attach(pid, command_line=["fixtureapp"],
                               tier=__import__("ghostdriver.policy").policy.Tier.INTERACTIVE,
                               profile=profile).session_id


def status_text(box, session):
    return box.read(session, 'class=Static text="/clicks=/"')["values"][0]["text"]


# --- the walk -------------------------------------------------------------------

def test_the_walk_sees_tab_items_the_window_tree_cannot(app):
    from ghostdriver.backends.windows.elements import walk_elements
    from ghostdriver.backends.windows.enumerate import enumerate_process
    from ghostdriver.model.window import select_main_tree

    tree = select_main_tree(enumerate_process(app["pid"]))
    tabs_node = next(n for n in tree.walk() if n.class_name == "SysTabControl32")
    assert tabs_node.children == (), "to the window tree the tab strip is empty"

    walked = walk_elements(tabs_node)
    items = [e for e, _ in walked if e.control_type == "TabItem"]

    assert [i.name for i in items] == ["Operations", "Components", "Change Log"]
    assert all("SelectionItem" in i.patterns for i in items)
    assert [i.selected for i in items] == [True, False, False]
    assert all(i.host_handle == tabs_node.handle for i in items), \
        "an element without a window of its own is hosted by the control"
    assert [i.sibling_index for i in items] == [1, 2, 3]


# --- through the tools -------------------------------------------------------------

def test_find_lists_the_tabs_with_locators_that_resolve_again(box, app):
    session = session_on(box, app["pid"])

    found = box.find(session, "type=TabItem")

    assert found["ok"] and found["match_count"] == 3
    names = [e["name"] for e in found["elements"]]
    assert names == ["Operations", "Components", "Change Log"]
    for element in found["elements"]:
        again = box.find(session, element["locator"])
        assert again["match_count"] == 1, element["locator"]
        assert again["elements"][0]["name"] == element["name"]


def test_find_lists_unlabelled_toolbar_buttons_by_position(box, app):
    session = session_on(box, app["pid"])

    found = box.find(session, "type=MenuItem within=(class=ToolbarWindow32)")

    assert found["match_count"] == 3
    assert [e["name"] for e in found["elements"]] == ["", "", ""]
    assert [e["identities"] for e in found["elements"]] == [
        ["MenuItem#1@ToolbarWindow32"],
        ["MenuItem#2@ToolbarWindow32"],
        ["MenuItem#3@ToolbarWindow32"],
    ]


def test_read_answers_with_the_element_name_and_selection(box, app):
    session = session_on(box, app["pid"])

    values = box.read(session, 'type=TabItem name="Operations"')["values"]

    assert values == [{"type": "TabItem", "text": "Operations",
                       "answered": True, "selected": True}]


# --- actuation -----------------------------------------------------------------------

def test_clicking_a_tab_switches_the_page_it_stands_for(box, app):
    """Through the posted click, which is what notifies the application.
    The expectation names the *effect* a person would see -- the page --
    not the tab's own selected flag, because the pattern route sets that
    flag without the page ever switching (see verbs.click_element)."""
    session = session_on(box, app["pid"])
    assert box.find(session, 'class=GhostFixturePage text="Components"')["match_count"] == 0

    result = box.click(session, 'type=TabItem name="Components"',
                       expect={"locator": 'class=GhostFixturePage text="Components"'})

    assert result["ok"], result
    assert result["tier_used"] == 3 and result["verified"] == "effect"
    assert result["element"]["type"] == "TabItem"
    selected = box.read(session, 'type=TabItem name="Components"')["values"][0]
    assert selected["selected"] is True


def test_selecting_through_the_pattern_alone_does_not_switch_the_page(box, app):
    """The measurement the ladder order rests on, kept as a test so a
    fixture or toolkit change that makes it false is noticed."""
    from ghostdriver.backends.windows.elements import act_via_pattern, is_selected, walk_elements
    from ghostdriver.backends.windows.enumerate import enumerate_process
    from ghostdriver.model.window import select_main_tree

    session = session_on(box, app["pid"])
    tree = select_main_tree(enumerate_process(app["pid"]))
    tabs = next(n for n in tree.walk() if n.class_name == "SysTabControl32")
    components = next(e for e, _ in walk_elements(tabs) if e.name == "Components")

    assert act_via_pattern(components)
    time.sleep(0.3)

    assert is_selected(components) is True, "the surface says selected"
    assert box.find(session, 'class=GhostFixturePage text="Components"')["match_count"] == 0, \
        "and the application never heard about it"


def test_clicking_an_unlabelled_toolbar_button_by_position(box, app):
    session = session_on(box, app["pid"])

    result = box.click(
        session, "type=MenuItem index=1 within=(class=ToolbarWindow32)",
        expect={"locator": 'class=Static text="/clicks=1 last=tool-second/"'})

    assert result["ok"], result
    assert result["verified"] == "effect"
    assert "last=tool-second" in status_text(box, session)


def test_the_posted_click_reaches_an_element_through_its_host(box, app):
    """Tier 3 on its own: the route a target with no patterns is driven by.
    The button pair goes to the toolbar window at the button's rectangle,
    and the toolbar handles it as a click on that button."""
    from ghostdriver.backends.windows.elements import click_posted, walk_elements
    from ghostdriver.backends.windows.enumerate import enumerate_process
    from ghostdriver.model.window import select_main_tree

    session = session_on(box, app["pid"])
    tree = select_main_tree(enumerate_process(app["pid"]))
    toolbar = next(n for n in tree.walk() if n.class_name == "ToolbarWindow32")
    third = [e for e, _ in walk_elements(toolbar) if e.control_type == "MenuItem"][2]

    assert click_posted(third)
    time.sleep(0.3)

    assert "last=tool-third" in status_text(box, session)


def test_an_ambiguous_element_locator_is_refused_with_candidates(box, app):
    session = session_on(box, app["pid"])

    result = box.click(session, "type=TabItem")

    assert not result["ok"]
    assert result["error"]["kind"] == "ambiguous"
    assert [c["name"] for c in result["error"]["candidates"]] == \
        ["Operations", "Components", "Change Log"]


def test_replacing_the_value_of_an_element_that_has_none_is_refused(box, app):
    """A tab item publishes no value, so there is nothing to replace; the
    refusal says what to do instead."""
    session = session_on(box, app["pid"])

    result = box.set_value(session, 'type=TabItem name="Components"', "x")

    assert not result["ok"]
    assert result["error"]["kind"] == "not_actionable"
    assert "type_text" in result["error"]["message"]


# --- the denylist names elements by what they are ----------------------------------

def test_the_denylist_refuses_a_tab_by_its_typed_caption(box, app):
    session = session_on(box, app["pid"], denylist=["TabItem:Change*"])

    result = box.click(session, 'type=TabItem name="Change Log"')

    assert not result["ok"]
    assert result["error"]["kind"] == "denied_by_policy"
    assert "Change Log" in result["error"]["message"]


def test_the_denylist_refuses_an_unlabelled_button_by_type_and_position(box, app):
    """The case the denylist could not express before: a button with no
    caption, forbidden by what and where it is."""
    session = session_on(box, app["pid"], denylist=["MenuItem#3@ToolbarWindow32"])

    refused = box.click(session, "type=MenuItem index=2 within=(class=ToolbarWindow32)")
    allowed = box.click(session, "type=MenuItem index=0 within=(class=ToolbarWindow32)")

    assert not refused["ok"] and refused["error"]["kind"] == "denied_by_policy"
    assert allowed["ok"], allowed


def test_a_plain_caption_pattern_still_catches_a_named_element(box, app):
    session = session_on(box, app["pid"], denylist=["*change log*"])

    result = box.click(session, 'type=TabItem name="Change Log"')

    assert result["error"]["kind"] == "denied_by_policy"


# --- waiting on an element -----------------------------------------------------------

def test_wait_for_works_on_element_locators(box, app):
    session = session_on(box, app["pid"])

    present = box.wait_for(session, 'type=TabItem name="Components"', timeout_s=1.0)
    absent = box.wait_for(session, 'type=TabItem name="Nowhere"', condition="absent",
                          timeout_s=1.0)

    assert present["ok"] and absent["ok"]


# --- on a hidden desktop ------------------------------------------------------------

def test_elements_resolve_on_a_hidden_desktop_session(box):
    """The walk is COM, and COM is apartment-bound: a hidden-desktop session
    runs every backend call on its desktop-bound worker thread, and the
    walk has to create its client there. Proven by finding the tabs of a
    target nobody on this desktop can see."""
    command = [sys.executable, "-u", "-m", "tests.fixtureapp", "--onscreen"]
    box.sessions.record_launch_grant(command, allowed=True)
    launched = box.launch_isolated(command, tier="interactive", announces_pid=True)
    assert launched["ok"], launched
    session = launched["session_id"]
    try:
        for _ in range(40):
            if box.describe(session).get("windows"):
                break
            time.sleep(0.1)

        found = box.find(session, "type=TabItem")
        assert [e["name"] for e in found["elements"]] == \
            ["Operations", "Components", "Change Log"]

        clicked = box.click(session, 'type=TabItem name="Components"',
                            expect={"locator": 'class=GhostFixturePage text="Components"'})
        assert clicked["ok"], clicked
    finally:
        box.release(session)


# --- the pattern rung names why it declined (#236) ---------------------------------

def test_the_pattern_rung_names_why_it_declined(box, app):
    """It used to return False for three different reasons; the result could
    only say 'returned without delivering'."""
    import dataclasses

    import pytest

    from ghostdriver.backends.windows.elements import (
        ElementError,
        act_via_pattern,
        walk_elements,
    )
    from ghostdriver.backends.windows.enumerate import enumerate_process
    from ghostdriver.model.window import select_main_tree

    tree = select_main_tree(enumerate_process(app["pid"]))
    tabs = next(n for n in tree.walk() if n.class_name == "SysTabControl32")
    tab = next(e for e, _ in walk_elements(tabs) if e.name == "Components")

    no_pattern = dataclasses.replace(tab, patterns=("Value",))
    with pytest.raises(ElementError, match=r"publishes none of .* \(it publishes: Value\)"):
        act_via_pattern(no_pattern)

    gone = dataclasses.replace(tab, runtime_id=(42, 4242, 424242))
    with pytest.raises(ElementError, match="no longer on the accessibility surface"):
        act_via_pattern(gone)


def test_a_declined_pattern_rung_s_reason_reaches_the_result(box, app):
    """Through the ladder: the rung's message is the click's `declined`."""
    from ghostdriver.actuate import Actuator, Attempt, Tier
    from ghostdriver.backends.windows.elements import ElementError

    def rung():
        raise ElementError("the element publishes none of SelectionItem, Invoke (it publishes: none)")

    result = Actuator(tiers=(Tier.UIA_PATTERN,)).perform([Attempt(Tier.UIA_PATTERN, rung)])

    assert "publishes none of" in result.declined["tier 1"]
