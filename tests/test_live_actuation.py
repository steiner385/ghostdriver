"""The live-actuation guard (D#111): a real keystroke on the operator's own
display, aborted the instant their desktop moves.

Pure: `commit_value`'s desktop calls are injected, so the guard's logic is
tested without a display. The backend that supplies the real samplers is
proven against the target. The import is inside each test so this module
does not bind a platform at collection (tests/test_structure.py).
"""

import pytest


def _commit():
    from ghostdriver.backends.linux.live import LiveActuationAborted, commit_value
    return commit_value, LiveActuationAborted


def test_it_writes_then_presses_enter_when_the_desktop_holds_still():
    commit_value, _ = _commit()
    calls = []
    ok = commit_value(
        99, "0.2", live_window=0x1234,
        active=lambda: 0x1234, cursor=lambda: (10, 10),
        write=lambda h, t: calls.append(("write", h, t)) or True,
        focus=lambda h: calls.append(("focus", h)) or True,
        enter=lambda: calls.append(("enter",)) or True,
    )
    assert ok is True
    assert [c[0] for c in calls] == ["write", "focus", "enter"]


def test_a_foreground_change_before_the_write_aborts_before_touching_anything():
    commit_value, Aborted = _commit()
    calls = []
    with pytest.raises(Aborted, match="foreground window changed"):
        commit_value(
            99, "0.2", live_window=0x1234,
            active=lambda: 0x9999,  # the operator switched away
            cursor=lambda: (10, 10),
            write=lambda h, t: calls.append("write") or True,
            focus=lambda h: calls.append("focus") or True,
            enter=lambda: calls.append("enter") or True,
        )
    assert calls == []  # nothing was sent


def test_a_pointer_move_between_write_and_enter_aborts_before_the_enter():
    commit_value, Aborted = _commit()
    calls = []
    cursors = iter([(10, 10), (10, 10), (55, 55)])  # baseline, after-write ok, moved

    with pytest.raises(Aborted, match="pointer moved"):
        commit_value(
            99, "0.2", live_window=0x1234,
            active=lambda: 0x1234,
            cursor=lambda: next(cursors),
            write=lambda h, t: calls.append("write") or True,
            focus=lambda h: calls.append("focus") or True,
            enter=lambda: calls.append("enter") or True,
        )
    assert "write" in calls and "enter" not in calls  # wrote, never committed


def test_no_live_window_is_refused_outright():
    commit_value, Aborted = _commit()
    with pytest.raises(Aborted, match="no live window"):
        commit_value(99, "0.2", live_window=0,
                     active=lambda: 0, cursor=lambda: (0, 0),
                     write=lambda h, t: True, focus=lambda h: True,
                     enter=lambda: True)


def test_a_declined_write_returns_false_without_pressing_enter():
    commit_value, _ = _commit()
    calls = []
    ok = commit_value(
        99, "0.2", live_window=0x1234,
        active=lambda: 0x1234, cursor=lambda: (0, 0),
        write=lambda h, t: False,  # the editable write did not take
        focus=lambda h: calls.append("focus") or True,
        enter=lambda: calls.append("enter") or True,
    )
    assert ok is False and calls == []
