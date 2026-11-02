"""A posted click is not aimed by a rectangle outside its own window (#257).

Measured on a Chromium host on a monitor at another scale: Row 3 was
reported ending at x=2934 in a window ending at x=2820, and the click aimed
by it landed on Row 4. The window and the posting are stood in here, so
what is checked is the comparison, with nothing clicked on the desktop.
"""

from types import SimpleNamespace

import pytest

from ghostdriver.model.element import AccessibleElement
from tests.conftest import on_windows

pytestmark = on_windows

#: The window from the measurement, as GetWindowRect reported it.
WINDOW = (2400, 150, 2820, 790)


def element(rect) -> AccessibleElement:
    return AccessibleElement(
        runtime_id=(1, 2), control_type="Button", name="Row 3", automation_id="",
        class_name="", rect=rect, enabled=True, offscreen=False,
        patterns=("Invoke",), host_handle=0x1234, host_class="Chrome_RenderWidgetHostHWND")


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


def test_the_measured_rectangle_is_refused_by_name(posted):
    from ghostdriver.backends.windows import elements

    with pytest.raises(elements.ElementError, match="#257") as raised:
        elements.click_posted(element((2530, 332, 2934, 373)))
    assert "not inside its window" in str(raised.value)
    assert posted == [], "nothing was posted"


@pytest.mark.parametrize("rect", [
    (2390, 300, 2500, 340),   # past the left edge
    (2500, 140, 2600, 180),   # above the top
    (2500, 770, 2600, 800),   # cut off at the bottom
])
def test_any_edge_outside_the_window_is_refused(rect, posted):
    from ghostdriver.backends.windows import elements

    with pytest.raises(elements.ElementError, match="#257"):
        elements.click_posted(element(rect))
    assert posted == []


def test_a_rectangle_inside_its_window_is_clicked(posted):
    from ghostdriver.backends.windows import elements

    assert elements.click_posted(element((2410, 332, 2810, 373)))
    assert posted == [(2610, 352)]


def test_a_rectangle_on_the_windows_own_edges_is_inside(posted):
    from ghostdriver.backends.windows import elements

    assert elements.click_posted(element(WINDOW))
    assert len(posted) == 1
