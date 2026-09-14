"""`await_human` with `settle_s`, and `until` alongside `until_change` (#123).

Backend-free: the surface digest and the resolver are stood in for, so the
wait's logic is proven on any platform; `notice=False` keeps the corner
window out of it.
"""

import os
import time

import pytest

from ghostdriver.operator import ENV_VAR
from ghostdriver.policy import ConsentSource, Tier
from ghostdriver.session import Profile, SessionManager
from ghostdriver.tools import Toolbox
from ghostdriver.tools.human import _SettledChange


@pytest.fixture
def attached(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "ops"))
    box = Toolbox(SessionManager())
    pid = os.getpid()
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    sid = box.sessions.attach(pid, command_line=["pytest"], tier=Tier.READ_ONLY,
                              profile=Profile()).session_id
    return box, sid


class Surface:
    """A surface whose digest follows a script: one entry per read, the
    last one repeated."""

    def __init__(self, *digests):
        self.digests = list(digests)

    def __call__(self, session_id, all_windows=False):
        digest = self.digests.pop(0) if len(self.digests) > 1 else self.digests[0]
        return {"shape_digest": digest}


def wait(box, sid, **kw):
    kw.setdefault("timeout_s", 2.0)
    kw.setdefault("poll_s", 0.01)
    return box.await_human(sid, "do the thing", notice=False, **kw)


# --- the settle clock, on its own ------------------------------------------

def test_without_a_settle_the_first_movement_counts():
    check = _SettledChange(lambda: "a", 0.0, now=lambda: 0.0)
    assert check() is False
    check.read = lambda: "b"
    assert check() is True


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_a_settle_waits_for_the_surface_to_hold_still():
    surface, clock = {"d": "a"}, Clock()
    check = _SettledChange(lambda: surface["d"], 2.0, now=clock)

    surface["d"] = "b"
    assert check() is False, "moved to b at t=0"
    clock.t, surface["d"] = 0.5, "c"
    assert check() is False, "moved again at t=0.5; the still clock restarts"
    clock.t = 1.5
    assert check() is False, "c for 1.0s: not yet"
    clock.t = 3.0
    assert check() is True, "c for 2.5s: settled"


def test_a_surface_that_flickers_back_still_moved():
    surface, clock = {"d": "a"}, Clock()
    check = _SettledChange(lambda: surface["d"], 2.0, now=clock)

    surface["d"] = "b"
    assert check() is False, "b"
    clock.t, surface["d"] = 1.0, "a"
    assert check() is False, "back to a at t=1.0: moved, not yet still"
    clock.t = 5.0
    assert check() is True, "a, still since t=1.0"


# --- through the tool ------------------------------------------------------------

def test_until_change_alone_returns_on_the_first_movement(attached, monkeypatch):
    box, sid = attached
    monkeypatch.setattr(box, "surfaces", Surface("a", "b"))

    result = wait(box, sid, until_change=True)

    assert result["ok"] and result["verified"] is True
    assert result["expected"] == "the target's surface shape changed"


def test_a_settle_holds_the_wait_until_the_surface_is_still(attached, monkeypatch):
    box, sid = attached
    monkeypatch.setattr(box, "surfaces", Surface("a", "b", "c"))

    started = time.monotonic()
    result = wait(box, sid, until_change=True, settle_s=0.2)

    assert result["ok"], result
    assert time.monotonic() - started >= 0.2
    assert "held still for 0.2s" in result["expected"]


def test_until_alongside_until_change_needs_both(attached, monkeypatch):
    """A splash screen is a change; the login window behind it is the one
    that was meant. With a locator alongside, the wait ends only when the
    surface moved AND the control is there."""
    box, sid = attached
    monkeypatch.setattr(box, "surfaces", Surface("a", "b"))
    present = {"login": False}
    monkeypatch.setattr(box, "_resolve",
                        lambda session, where, all_windows: [object()] if present["login"] else [])

    early = wait(box, sid, until_change=True, until="class=TLoginForm", timeout_s=0.1)
    assert not early["ok"] and early["error"]["kind"] == "timeout"
    assert early["expected"] == "the target's surface shape changed and class=TLoginForm exists"

    present["login"] = True
    monkeypatch.setattr(box, "surfaces", Surface("a", "b"))
    late = wait(box, sid, until_change=True, until="class=TLoginForm")
    assert late["ok"] and late["verified"] is True


def test_until_absent_alongside_until_change(attached, monkeypatch):
    box, sid = attached
    monkeypatch.setattr(box, "surfaces", Surface("a", "b"))
    monkeypatch.setattr(box, "_resolve", lambda session, where, all_windows: [])

    result = wait(box, sid, until_change=True, until={"locator": "class=TSplash", "absent": True})

    assert result["ok"]
    assert result["expected"].endswith("class=TSplash is gone")


def test_a_settle_without_until_change_is_refused(attached, monkeypatch):
    box, sid = attached
    monkeypatch.setattr(box, "_resolve", lambda session, where, all_windows: [object()])
    result = wait(box, sid, until="class=X", settle_s=1.0)
    assert not result["ok"] and "settle_s goes with until_change" in result["error"]["message"]
    negative = wait(box, sid, until_change=True, settle_s=-1)
    assert not negative["ok"] and "settle_s" in negative["error"]["message"]
