"""`click(real_input=true)` is refused before anything is resolved unless the
session holds the live grant (#124, D#111). Backend-free."""

import os

import pytest

from ghostdriver.operator import ENV_VAR
from ghostdriver.policy import ConsentSource, Tier
from ghostdriver.session import Profile, SessionManager
from ghostdriver.tools import Toolbox


@pytest.fixture
def attached(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "ops"))
    box = Toolbox(SessionManager())
    pid = os.getpid()
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    sid = box.sessions.attach(pid, command_line=["pytest"], tier=Tier.INTERACTIVE,
                              profile=Profile()).session_id
    return box, sid


def test_real_input_without_a_live_session_is_refused_by_policy(attached):
    box, sid = attached
    result = box.click(sid, "class=THtLeftPanel", real_input=True)
    assert not result["ok"]
    assert result["error"]["kind"] == "denied_by_policy"
    assert "live=true" in result["error"]["message"]


def test_real_input_with_modifiers_is_refused(attached):
    box, sid = attached
    session = box.sessions.get(sid)
    object.__setattr__(session, "live_window", 0x1234)  # frozen dataclass
    result = box.click(sid, "class=X", real_input=True, modifiers=["ctrl"])
    assert not result["ok"] and "modifiers" in result["error"]["message"]


# --- the abort note means an abort (#130) -----------------------------------------

def test_a_postcondition_miss_after_a_delivered_click_is_not_an_abort():
    from ghostdriver.model.result import ActionResult
    from ghostdriver.tools.actuation import _live_abort_note

    missed = ActionResult(ok=False, tier_used=4, route_used="cursor_posted",
                          postcondition_verified=False)
    assert _live_abort_note(missed) is None


def test_a_declined_rung_is_an_abort_with_its_reason():
    from ghostdriver.model.result import ActionResult
    from ghostdriver.tools.actuation import _live_abort_note

    declined = ActionResult(ok=False, declined={"real_input": "the pointer moved while acting"})
    note = _live_abort_note(declined)
    assert note is not None and "real_input: the pointer moved" in note


def test_the_click_point_is_in_the_frame_the_process_sees():
    from types import SimpleNamespace

    from ghostdriver.tools.actuation import _click_point

    node = SimpleNamespace(rect=(12, 217, 44, 826))
    assert _click_point(node, None) == (28, 521)
    assert _click_point(node, (5, 9)) == (17, 226)
