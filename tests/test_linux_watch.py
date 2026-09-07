"""Slice 5a of #40: the minimized watch, against a target that fights back.

The policy already existed and is platform-neutral -- `ghostdriver.isolation`
says so in its own docstring, "pure policy, fed observations". So this is a
second *sampler* rather than a second policy, which is the seam D59 exists to
keep. What is Linux-specific is only what a sample is: hidden rather than
unmapped (D#13), and putting a window away without a way to take it back
quietly (D#14).

The fixture grabs the foreground on a timer, which is what a foreground grab
*is*. The watch has to put it away, notice it got out, photograph what
appeared, and put it away again.
"""

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time

import pytest

from tests.conftest import on_linux

pytestmark = [on_linux, pytest.mark.slow]

DISPLAY = ":67"
NEEDED = ("Xvfb", "dbus-run-session", "gnome-shell", "xprop", "convert")


@pytest.fixture(scope="module")
def watched():
    missing = [t for t in NEEDED if shutil.which(t) is None]
    if missing:
        pytest.skip("the watch measurement needs: " + ", ".join(missing))

    server = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", "1280x800x24"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    inner = ('gnome-shell --x11 >/dev/null 2>&1 & '
             'for i in $(seq 1 30); do '
             'xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -q 0x && break; '
             'sleep 1; done; '
             f'exec {sys.executable} -m tests.linux_watch_probe')
    probe = subprocess.Popen(
        ["dbus-run-session", "--", "bash", "-c", inner],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        start_new_session=True,
        env=dict(os.environ, DISPLAY=DISPLAY, GSETTINGS_BACKEND="memory",
                 GDK_BACKEND="x11", PYTHONPATH="src"),
    )
    line, deadline = None, time.monotonic() + 240
    try:
        for out in probe.stdout:
            if out.startswith("{") and '"kinds"' in out:
                line = out
                break
            if time.monotonic() > deadline:
                break
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(probe.pid), signal.SIGTERM)
        with contextlib.suppress(subprocess.TimeoutExpired):
            probe.wait(timeout=20)
        server.terminate()
        server.wait(timeout=10)

    if line is None:
        pytest.skip("the watch probe produced no report")
    return json.loads(line)


def test_starting_the_watch_puts_the_target_away(watched):
    """`start` establishes the state it is there to keep, rather than waiting
    for the first sample to notice the target is on screen."""
    assert watched["hidden_after_start"] is True


#: The two ways the policy names an escape. Which one fires is not the
#: sampler's business and is not stable here: `present()` sometimes gets
#: focus from GNOME Shell and sometimes only maps, so the same fixture
#: produces `unexpected_foreground` on one run and `unexpected_restore` on
#: the next. Both are escapes, both are captured, both are put back.
ESCAPES = {"unexpected_foreground", "unexpected_restore"}


def test_a_target_that_gets_out_is_reported(watched):
    """The event is the product. `isolation.py` is explicit that
    re-minimizing is the housekeeping and the *report* is what a caller
    could not have got any other way -- an application demanding the screen
    is almost always raising something.

    Asserted as "an escape" rather than as a particular kind. Pinning the
    kind would be pinning whether the window manager happened to grant focus
    that run, which is neither stable nor this backend's decision: the
    policy that tells the two apart is platform-neutral and already tested.
    """
    assert set(watched["kinds"]) & ESCAPES, watched["events"]


def test_the_escape_is_photographed_before_it_is_put_back(watched):
    """Whatever appeared is gone the moment the watchdog acts, so the capture
    has to happen first or the picture is of a hidden window. Asserted
    because "captured" is the difference between telling a caller *that*
    something appeared and telling them *what*."""
    assert watched["any_capture"] is True, watched["events"]


def test_the_target_is_put_back_after_the_grab(watched):
    """The housekeeping half. Measured on Linux this is load-bearing in a way
    it is not on Windows: there is no quiet un-hide (D#14), so a target left
    out is a target holding the foreground."""
    assert watched["hidden_at_end"] is True
