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
