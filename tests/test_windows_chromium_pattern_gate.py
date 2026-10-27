"""A pattern call on a Chromium host is declined on the person's desktop (#249).

Measured: every UIA pattern call on a Chromium host brought its window to
the front, and every posted route worked without doing so. What is checked
here is the gate, with the desktop question stood in, so no window has to
take anything for the test to run.
"""

import pytest

from ghostdriver.model.element import AccessibleElement
from tests.conftest import on_windows

pytestmark = on_windows


def element(host_class: str, patterns=("Invoke", "Value")) -> AccessibleElement:
    return AccessibleElement(
        runtime_id=(1, 2), control_type="Button", name="Probe", automation_id="",
        class_name="", rect=(0, 0, 10, 10), enabled=True, offscreen=False,
        patterns=tuple(patterns), host_handle=0, host_class=host_class)


@pytest.fixture
def operator_desktop(monkeypatch):
    from ghostdriver.backends.windows import hidden_desktop

    def on(value: bool):
        monkeypatch.setattr(hidden_desktop, "on_input_desktop", lambda: value)
    return on


@pytest.mark.parametrize("host", ["Chrome_WidgetWin_1", "Chrome_RenderWidgetHostHWND"])
def test_a_chromium_host_on_the_persons_desktop_gets_no_pattern_call(host, operator_desktop):
    from ghostdriver.backends.windows import elements

    operator_desktop(True)
    with pytest.raises(elements.ElementError, match="#249"):
        elements.act_via_pattern(element(host))
    with pytest.raises(elements.ElementError, match="front"):
        elements.set_value_via_pattern(element(host), "x")


def test_a_hidden_desktop_has_no_foreground_to_take(operator_desktop):
    """Past the gate, the call fails for the ordinary reason -- there is no
    such element, host 0 -- which shows the gate let it through."""
    from ghostdriver.backends.windows import elements

    operator_desktop(False)
    with pytest.raises(Exception) as raised:
        elements.act_via_pattern(element("Chrome_WidgetWin_1"))
    assert "#249" not in str(raised.value)


def test_a_native_host_is_not_gated(operator_desktop):
    from ghostdriver.backends.windows import elements

    operator_desktop(True)
    with pytest.raises(Exception) as raised:
        elements.act_via_pattern(element("SysTabControl32"))
    assert "#249" not in str(raised.value)


def test_the_calling_thread_is_on_the_input_desktop_here():
    """The real check, on the thread a test runs on: the default desktop,
    which is the input desktop on a machine someone is using."""
    from ghostdriver.backends.windows.hidden_desktop import on_input_desktop

    assert on_input_desktop() is True


def test_a_desktop_this_server_made_is_nobodys():
    """The hidden desktop a launched target runs on: its thread answers no,
    even where the input desktop cannot be read (a CI service session)."""
    from ghostdriver.backends.windows.hidden_desktop import HiddenDesktop, on_input_desktop

    desktop = HiddenDesktop(name="ghostdriver-gatetest")
    desktop.prepare()
    try:
        assert desktop.run(on_input_desktop) is False
    finally:
        desktop.teardown()
