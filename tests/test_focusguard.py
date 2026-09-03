"""The foreground watch notices our windows and ignores everyone else's.

Proven with a fed sequence and a real child process, not by taking a real
operator's focus: the point of the guard is that nobody has to.
"""

import os
import subprocess
import sys

import pytest

from tests import focusguard
from tests.focusguard import ForegroundWatch


@pytest.fixture
def child():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    yield proc.pid
    proc.kill()


def watch_with(pids: dict[int, int]):
    return ForegroundWatch(
        foreground=lambda: 0,
        pid_of=lambda hwnd: pids[hwnd],
        class_of=lambda hwnd: f"class-of-{hwnd}",
    )


def test_a_window_of_a_descendant_process_is_recorded_with_the_test_name(child):
    watch = watch_with({0x10: child})
    focusguard.CURRENT["test"] = "tests/test_x.py::test_y"

    watch.observe(0x10, last=0x1)

    assert [(t["pid"], t["class"], t["test"]) for t in watch.taken] == [
        (child, "class-of-16", "tests/test_x.py::test_y")]


def test_a_window_of_an_unrelated_process_is_not_ours():
    """The operator switching to their own windows is their business."""
    unrelated = 4  # the System process: never descended from a test run
    watch = watch_with({0x20: unrelated})

    watch.observe(0x20, last=0x1)

    assert watch.taken == []


def test_this_process_itself_counts_as_ours():
    watch = watch_with({0x30: os.getpid()})

    watch.observe(0x30, last=0x1)

    assert len(watch.taken) == 1


def test_no_change_and_no_window_record_nothing(child):
    watch = watch_with({0x10: child})

    assert watch.observe(0x10, last=0x10) == 0x10  # unchanged
    assert watch.observe(0, last=0x10) == 0        # foreground went to nothing

    assert watch.taken == []


def test_a_process_that_has_exited_is_not_ours():
    """psutil cannot walk a dead process's parents; the guard says no
    rather than crashing the watch thread."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    watch = watch_with({0x40: proc.pid})

    watch.observe(0x40, last=0x1)

    assert watch.taken == []
