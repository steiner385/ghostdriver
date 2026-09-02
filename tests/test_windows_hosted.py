"""Resolving the application inside a hosted frame, against live windows.

The window tree cannot answer this -- a hosted application and its frame are
separate top-level windows with no relationship between them -- so the
answer comes from the accessibility tree, whose elements carry the process
that provided them.
"""

import pytest

from tests.conftest import on_windows

pytestmark = on_windows


def test_an_ordinary_window_resolves_to_nobody_else(win32_target):
    """The direction that matters most for false positives.

    A normal application provides its own elements. Reporting some other
    process as "the application inside" would send a caller somewhere
    unrelated, which is worse than saying nothing.
    """
    from ghostdriver.backends.windows.enumerate import top_level_windows
    from ghostdriver.backends.windows.hosted import resolve_hosted_app

    hwnd = top_level_windows(win32_target)[0]
    assert resolve_hosted_app(hwnd, win32_target) is None


def test_the_census_attributes_elements_to_the_owning_process(win32_target):
    from ghostdriver.backends.windows.enumerate import top_level_windows
    from ghostdriver.backends.windows.hosted import process_census

    hwnd = top_level_windows(win32_target)[0]
    counts = process_census(hwnd)

    if not counts:
        pytest.skip("no UIA provider for this window on this machine")
    assert max(counts, key=counts.get) == win32_target


def test_resolution_needs_a_clear_majority():
    """Set high on purpose: pointing a caller at an unrelated process is
    worse than admitting the answer is unclear."""
    from ghostdriver.backends.windows.hosted import MAJORITY

    assert MAJORITY >= 0.6


def test_the_walk_is_bounded(win32_target):
    """It runs during attach, so it cannot be a full tree walk."""
    from ghostdriver.backends.windows.hosted import MAX_DEPTH, MAX_ELEMENTS

    assert MAX_ELEMENTS <= 500
    assert MAX_DEPTH <= 10
