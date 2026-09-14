"""`capture region` renders the window a person sees at the rect (#136).

Backend-free: the trees are fakes and the desktop's answer to "what is at
this point" is stood in for.
"""

from types import SimpleNamespace

import pytest

from ghostdriver.tools import screen


class Tree(SimpleNamespace):
    pass


MAIN = Tree(handle=0x10, rect=(0, 0, 1536, 904))
MENU = Tree(handle=0x20, rect=(100, 100, 300, 500))     # a popup over the main window
MODAL = Tree(handle=0x30, rect=(400, 300, 900, 700))


@pytest.fixture
def desktop(monkeypatch):
    """What the desktop says is at a point: {root hwnd}; None means the
    backend cannot say."""
    answer = {"root": None}

    class WinApi:
        @staticmethod
        def window_from_point(x, y):
            return answer["root"] or 0

        @staticmethod
        def root_window(hwnd):
            return hwnd

    monkeypatch.setattr("ghostdriver.backends.current", lambda: SimpleNamespace(winapi=WinApi))
    return answer


def test_the_window_under_the_region_wins_when_it_is_a_candidate(desktop):
    desktop["root"] = MENU.handle
    region = (120, 120, 280, 480)  # inside both the menu and the main window
    assert screen._top_level_overlapping([MAIN, MENU], region) is MENU


def test_a_window_under_the_point_that_does_not_overlap_the_region_is_ignored(desktop):
    desktop["root"] = MODAL.handle   # the desktop says the modal, but the region is elsewhere
    region = (120, 120, 280, 480)
    assert screen._top_level_overlapping([MAIN, MENU], region) is MENU, "smaller of equal overlaps"


def test_without_a_desktop_answer_the_old_rule_stands(desktop):
    desktop["root"] = None
    region = (120, 120, 280, 480)
    assert screen._top_level_overlapping([MAIN, MENU], region) is MENU
    assert screen._top_level_overlapping([MAIN], region) is MAIN


def test_a_backend_without_the_query_falls_back(monkeypatch):
    monkeypatch.setattr("ghostdriver.backends.current", lambda: SimpleNamespace())
    region = (120, 120, 280, 480)
    assert screen._top_level_overlapping([MAIN, MENU], region) is MENU
