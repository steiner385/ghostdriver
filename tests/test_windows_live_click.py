"""The real-input click guard (#124, D#111): a person's click on the
operator's own display, stopped the instant their desktop moves.

The guard is a function of injected samplers, so it is proven here without
a desktop, a foreground change or a pointer. The module needs the Win32
binding to import, so it is Windows-only; the import is inside each test.
"""

import pytest

from tests.conftest import on_windows

pytestmark = on_windows

LIVE = 0x1234


def _live():
    from ghostdriver.backends.windows.live import LiveActuationAborted, click_real
    return click_real, LiveActuationAborted


def harness(*, foreground=LIVE, cursors=((10, 10),), root=LIVE):
    calls: list = []
    cursor_iter = iter(cursors)
    last = {"c": cursors[-1]}

    def cursor_now():
        try:
            last["c"] = next(cursor_iter)
        except StopIteration:
            pass
        return last["c"]

    kw = dict(
        foreground=lambda: foreground,
        cursor_now=cursor_now,
        root=lambda hwnd: root,
        place=lambda x, y: calls.append(("place", x, y)) or True,
        press=lambda button, count: calls.append(("press", button, count)) or True,
    )
    return calls, kw


def test_it_places_the_pointer_presses_and_puts_the_pointer_back():
    click_real, _ = _live()
    calls, kw = harness(cursors=[(10, 10), (10, 10), (300, 200)])

    ok = click_real(77, (300, 200), live_window=LIVE, button="left", count=2, **kw)

    assert ok is True
    assert calls == [("place", 300, 200), ("press", "left", 2), ("place", 10, 10)]


def test_a_foreground_change_aborts_before_the_pointer_is_touched():
    click_real, Aborted = _live()
    calls, kw = harness(foreground=0x9999)

    with pytest.raises(Aborted, match="foreground window changed"):
        click_real(77, (300, 200), live_window=LIVE, **kw)
    assert calls == []


def test_a_pointer_move_after_placement_aborts_before_the_press():
    click_real, Aborted = _live()
    # baseline, guard-before-place ok, then the person moved it off the point
    calls, kw = harness(cursors=[(10, 10), (10, 10), (55, 55)])

    with pytest.raises(Aborted, match="pointer moved"):
        click_real(77, (300, 200), live_window=LIVE, **kw)
    assert calls == [("place", 300, 200)], "placed, never pressed"


def test_no_live_window_means_no_real_input_at_all():
    click_real, Aborted = _live()
    calls, kw = harness()
    with pytest.raises(Aborted, match="no live window"):
        click_real(77, (1, 1), live_window=0, **kw)
    assert calls == []


def test_a_control_outside_the_consented_window_is_refused():
    click_real, Aborted = _live()
    calls, kw = harness(root=0x4444)
    with pytest.raises(Aborted, match="not the live window"):
        click_real(77, (1, 1), live_window=LIVE, **kw)
    assert calls == []


def test_an_unknown_button_is_refused_not_guessed():
    click_real, Aborted = _live()
    calls, kw = harness()
    with pytest.raises(Aborted, match="no 'x1' button"):
        click_real(77, (1, 1), live_window=LIVE, button="x1", **kw)
    assert calls == []
