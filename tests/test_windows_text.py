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


def test_answering_controls_are_marked_responsive(tk_target):
    """Controls that answer a text query must be flagged responsive.

    The empty-vs-no-answer distinction lives on WindowNode.responsive once
    build_tree has run; asserting on `text` alone cannot see it, because
    both cases carry "".
    """
    from ghostdriver.backends.windows.enumerate import enumerate_process
    nodes = list(enumerate_process(tk_target)[0].walk())
    assert nodes
    assert all(n.responsive for n in nodes)
