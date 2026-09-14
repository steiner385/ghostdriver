"""`capture(scale=...)` (#120): the argument is checked before any backend is
touched, so the refusals are proven on any platform; the pixels are proven
against the fixture in `tests/test_windows_capture.py`.
"""

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
    sid = box.sessions.attach(pid, command_line=["pytest"], tier=Tier.READ_ONLY,
                              profile=Profile()).session_id
    return box, sid


@pytest.mark.parametrize("bad", [0, -0.5, 1.5, 2, "half", None])
def test_a_scale_outside_the_unit_interval_is_refused_by_name(attached, bad):
    box, sid = attached
    result = box.capture(sid, scale=bad)
    assert not result["ok"], bad
    assert result["error"]["kind"] == "not_actionable"
    assert "scale" in result["error"]["message"] and repr(bad) in result["error"]["message"]
