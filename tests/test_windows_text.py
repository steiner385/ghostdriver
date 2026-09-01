import pytest

from tests.conftest import on_windows

pytestmark = on_windows


def test_reads_caption_of_a_cross_process_control(win32_target):
    from ghostdriver.backends.windows.enumerate import enumerate_process
    texts = {n.text for n in enumerate_process(win32_target)[0].walk()}
    assert "Expand All" in texts
    assert "Collapse All" in texts


def test_reads_top_level_window_title(win32_target):
    from ghostdriver.backends.windows.enumerate import enumerate_process
    assert enumerate_process(win32_target)[0].text == "GhostdriverTestWindow"


def test_returns_none_for_a_dead_handle():
    from ghostdriver.backends.windows.text import read_window_text
    assert read_window_text(0xDEADBEEF) is None


def test_answering_controls_are_marked_responsive(win32_target):
    """Every control in this fixture answers, so all must be responsive=True.

    Be clear about what this does and does not verify. It verifies that
    build_tree wires the flag the right way round: an implementation that
    wrote `responsive = raw_text is None` would mark every node in this
    fixture False and fail here. It does NOT reach the False branch at all
    — the fixture is a live, message-pumping window whose controls always
    answer, so no node in it can produce raw_text is None. An
    implementation that hardcoded `responsive=True` also passes.

    The False branch is genuinely unexercised by the suite. It cannot be
    covered here without faking the send path, and faking it would test the
    fake. Its first real execution is against a target in the Windows
    validation session; see Gate 5 of docs/VALIDATION.md.
    """
    from ghostdriver.backends.windows.enumerate import enumerate_process
    nodes = list(enumerate_process(win32_target)[0].walk())
    assert nodes
    assert all(n.responsive for n in nodes)
