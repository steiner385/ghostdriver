"""`changed: true` is refused on an action whose effect is text (#248).

`changed` compares the shape digest, the top-level windows and `blocked_by`.
Text typed into an owner-drawn editor that keeps its size moves none of
them, so a `changed` there read `delivered_no_effect` -- and handed a person
a step that had already worked -- on text that landed. Backend-free: the
refusal comes before the resolver, the backend or the ladder is reached, and
the tool tests stand in for `_prepared` and `_perform` to show nothing is
sent.
"""

import pytest

from ghostdriver.operator import ENV_VAR
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox
from ghostdriver.tools.core import _Prepared
from ghostdriver.tools.expect import BLIND_TO_TEXT


class _Node:
    handle = 1
    class_name = "TWPRichText"
    text = ""
    rect = (0, 0, 100, 20)


@pytest.fixture
def box(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "ops"))
    box = Toolbox(SessionManager())
    prepared = _Prepared(session=object(), node=_Node(), cadence=None)
    monkeypatch.setattr(box, "_prepared", lambda *a, **k: (prepared, None))
    monkeypatch.setattr(box, "_refuse_if_protected", lambda *a, **k: None)

    def performed(*a, **k):
        raise AssertionError("an action was sent despite an unusable expect")

    monkeypatch.setattr(box, "_perform", performed)
    return box


def test_changed_is_refused_where_the_action_carries_text(box):
    with pytest.raises(ValueError, match="cannot see text"):
        box._expectation(None, {"changed": True}, carries_text=True)


def test_the_refusal_says_what_to_name_instead():
    assert "`text`" in BLIND_TO_TEXT and "capture" in BLIND_TO_TEXT


@pytest.mark.parametrize("expect", [{"changed": True}, '{"changed": true}',
                                    {"changed": True, "timeout_s": 3}])
def test_type_text_refuses_changed_before_sending(box, expect):
    """The field case: TWPRichText at fast_human, every character landed."""
    result = box.type_text("s", "class=TWPRichText", "hello", expect=expect)

    assert result["ok"] is False
    assert "cannot see text" in result["error"]["message"]
    assert "outcome" not in result


def test_set_value_refuses_changed_before_sending(box):
    result = box.set_value("s", "class=TWPRichText", "hello",
                           expect={"changed": True})

    assert result["ok"] is False
    assert "cannot see text" in result["error"]["message"]


def test_send_keys_with_a_character_refuses_changed(box):
    result = box.send_keys("s", "class=TWPRichText", ["a", "enter"],
                           expect={"changed": True})

    assert result["ok"] is False
    assert "cannot see text" in result["error"]["message"]


def test_send_keys_with_named_keys_alone_keeps_changed(box, monkeypatch):
    """Enter or escape can open or close a window, which `changed` sees: the
    refusal is for text, not for the tool."""
    built = []

    def expectation(session, expect, *, carries_text=False):
        built.append(carries_text)
        raise ValueError("stop here")

    monkeypatch.setattr(box, "_expectation", expectation)
    box.send_keys("s", "class=TWPRichText", ["enter"], expect={"changed": True})

    assert built == [False]
