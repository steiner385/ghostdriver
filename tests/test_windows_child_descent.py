"""Descending into a windowed child does not move the point (#257).

Measured on a monitor at 100% beside a primary at 125%, from this
DPI-unaware server: `ClientToScreen` scaled x by 1.25 and `ScreenToClient`
did not. `deepest_child_at` used to chain the two at every descent, so the
point reached the child moved. The window tree is stood in here, with that
measured disagreement built into it, so nothing is clicked on the desktop.
"""

from types import SimpleNamespace

import pytest

from tests.conftest import on_windows

pytestmark = on_windows

HOST, CHILD = 0x100, 0x200
#: Where each window's client area starts on screen, as ScreenToClient sees it.
ORIGIN = {HOST: (1912, 100), CHILD: (1912, 140)}


def _hwnd(value) -> int:
    return int(getattr(value, "value", value) or 0)


@pytest.fixture
def mixed_dpi(monkeypatch):
    from ghostdriver.backends.windows import input as win_input

    def screen_to_client(hwnd, ref):
        ox, oy = ORIGIN[_hwnd(hwnd)]
        ref._obj.x -= ox
        ref._obj.y -= oy
        return True

    def client_to_screen(hwnd, ref):
        # The measured disagreement: x scaled by the primary's 1.25.
        ox, oy = ORIGIN[_hwnd(hwnd)]
        ref._obj.x = int((ref._obj.x + ox) * 1.25)
        ref._obj.y += oy
        return True

    def child_from_point(hwnd, point, flags):
        # The child covers the host's client area below y=40.
        return CHILD if _hwnd(hwnd) == HOST and point.y >= 40 else None

    monkeypatch.setattr(win_input, "user32", SimpleNamespace(
        ScreenToClient=screen_to_client, ClientToScreen=client_to_screen,
        ChildWindowFromPointEx=child_from_point))
    return win_input


def test_the_point_reaches_the_child_where_it_was_aimed(mixed_dpi):
    # Mail's centre in the measurement: client (34, 76) of the host.
    assert mixed_dpi.deepest_child_at(HOST, 34, 76) == (CHILD, 34, 36)


def test_a_point_over_no_child_stays_with_the_host(mixed_dpi):
    assert mixed_dpi.deepest_child_at(HOST, 34, 20) == (HOST, 34, 20)
