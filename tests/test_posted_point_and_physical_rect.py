"""What a result says about where a click went and where a rectangle is (G#3).

The 10/29 Outlook miss could not be read back from its trace: the trace kept
neither the point the click was posted to nor anything that showed the
window's monitor. And `physical_rect` on that monitor was logical x 1.25,
which was not where the window was. Backend-free: the backend is stood in,
so these run on any platform.
"""

from types import SimpleNamespace

import pytest

from ghostdriver import backends
from ghostdriver.model.element import AccessibleElement
from ghostdriver.tools import Toolbox
from ghostdriver.tools.core import _physical


def backend(monkeypatch, **winapi):
    stand_in = SimpleNamespace(winapi=SimpleNamespace(**winapi),
                               deepest_child_at=lambda h, x, y: (h, x, y))
    monkeypatch.setattr(backends, "current", lambda: stand_in)
    return stand_in


# --- physical_rect -------------------------------------------------------------

def test_physical_rect_is_null_where_no_conversion_is_known(monkeypatch):
    """Null, not absent: absent means the display is unscaled (D73)."""
    backend(monkeypatch, to_physical_rect=lambda rect: None)
    assert _physical((1930, 430, 3130, 1078)) == {"physical_rect": None}


def test_physical_rect_is_absent_at_scale_one(monkeypatch):
    backend(monkeypatch, to_physical_rect=lambda rect: {
        "left": 1, "top": 2, "right": 3, "bottom": 4, "scale": 1.0})
    assert _physical((1, 2, 3, 4)) == {}


def test_physical_rect_is_given_when_scaled(monkeypatch):
    physical = {"left": 125, "top": 0, "right": 250, "bottom": 50, "scale": 1.25}
    backend(monkeypatch, to_physical_rect=lambda rect: physical)
    assert _physical((100, 0, 200, 40)) == {"physical_rect": physical}


def test_physical_rect_on_a_backend_without_it_is_absent(monkeypatch):
    def unbuilt(rect):
        raise backends.UnsupportedPlatform("not built")

    backend(monkeypatch, to_physical_rect=unbuilt)
    assert _physical((0, 0, 1, 1)) == {}


# --- posted_point ---------------------------------------------------------------

DRAFTS = (1997, 430, 2185, 455)


@pytest.fixture
def delivery(monkeypatch):
    backend(monkeypatch, screen_to_client=lambda host, p: (p[0] - 1919, p[1] + 1),
            client_centre=lambda host: (50, 10), class_name=lambda h: "Child")
    session = SimpleNamespace(run=lambda f: f())

    def deliver(node, point=None):
        return Toolbox._delivery(None, SimpleNamespace(node=node, session=session), point)
    return deliver


def element() -> AccessibleElement:
    return AccessibleElement(
        runtime_id=(1,), control_type="TreeItem", name="Drafts", automation_id="",
        class_name="", rect=DRAFTS, enabled=True, offscreen=False, patterns=(),
        host_handle=0x6075A, host_class="Chrome_WidgetWin_1")


def test_a_click_posted_to_the_host_itself_records_its_point(delivery):
    """The measured case: posted to the host, no child under the point."""
    result = delivery(element())
    assert result == {"posted_point": {"handle_ephemeral": "0x0006075A",
                                       "client": {"x": 172, "y": 443},
                                       "screen": {"x": 2091, "y": 442}}}


def test_an_offset_click_records_the_offset_point(delivery):
    result = delivery(element(), point=(10, 5))
    assert result["posted_point"]["screen"] == {"x": 2007, "y": 435}


def test_a_window_click_records_its_client_point(delivery):
    node = SimpleNamespace(handle=0x10, rect=(0, 0, 100, 20))
    assert delivery(node) == {"posted_point": {"handle_ephemeral": "0x00000010",
                                               "client": {"x": 50, "y": 10}}}


def test_a_descent_still_says_delivered_to(delivery, monkeypatch):
    backends.current().deepest_child_at = lambda h, x, y: (0x99, 3, 4)
    result = delivery(element())
    assert result["posted_point"]["handle_ephemeral"] == "0x00000099"
    assert result["delivered_to"]["at"] == {"x": 3, "y": 4}


def test_the_trace_keeps_the_posted_point():
    from ghostdriver.tools import _result_summary

    kept = _result_summary({"ok": True, "posted_point": {"client": {"x": 1, "y": 2}}})
    assert kept == {"posted_point": {"client": {"x": 1, "y": 2}}}
