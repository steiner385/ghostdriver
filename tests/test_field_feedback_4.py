"""The fourth field report (D66), each item proven on the fixture.

A click on a panel over a windowed child reported delivered and did
nothing; a control that answered "" and rendered content was reported
as a failed write; a frozen application was reported healthy; a wait
that died with the server left no trace; coordinates read off a
physical screenshot had to be converted by hand; `enabled=` and
`handle=` were refused although every result reports both.
"""

import ctypes
import json
import subprocess
import sys
import threading
import time
from ctypes import wintypes

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
ROW_1_SELECTED = {"locator": 'class=Static text="/last=grid row=1$/"'}
WM_LBUTTONUP = 0x0202


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


def session_for(pid, tier=Tier.INTERACTIVE):
    box = Toolbox(SessionManager(store=ConsentStore(None)))
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    return box, box.sessions.attach(pid, command_line=["fixtureapp"], tier=tier).session_id


# --- 2. a click goes to the window under the point -------------------------------------

def test_a_click_on_a_panel_reaches_the_windowed_child_under_the_point(app):
    """The page is a panel; Apply is a window of its own on it, at (12, 12)
    to (122, 38). A click posted to the page over Apply used to be dropped."""
    box, session = session_for(app["pid"])
    page = f"handle=0x{app['pages'][0]:08X}"

    result = box.click(session, page, at={"x": 60, "y": 25},
                       expect={"locator": 'class=Static text="/last=Apply$/"'})

    assert result["ok"], result
    assert result["delivered_to"]["class"] == app["button_class"]
    assert result["delivered_to"]["at"] == {"x": 48, "y": 13}


def test_a_click_with_nothing_under_the_point_says_nothing_about_delivery(app):
    box, session = session_for(app["pid"])

    result = box.click(session, GRID, at=ROW_1, expect=ROW_1_SELECTED)

    assert result["ok"] and "delivered_to" not in result


# --- 3. an empty answer from a control that renders content -----------------------------

def test_read_flags_a_control_that_answers_empty_and_paints_rows(app):
    box, session = session_for(app["pid"])

    grid = box.read(session, GRID)["values"][0]
    label = box.read(session, "class=Static")["values"][0]

    assert grid["text"] == "" and grid["read_unreliable"] is True
    assert grid["rendered_ink"] > 0.02 and "capture" in grid["note"]
    assert "read_unreliable" not in label


# --- 6. a frozen application is reported as one ------------------------------------------

def test_a_hung_window_is_reported_by_modals_and_describe():
    proc, handles = start("--hang-after", "300", "--hang-for", "12")
    try:
        box, session = session_for(handles["pid"])
        time.sleep(6.5)  # the system's verdict takes five seconds of silence

        held = box.modals(session)
        described = box.describe(session)

        assert held["hung_windows"], held
        assert "stopped pumping" in held["hint"]
        assert described["windows"][0]["hung"] is True
    finally:
        stop(proc, handles)


# --- 7. await_human: Later, and a trace of the wait ----------------------------------------

def _post_later(hwnd: int) -> None:
    from ghostdriver.backends.windows.notice import later_rect

    left, top, right, bottom = later_rect(hwnd)
    x, y = (left + right) // 2, (top + bottom) // 2
    ctypes.windll.user32.PostMessageW(wintypes.HWND(hwnd), WM_LBUTTONUP, 0,
                                      (y << 16) | (x & 0xFFFF))


def test_later_on_the_notice_defers_the_ask():
    from ghostdriver.backends.windows.notice import OperatorNotice

    with OperatorNotice("Please sign in") as shown:
        assert shown.hwnd and not shown.deferred
        _post_later(shown.hwnd)
        deadline = time.monotonic() + 2
        while not shown.deferred and time.monotonic() < deadline:
            time.sleep(0.05)
        assert shown.deferred


def test_await_human_returns_deferred_when_the_person_chooses_later(app):
    from ghostdriver.backends.windows.notice import CLASS_NAME

    box, session = session_for(app["pid"])
    outcome: dict = {}

    def wait():
        outcome.update(box.await_human(session, ask="Please sign in",
                                       until={"locator": "class=NoSuchWindow"},
                                       timeout_s=20))

    worker = threading.Thread(target=wait)
    worker.start()
    find = ctypes.windll.user32.FindWindowW
    find.restype = wintypes.HWND
    hwnd = 0
    deadline = time.monotonic() + 5
    while not hwnd and time.monotonic() < deadline:
        hwnd = find(CLASS_NAME, None) or 0
        time.sleep(0.05)
    assert hwnd, "the notice never appeared"
    time.sleep(0.2)
    _post_later(hwnd)
    worker.join(timeout=10)

    assert not worker.is_alive()
    assert outcome["deferred"] is True and outcome["error"]["kind"] == "deferred"
    assert outcome["notice_shown"] is True and outcome["waited_ms"] < 10000


def test_a_wait_is_traced_when_it_begins(tmp_path, monkeypatch):
    from ghostdriver.trace import ENV_VAR, read

    path = tmp_path / "trace.jsonl"
    monkeypatch.setenv(ENV_VAR, str(path))
    box = Toolbox(SessionManager(store=ConsentStore(None)))

    box.wait_for("nope", "class=Static")

    events = read(path)
    assert events[0]["tool"] == "wait_for" and events[0]["phase"] == "began"
    assert events[1]["tool"] == "wait_for" and events[1]["ok"] is False


def test_a_lost_session_says_what_the_person_was_asked(tmp_path, monkeypatch):
    from ghostdriver.model.result import GhostdriverError
    from ghostdriver.operator import ENV_VAR

    ops = tmp_path / "ops"
    (ops / "logs").mkdir(parents=True)
    lines = [
        {"at": time.time() - 90, "tool": "attach", "session_id": "deadbeef0002",
         "args": {"pid": 4242, "tier": "interactive"}, "ok": True},
        {"at": time.time() - 60, "tool": "await_human", "phase": "began",
         "session_id": "deadbeef0002", "args": {"ask": "Please sign in"}},
    ]
    (ops / "logs" / "ghostdriver-20260903-99998.jsonl").write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    monkeypatch.setenv(ENV_VAR, str(ops))

    with pytest.raises(GhostdriverError) as refused:
        SessionManager(store=ConsentStore(None)).get("deadbeef0002")

    assert "await_human" in str(refused.value) and "Please sign in" in str(refused.value)


# --- 8. a point read off a physical screenshot --------------------------------------------

def test_at_can_be_given_in_physical_pixels(app):
    from ghostdriver.backends.windows import winapi

    scale = winapi.display_scale()
    box, session = session_for(app["pid"])

    result = box.click(session, GRID, frame="physical",
                       at={"x": round(30 * scale), "y": round(25 * scale)},
                       expect=ROW_1_SELECTED)

    assert result["ok"], result
    assert result["at"] == (30, 25), "converted back into this tool's frame"


# --- 9. enabled= and handle= -----------------------------------------------------------------

def test_enabled_and_handle_are_locator_keys(app):
    box, session = session_for(app["pid"])

    buttons = box.find(session, f"class={app['button_class']} enabled=true")
    shell = box.find(session, f"handle=0x{app['main']:08X}")

    assert buttons["match_count"] >= 1
    assert shell["match_count"] == 1 and shell["elements"][0]["class"] == "GhostFixtureShell"
