"""A posted click on a Chromium host on a monitor at another scale is refused (G#3).

Measured: Outlook (WebView2) maximized on a 100% monitor beside a 125%
primary, with the server DPI-unaware. The Drafts rectangle was right, the
conversion was right, and the posted click opened Notes. At two restored
positions on the same monitor it opened Drafts, and an Edge window there
missed at one restored position and not at another. The monitor's dpi is
stood in here, so what is checked is the decision, with nothing clicked.
The last tests ask Windows for real: on a single-monitor machine the
monitor is at the system scale, which is why nothing is refused there.
"""

from types import SimpleNamespace

import pytest

from ghostdriver.model.element import AccessibleElement
from tests.conftest import on_windows

pytestmark = on_windows

WINDOW = (1912, -8, 3848, 1040)
#: Drafts, from the maximized measurement.
DRAFTS = (1997, 430, 2185, 455)


def element(host_class: str) -> AccessibleElement:
    return AccessibleElement(
        runtime_id=(1, 2), control_type="TreeItem", name="Drafts", automation_id="",
        class_name="", rect=DRAFTS, enabled=True, offscreen=False,
        patterns=("SelectionItem",), host_handle=0x1234, host_class=host_class)


@pytest.fixture
def posted(monkeypatch):
    from ghostdriver.backends.windows import elements, winapi

    sent = []
    monkeypatch.setattr(winapi, "root_window", lambda hwnd: hwnd)
    monkeypatch.setattr(winapi, "window_rect", lambda hwnd: WINDOW)
    monkeypatch.setattr(elements, "user32", SimpleNamespace(ScreenToClient=lambda h, p: True))
    monkeypatch.setattr(elements, "deepest_child_at", lambda h, x, y: (h, x, y))
    monkeypatch.setattr(elements, "post_click",
                        lambda h, x, y, **kw: sent.append((x, y)) or True)
    return sent


def monitor_at(monkeypatch, dpi):
    from ghostdriver.backends.windows import winapi

    monkeypatch.setattr(winapi, "window_monitor_dpi", lambda hwnd: dpi)


@pytest.mark.parametrize("host", ["Chrome_WidgetWin_1", "Chrome_RenderWidgetHostHWND"])
def test_the_measured_monitor_is_refused_by_name(host, posted, monkeypatch):
    from ghostdriver.backends.windows import elements

    monitor_at(monkeypatch, (96, 120))
    with pytest.raises(elements.ElementError, match="G#3") as raised:
        elements.click_posted(element(host))
    assert "96 dpi" in str(raised.value) and "120 dpi" in str(raised.value)
    assert posted == [], "nothing was posted"


def test_a_monitor_scaled_above_the_system_is_refused_too(posted, monkeypatch):
    from ghostdriver.backends.windows import elements

    monitor_at(monkeypatch, (144, 96))
    with pytest.raises(elements.ElementError, match="G#3"):
        elements.click_posted(element("Chrome_WidgetWin_1"))
    assert posted == []


@pytest.mark.parametrize("dpi", [(120, 120), (96, 96), None])
def test_a_monitor_at_the_system_scale_or_unknown_is_clicked(dpi, posted, monkeypatch):
    from ghostdriver.backends.windows import elements

    monitor_at(monkeypatch, dpi)
    assert elements.click_posted(element("Chrome_WidgetWin_1"))
    assert posted == [(2091, 442)]


def test_a_native_host_is_not_refused_on_another_scale(posted, monkeypatch):
    """Unmeasured, not cleared: only Chromium hosts were seen missing."""
    from ghostdriver.backends.windows import elements

    monitor_at(monkeypatch, (96, 120))
    assert elements.click_posted(element("SysTreeView32"))
    assert len(posted) == 1


def test_the_window_guard_no_longer_advises_maximizing(posted, monkeypatch):
    """Maximized was the state that missed (G#3)."""
    from ghostdriver.backends.windows import elements, winapi

    monkeypatch.setattr(winapi, "window_rect", lambda hwnd: (2400, 150, 2820, 790))
    with pytest.raises(elements.ElementError) as raised:
        elements.click_posted(element("Chrome_WidgetWin_1"))
    assert "maximized" not in str(raised.value)


def test_physical_rect_is_unknown_on_another_scale(monkeypatch):
    from ghostdriver.backends.windows import winapi

    monkeypatch.setattr(winapi, "rect_monitor_dpi", lambda rect: (96, 120))
    assert winapi.to_physical_rect((1930, 430, 3130, 1078)) is None
    monkeypatch.setattr(winapi, "rect_monitor_dpi", lambda rect: (120, 120))
    monkeypatch.setattr(winapi, "display_scale", lambda: 1.25)
    assert winapi.to_physical_rect((0, 0, 100, 40))["right"] == 125


# --- the real call ------------------------------------------------------------

def test_windows_answers_the_dpi_of_the_primary_monitor():
    """The bindings work, and the answer is not the unaware process's 96 by
    construction: the monitor and the system agree on the primary."""
    from ghostdriver.backends.windows import winapi

    dpi = winapi.rect_monitor_dpi((0, 0, 10, 10))
    assert dpi is not None, "Windows 10 1607 or later answers this"
    monitor, system = dpi
    assert monitor >= 96 and system >= 96
    assert monitor == system
    assert winapi.window_monitor_dpi(winapi.user32.GetDesktopWindow()) == dpi


def test_the_thread_is_left_dpi_unaware():
    """The per-monitor context is set for the question and put back."""
    import ctypes

    from ghostdriver.backends.windows import winapi

    get = winapi.user32.GetThreadDpiAwarenessContext
    get.restype = ctypes.c_void_p
    awareness = winapi.user32.GetAwarenessFromDpiAwarenessContext
    awareness.argtypes = [ctypes.c_void_p]
    before = awareness(get())
    winapi.rect_monitor_dpi((0, 0, 10, 10))
    assert awareness(get()) == before
