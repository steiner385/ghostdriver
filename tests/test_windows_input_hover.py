"""The posted hover (#133): CM_MOUSEENTER goes out first, and only when
asked. Proven at the message level by recording what would be posted; no
window is needed, because nothing here reads one.
"""

import pytest

from tests.conftest import on_windows

pytestmark = on_windows


@pytest.fixture
def posted(monkeypatch):
    from ghostdriver.backends.windows import input as win_input

    log: list[tuple[int, int]] = []

    def record(hwnd, msg, wparam, lparam):
        log.append((int(msg), int(wparam)))
        return 1

    monkeypatch.setattr(win_input.user32, "PostMessageW", record)
    return win_input, log


def test_hover_posts_the_mouse_enter_notification_before_the_pair(posted):
    win_input, log = posted

    assert win_input.post_click(0x1234, 3, 4, hover=True) is True

    assert [m for m, _ in log] == [win_input.CM_MOUSEENTER, win_input.WM_MOUSEMOVE,
                                   win_input.WM_LBUTTONDOWN, win_input.WM_LBUTTONUP]
    assert log[0] == (win_input.CM_MOUSEENTER, 0), "no flags ride on the notification"


def test_without_hover_the_sequence_is_exactly_as_before(posted):
    win_input, log = posted

    win_input.post_click(0x1234, 3, 4)

    assert [m for m, _ in log] == [win_input.WM_MOUSEMOVE, win_input.WM_LBUTTONDOWN,
                                   win_input.WM_LBUTTONUP]


def test_the_notification_is_the_vcl_value(posted):
    win_input, _ = posted
    assert win_input.CM_MOUSEENTER == 0xB000 + 19
