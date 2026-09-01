import pytest

from tests.conftest import on_windows

pytestmark = on_windows


def test_reads_caption_of_a_cross_process_control(tk_target):
    from ghostdriver.backends.windows.enumerate import enumerate_process
    texts = {n.text for n in enumerate_process(tk_target)[0].walk()}
    assert "Expand All" in texts
    assert "Collapse All" in texts


def test_reads_top_level_window_title(tk_target):
    from ghostdriver.backends.windows.enumerate import enumerate_process
    assert enumerate_process(tk_target)[0].text == "GhostdriverTestWindow"


def test_returns_none_for_a_dead_handle():
    from ghostdriver.backends.windows.text import read_window_text
    assert read_window_text(0xDEADBEEF) is None


def test_distinguishes_empty_text_from_no_answer(tk_target):
    """A control with no caption returns "", not None.

    Collapsing the two would make "the control has no text" and "the target
    stopped responding" indistinguishable, which is exactly the ambiguity
    that produces false passes.
    """
    from ghostdriver.backends.windows.enumerate import enumerate_process
    results = [n.text for n in enumerate_process(tk_target)[0].walk()]
    assert "" in results
    assert None not in results
