"""Last in the run on purpose: did any test take the operator's foreground?

The watch itself lives in tests/focusguard.py and is started by conftest at
session start. This test only reads what it recorded. It is the promise the
whole tool is built on, held to the suite that tests it: nothing we launch
takes the foreground, ever, unless a test opted in to provoke exactly that.
"""

import os

import pytest

from tests.conftest import on_windows

pytestmark = on_windows


@pytest.mark.skipif(
    os.environ.get("GHOSTDRIVER_ALLOW_FOCUS_TESTS") == "1",
    reason="opt-in focus tests take the foreground on purpose",
)
def test_no_test_spawned_window_took_the_foreground(request):
    watch = request.config._ghostdriver_focus_watch
    watch.stop()

    assert watch.taken == [], (
        "a window belonging to a process this run launched became the "
        "foreground window -- the operator's focus was taken:\n"
        + "\n".join(f"  {t['class']} (pid {t['pid']}) during {t['test']}"
                    for t in watch.taken)
    )
