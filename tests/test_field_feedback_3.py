"""The third field report (D65), each item proven on the fixture.

Consent lost twice mid-work with no error at the moment of loss; a
regex with a space refused; a wait ceiling below the screen's render
time; a copy the tool could trigger and not read; a refusal that named
no tier; coordinates converted by hand.
"""

import json
import subprocess
import sys
import time

import psutil
import pytest

from ghostdriver.consent import ConsentStore
from ghostdriver.model.locator import Locator
from ghostdriver.model.result import GhostdriverError
from ghostdriver.policy import ConsentSource, Tier
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox
from tests.conftest import on_windows

pytestmark = on_windows


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


def session_for(pid, tier=Tier.INTERACTIVE, store=None):
    box = Toolbox(SessionManager(store=store or ConsentStore(None)))
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    return box, box.sessions.attach(pid, command_line=["fixtureapp"], tier=tier).session_id


# --- 1. consent kept while the target lives -------------------------------------------

def test_a_decision_outlives_the_server_run_that_recorded_it(app, tmp_path):
    store = ConsentStore(tmp_path / "consent")
    first = SessionManager(store=store)
    first.record_grant(app["pid"], allowed=True, source=ConsentSource.ELICITED,
                       note="approved in chat")

    second = SessionManager(store=store)  # a new server run

    kept = second.grant_for(app["pid"])
    assert kept is not None and kept.allowed and kept.restored
    assert "kept from an earlier server run" in kept.describe()
    assert "approved in chat" in kept.describe()


def test_a_kept_decision_dies_with_its_process(tmp_path):
    proc, handles = start()
    store = ConsentStore(tmp_path / "consent")
    SessionManager(store=store).record_grant(
        handles["pid"], allowed=True, source=ConsentSource.ELICITED)
    stop(proc, handles)
    # The venv's python.exe is a launcher; the fixture is its child and
    # outlives the launcher's exit by a moment.
    deadline = time.monotonic() + 5
    while psutil.pid_exists(handles["pid"]) and time.monotonic() < deadline:
        time.sleep(0.05)

    later = SessionManager(store=store)

    assert later.grant_for(handles["pid"]) is None
    assert not list((tmp_path / "consent").glob("*.json")), "the stale entry is dropped"


def test_a_restriction_is_kept_too(app, tmp_path):
    store = ConsentStore(tmp_path / "consent")
    SessionManager(store=store).record_grant(
        app["pid"], allowed=False, source=ConsentSource.OPERATOR_TOOL)

    kept = SessionManager(store=store).grant_for(app["pid"])

    assert kept is not None and not kept.allowed and kept.restored


def test_a_lost_session_is_told_which_run_opened_it(tmp_path, monkeypatch):
    from ghostdriver.operator import ENV_VAR

    ops = tmp_path / "ops"
    (ops / "logs").mkdir(parents=True)
    (ops / "logs" / "ghostdriver-20260903-99999.jsonl").write_text(json.dumps({
        "at": time.time() - 60, "tool": "attach", "session_id": "deadbeef0001",
        "args": {"pid": 4242, "tier": "interactive"}, "ok": True,
    }) + "\n", encoding="utf-8")
    monkeypatch.setenv(ENV_VAR, str(ops))

    with pytest.raises(GhostdriverError) as refused:
        SessionManager(store=ConsentStore(None)).get("deadbeef0001")

    message = str(refused.value)
    assert "earlier server run" in message and "attach(pid=4242" in message


# --- 7 and 8. the messages that cost a round trip --------------------------------

def test_a_refusal_names_the_tier_that_permits(app):
    box, session = session_for(app["pid"])

    refused = box.probe_grid(session, "class=GhostFixtureDataGrid")

    assert not refused["ok"]
    assert "needs tier 'full'" in refused["error"]["message"]


def test_an_unquoted_regex_with_spaces_is_one_token():
    parsed = Locator.parse("text=/Work Order/")

    assert "Work Order" in repr(parsed)
    assert "Work Order" in repr(Locator.parse("text=/Work Order/ within=(class=TPanel)"))
    with pytest.raises(ValueError, match="must be quoted"):
        Locator.parse("text=Work Order")


def test_find_says_the_display_scale_when_there_is_one(app):
    from ghostdriver.backends.windows import winapi

    box, session = session_for(app["pid"])

    found = box.find(session, "class=Static")

    if winapi.display_scale() == 1.0:
        assert "display_scale" not in found
    else:
        assert found["display_scale"] == winapi.display_scale()
        assert "logical pixels" in found["coordinates"]


# --- 6. a longer wait, and a capture kept on disk ------------------------------------

def test_wait_for_takes_a_long_ceiling_and_says_what_it_used(app):
    box, session = session_for(app["pid"])

    waited = box.wait_for(session, "class=Static", timeout_s=1000)

    assert waited["ok"] and waited["timeout_s"] == 300.0


def test_capture_can_be_kept_under_the_operator_directory(app, tmp_path, monkeypatch):
    from ghostdriver.operator import ENV_VAR

    ops = tmp_path / "ops"
    ops.mkdir()
    monkeypatch.setenv(ENV_VAR, str(ops))
    box, session = session_for(app["pid"])

    shot = box.capture(session, save_as="evidence-01")

    assert shot["ok"], shot
    saved = ops / "captures" / "evidence-01.png"
    assert shot["saved_to"] == str(saved) and saved.read_bytes()[:4] == b"\x89PNG"


def test_capture_refuses_a_path_as_a_name(app, tmp_path, monkeypatch):
    from ghostdriver.operator import ENV_VAR

    monkeypatch.setenv(ENV_VAR, str(tmp_path))
    box, session = session_for(app["pid"])

    shot = box.capture(session, save_as="../elsewhere")

    assert shot["ok"] and shot["saved_to"] is None and "file name" in shot["save_error"]


# --- 5. the clipboard read -----------------------------------------------------------

def test_read_clipboard_returns_what_the_target_copied(app):
    from ghostdriver.backends.windows.grid import write_clipboard_text

    box, session = session_for(app["pid"])
    write_clipboard_text("PART-0001\tBracket, upper\tEA\t12")
    try:
        got = box.read_clipboard(session)
    finally:
        write_clipboard_text("")

    assert got["ok"] and got["text"] == "PART-0001\tBracket, upper\tEA\t12"
    assert not got["empty"] and "shared with the person" in got["caution"]


def test_read_clipboard_needs_the_interactive_tier(app):
    box, session = session_for(app["pid"], tier=Tier.READ_ONLY)

    refused = box.read_clipboard(session)

    assert not refused["ok"] and "needs tier 'interactive'" in refused["error"]["message"]
