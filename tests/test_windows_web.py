"""An embedded web document, driven through the accessibility surface.

A Chromium engine is launched onto a hidden desktop with the fixture page,
so nothing here can reach the operator's screen, and the session is the
ordinary hidden-desktop kind. Everything then goes through the same tools
and locators as a native target: the region model names the document, the
first question wakes the engine, element locators name its buttons, tabs
and inputs, a posted click on the host drives them, and posted characters
reach the page's own script -- one input event per character, measured.

Skipped where no Chromium engine is installed.
"""

import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

from ghostdriver.session import Profile, SessionManager
from ghostdriver.tools import Toolbox
from tests.conftest import on_windows

pytestmark = [on_windows, pytest.mark.slow]
ENGINES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]
ENGINE = next((e for e in ENGINES if os.path.exists(e)), None)
PAGE = "file:///" + str(Path(__file__).resolve().parent / "fixturepage.html").replace("\\", "/")

needs_engine = pytest.mark.skipif(ENGINE is None, reason="no Chromium engine installed")


@pytest.fixture(scope="module")
def web():
    """One engine, one hidden desktop, one session for the module: an
    engine takes seconds to start, and every test here reads the same page."""
    profile_dir = tempfile.mkdtemp(prefix="gd-web-")
    command = [ENGINE, f"--user-data-dir={profile_dir}", "--no-first-run",
               "--disable-sync", f"--app={PAGE}"]
    box = Toolbox(SessionManager())
    box.sessions.record_launch_grant(command, allowed=True, note="web fixture")
    launched = box.launch_isolated(command, tier="interactive")
    assert launched["ok"], launched
    session = launched["session_id"]
    # The engine's first window is a hidden helper; the real one, with the
    # page, comes seconds later. Ready means the document is on the surface
    # -- and asking for it is what wakes the engine.
    ready = False
    for _ in range(160):
        found = box.find(session, "type=Document")
        if found.get("ok") and found["match_count"]:
            ready = True
            break
        time.sleep(0.25)
    assert ready, "the engine never published its document"
    yield box, session
    box.release(session)
    shutil.rmtree(profile_dir, ignore_errors=True)


def texts(box, session, prefix):
    found = box.find(session, f'type=Text name="/^{prefix}/"')
    return [e["name"] for e in found["elements"]]


# --- the document is reachable ---------------------------------------------

@needs_engine
def test_the_region_model_names_the_document_and_the_first_question_wakes_it(web):
    box, session = web

    found = box.find(session, 'type=Button name="Expand All"')

    assert found["match_count"] == 1, found
    regions = box.surfaces(session)
    web_regions = [r for r in regions["regions_needing_another_mechanism"] if r["kind"] == "web-document"]
    assert web_regions, regions
    assert web_regions[0]["access"] == "accessibility", \
        "awake: the document reads through the accessibility surface"


@needs_engine
def test_page_controls_resolve_by_type_and_name(web):
    box, session = web

    buttons = box.find(session, "type=Button within=(type=Document)")
    tabs = box.find(session, "type=TabItem")

    assert {b["name"] for b in buttons["elements"]} >= {"Expand All", "Complete Task", "Delete Record"}
    assert [t["name"] for t in tabs["elements"]] == ["Operations", "Components", "Change Log"]


# --- acting on it -----------------------------------------------------------------

@needs_engine
def test_a_posted_click_on_the_host_drives_a_page_button(web):
    box, session = web

    result = box.click(session, 'type=Button name="Expand All"',
                       expect={"locator": 'type=Text name="/clicks=1 last=Expand All/"'})

    assert result["ok"], result
    assert result["tier_used"] == 3 and result["verified"] == "effect"


@needs_engine
def test_clicking_an_aria_tab_switches_the_panel(web):
    box, session = web

    result = box.click(session, 'type=TabItem name="Components"',
                       expect={"locator": 'type=Text name="Components page"'})

    assert result["ok"], result
    selected = box.read(session, 'type=TabItem name="Components"')["values"][0]
    assert selected["selected"] is True


@needs_engine
def test_typing_reaches_the_pages_own_script(web):
    """Posted characters go to the host window and the page's input handler
    sees each one. The mirror follows the change event, which the page
    fires on blur -- so the value is checked at once and the commit after
    a tab out, the way a person's edit would land."""
    box, session = web

    replaced = box.set_value(session, 'type=Edit name="Part number"', "PART-0002")
    assert replaced["ok"], replaced
    assert replaced["display"] == "PART-0002"
    assert replaced["tier_used"] == 3, "typed, not set: no commit expectation was given"

    tabbed = box.send_keys(session, 'type=Edit name="Part number"', ["tab"],
                           expect={"locator": 'type=Text name="committed:PART-0002"'})
    assert tabbed["ok"], tabbed
    events = texts(box, session, "events:")
    assert events and events[0] != "events:0", "the script saw the keystrokes"


@needs_engine
def test_the_value_pattern_is_offered_under_a_commit_expectation_and_commits_here(web):
    """Measured on Chromium: SetValue fires the page's input and change
    events, so under a commit expectation tier 1 is taken and verified.
    On the native bridge it would fail the check and fall through (D21)."""
    box, session = web

    result = box.set_value(session, 'type=Edit name="Part number"', "PART-0003",
                           expect={"locator": 'type=Text name="committed:PART-0003"'})

    assert result["ok"], result
    assert result["tier_used"] == 1 and result["verified"] == "committed"


# --- the boundaries hold on the web too ------------------------------------------

@needs_engine
def test_a_web_password_field_is_refused(web):
    box, session = web

    result = box.type_text(session, 'type=Edit name="Password"', "x")

    assert not result["ok"]
    assert result["error"]["kind"] == "denied_by_policy"
    assert "await_human" in result["error"]["message"]


@needs_engine
def test_the_denylist_refuses_a_page_button_by_caption():
    """A separate session on the same engine would need a second launch;
    the denylist check is pure over identities, so it is proven at the
    policy layer here rather than by launching another engine."""
    from ghostdriver.model.element import AccessibleElement
    from ghostdriver.policy import denied

    button = AccessibleElement(
        runtime_id=(1,), control_type="Button", name="Delete Record",
        automation_id="delete", class_name="", rect=(0, 0, 1, 1), enabled=True,
        offscreen=False, patterns=("Invoke",), host_handle=1, host_class="Chrome_WidgetWin_1")

    assert any(denied(i, list(Profile(denylist=("*delete*",)).denylist))
               for i in button.identities())
