"""The real-input click guard (#124, #130, D#111): a click with the
operator's pointer, on their own display, stopped the instant their desktop
moves -- and never stopped by its own placement.

The guard is a function of injected samplers, so it is proven here without
a desktop. The module needs the Win32 binding to import, so it is
Windows-only; the import is inside each test.
"""

import pytest

from tests.conftest import on_windows

pytestmark = on_windows

LIVE = 0x1234


def _live():
    from ghostdriver.backends.windows.live import LiveActuationAborted, click_real
    return click_real, LiveActuationAborted


class Desk:
    """A fake desktop: the foreground window, the pointer, and what the
    rung did to them. `place` moves the pointer exactly unless `clamp_x`
    caps it, the way a screen edge does."""

    def __init__(self, *, foreground=LIVE, cursor=(10, 10), root=LIVE,
                 raise_works=True, clamp_x=None):
        self.foreground_now = foreground
        self.cursor = cursor
        self.root_of = root
        self.raise_works = raise_works
        self.clamp_x = clamp_x
        self.calls: list = []

    def kw(self):
        return dict(
            foreground=lambda: self.foreground_now,
            cursor_now=lambda: self.cursor,
            root=lambda hwnd: self.root_of,
            raise_window=self.raise_window,
            settle=lambda s: self.calls.append(("settle", s)),
            place=self.place,
            press=lambda button, count: self.calls.append(("press", button, count)) or True,
            post=lambda hwnd, point, button, count: self.calls.append(
                ("post", hwnd, point, button, count)) or True,
        )

    def raise_window(self, hwnd):
        self.calls.append(("raise", hwnd))
        if self.raise_works:
            self.foreground_now = hwnd
        return self.raise_works

    def place(self, x, y):
        self.calls.append(("place", x, y))
        self.cursor = (min(x, self.clamp_x) if self.clamp_x is not None else x, y)
        return True

    def did(self):
        return [c[0] for c in self.calls]


# --- the input route ---------------------------------------------------------

def test_it_places_the_pointer_presses_and_puts_the_pointer_back():
    click_real, _ = _live()
    desk = Desk()

    ok = click_real(77, (300, 200), live_window=LIVE, button="left", count=2, **desk.kw())

    assert ok is True
    assert desk.calls == [("place", 300, 200), ("press", "left", 2), ("place", 10, 10)]


def test_its_own_placement_is_not_a_pointer_move():
    """Attempt 5 in the field: the guard compared the pointer with where it
    asked for it, and a clamped placement read as the operator moving."""
    click_real, _ = _live()
    desk = Desk(clamp_x=302)  # reads back within tolerance

    assert click_real(77, (303, 200), live_window=LIVE, **desk.kw()) is True
    assert "press" in desk.did()


def test_a_placement_that_reads_back_elsewhere_is_named_not_blamed_on_the_operator():
    click_real, Aborted = _live()
    desk = Desk(clamp_x=1536)  # a screen edge; the point is off it

    with pytest.raises(Aborted, match="could not be placed"):
        click_real(77, (1898, 280), live_window=LIVE, **desk.kw())
    assert "press" not in desk.did()
    assert desk.cursor == (10, 10), "the pointer was put back"


def test_a_window_that_lost_the_foreground_to_the_go_ahead_is_brought_back():
    """Attempt 3 in the field: typing 'hands off' in chat moved the
    foreground. The consented window is the one the operator named, so it
    is raised rather than refused."""
    click_real, _ = _live()
    desk = Desk(foreground=0x70BC2)

    assert click_real(77, (300, 200), live_window=LIVE, **desk.kw()) is True
    assert desk.did()[:2] == ["raise", "settle"]
    assert ("raise", LIVE) in desk.calls


def test_a_window_that_cannot_be_raised_is_refused_with_the_reason():
    click_real, Aborted = _live()
    desk = Desk(foreground=0x70BC2, raise_works=False)

    with pytest.raises(Aborted, match="could not be brought to the front"):
        click_real(77, (300, 200), live_window=LIVE, **desk.kw())
    assert "place" not in desk.did() and "press" not in desk.did()


def test_a_pointer_move_after_placement_aborts_before_the_press():
    """Baseline, stillness check, the placement read back where asked --
    then the person moves it before the button goes down."""
    click_real, Aborted = _live()
    desk = Desk()
    reads = iter([(10, 10), (10, 10), (300, 200), (55, 55)])
    kw = desk.kw()
    kw["cursor_now"] = lambda: next(reads)

    with pytest.raises(Aborted, match="pointer moved"):
        click_real(77, (300, 200), live_window=LIVE, **kw)
    assert "press" not in desk.did()


# --- the posted route --------------------------------------------------------

def test_the_posted_route_places_posts_and_needs_no_foreground():
    click_real, _ = _live()
    desk = Desk(foreground=0x70BC2)  # not the live window, and that is fine

    ok = click_real(77, (300, 200), live_window=LIVE, via="posted", **desk.kw())

    assert ok is True
    assert desk.calls == [("place", 300, 200), ("post", 77, (300, 200), "left", 1),
                          ("place", 10, 10)]
    assert "raise" not in desk.did()


# --- refusals with nothing sent -------------------------------------------------

def test_no_live_window_means_no_real_input_at_all():
    click_real, Aborted = _live()
    desk = Desk()
    with pytest.raises(Aborted, match="no live window"):
        click_real(77, (1, 1), live_window=0, **desk.kw())
    assert desk.calls == []


def test_a_control_outside_the_consented_window_is_refused():
    click_real, Aborted = _live()
    desk = Desk(root=0x4444)
    with pytest.raises(Aborted, match="not the live window"):
        click_real(77, (1, 1), live_window=LIVE, **desk.kw())
    assert desk.calls == []


def test_an_unknown_button_or_route_is_refused_not_guessed():
    click_real, Aborted = _live()
    desk = Desk()
    with pytest.raises(Aborted, match="no 'x1' button"):
        click_real(77, (1, 1), live_window=LIVE, button="x1", **desk.kw())
    with pytest.raises(Aborted, match="no real-input route"):
        click_real(77, (1, 1), live_window=LIVE, via="telepathy", **desk.kw())
    assert desk.calls == []
