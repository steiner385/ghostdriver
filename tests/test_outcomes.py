"""What a failed actuation *did*, promoted into the verdict (#194, #195).

Backend-free: the actuator's result is built by hand and reported through
the same `_reported` every actuation uses.
"""

from types import SimpleNamespace

import pytest

from ghostdriver.ledger import Outcome
from ghostdriver.model.result import ActionResult
from ghostdriver.model.window import WindowNode
from ghostdriver.operator import ENV_VAR
from ghostdriver.session import Profile, SessionManager
from ghostdriver.tools import Toolbox


@pytest.fixture
def box(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "ops"))
    return Toolbox(SessionManager())


def prepared():
    node = WindowNode(handle=0x10, class_name="TsfDBInputEdit", text="", rect=(0, 0, 10, 10),
                      visible=True, enabled=True, pid=1)
    session = SimpleNamespace(session_id="s", pid=1, profile=Profile())
    return SimpleNamespace(node=node, cadence=SimpleNamespace(name="robot"), session=session)


def missed(**kw):
    base = dict(ok=False, tiers_attempted=[3], routes_attempted=["posted"],
                postcondition_verified=False,
                error={"kind": "postcondition_failed", "message": "none produced the expected result"})
    base.update(kw)
    return ActionResult(**base)


def test_a_window_that_appeared_is_the_outcome_not_a_miss(box):
    result = missed(disturbances=[{"change": "window_appeared", "detail": "Error"},
                                  {"change": "blocked", "detail": "the application is now held by: Error"}])

    reported = box._reported(result, prepared(), "class=TsfCommandButton text=Ok")

    assert reported["ok"] is False, "a named expectation that did not hold did not hold"
    assert reported["outcome"] == "delivered_raised_window"
    assert reported["raised"] == ["Error"]
    assert reported["error"]["message"].startswith("delivered, and a window appeared (Error)")
    assert "modals" in reported["error"]["message"]


def test_a_delivered_click_that_changed_nothing_names_the_routes_left(box):
    reported = box._reported(missed(), prepared(), "class=TsfDBInputEdit index=3")

    assert reported["outcome"] == "delivered_no_effect"
    assert reported["no_effect_count"] == 1
    message = reported["error"]["message"]
    assert message.startswith("Delivered to the control and nothing changed")
    assert "f4" in message and "f2" in message and "await_human" in message
    assert "computer-use" not in message and "real input" not in message


def test_the_grid_cell_editor_is_a_check_not_a_promise(box):
    """D#199: whether a cell edits through a window is the grid's property.

    The clause promised one ("the editor window it shows") on a cell that
    then took neither posted keys nor real ones. It now says how to find
    out, and what each of the two answers means -- including that the
    second one ends the attempt rather than inviting more keys.
    """
    reported = box._reported(missed(), prepared(), "class=TsfDBInputEdit index=3")
    message = reported["error"]["message"]

    assert "the editor window it shows" not in message, "that was the promise"
    assert "f2" in message and "count=2" in message, "the check is still named"
    assert "If one appeared" in message and "If nothing appeared" in message, (
        "both answers, or the caller has to guess which one they got")
    assert "capture" in message and "the application's own interface" in message
    assert "do not keep trying keys" in message


def test_the_second_inert_delivery_of_the_same_action_says_so(box):
    locator = "class=TsfDBInputEdit index=3"
    for _ in range(2):
        box.sessions.ledger.record("s", Outcome(locator=locator, tool="click",
                                                cadence="robot", ok=False,
                                                action="left x1 at=(10, 10)"))

    reported = box._reported(missed(), prepared(), locator)

    assert reported["no_effect_count"] == 2
    assert reported["error"]["message"].startswith("This is delivery #2 of this same action")


def test_a_different_action_on_the_same_control_is_not_counted_as_a_repeat(box):
    """Two left clicks at different points and then a right-click were
    reported as 'delivery #3 ... will not act on a retry' (#240)."""
    locator = "class=TSfHypertextEditBox.UnicodeClass"
    for action in ("left x1 at=(40, 60)", "left x1 at=(40, 90)", "right x1 at=(40, 120)"):
        box.sessions.ledger.record("s", Outcome(locator=locator, tool="click",
                                                cadence="robot", ok=False, action=action))

    reported = box._reported(missed(), prepared(), locator)

    assert reported["no_effect_count"] == 1
    assert not reported["error"]["message"].startswith("This is delivery")


def test_a_route_that_never_delivered_is_not_called_inert(box):
    result = missed(declined={"posted": "returned without delivering"})
    reported = box._reported(result, prepared(), "class=X")
    assert "outcome" not in reported


def test_a_miss_with_other_changes_keeps_the_plain_suffix(box):
    result = missed(disturbances=[{"change": "took_foreground", "detail": "Main"}])
    reported = box._reported(result, prepared(), "class=X")
    assert "outcome" not in reported
    assert "1 other change(s)" in reported["error"]["message"]


def test_a_success_carries_no_outcome(box):
    result = ActionResult(ok=True, tier_used=3, routes_attempted=["posted"], tiers_attempted=[3])
    reported = box._reported(result, prepared(), "class=X")
    assert "outcome" not in reported and "error" not in reported


# --- {changed: true} sees a window appear (#194) --------------------------------

class Desktop:
    def __init__(self):
        self.digest = "a"
        self.windows = {0x10: "Main"}
        self.blocked = ()

    def snapshot(self, pid):
        return SimpleNamespace(windows=dict(self.windows), blocked_by=self.blocked, alive=True)


def test_changed_holds_when_a_top_level_window_appears(box, monkeypatch):
    desk = Desktop()
    monkeypatch.setattr(box, "surfaces", lambda sid, all_windows=False: {"shape_digest": desk.digest})
    monkeypatch.setattr("ghostdriver.backends.current", lambda: SimpleNamespace(snapshot=desk.snapshot))
    session = SimpleNamespace(session_id="s", pid=1, run=lambda f: f())

    condition, described = box._expectation(session, {"changed": True})

    assert described == "the target's surface changed"
    assert condition.holds() is False, "nothing moved yet"
    desk.windows[0x20] = "Error"          # a dialog: the digest is unchanged
    assert condition.holds() is True


def test_changed_holds_when_the_target_becomes_held(box, monkeypatch):
    desk = Desktop()
    monkeypatch.setattr(box, "surfaces", lambda sid, all_windows=False: {"shape_digest": desk.digest})
    monkeypatch.setattr("ghostdriver.backends.current", lambda: SimpleNamespace(snapshot=desk.snapshot))
    session = SimpleNamespace(session_id="s", pid=1, run=lambda f: f())

    condition, _ = box._expectation(session, {"changed": True})
    desk.blocked = ("Error",)
    assert condition.holds() is True


def test_the_function_keys_are_named_keys():
    import sys

    if sys.platform == "win32":
        from ghostdriver.backends.windows.input import NAMED_KEYS
        assert NAMED_KEYS["f2"] == 0x71 and NAMED_KEYS["f4"] == 0x73
