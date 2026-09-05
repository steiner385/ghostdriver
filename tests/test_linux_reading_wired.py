"""Slice 2 of #40: reading, reached through the contract rather than directly.

`tests/test_linux_reading.py` measures what AT-SPI *will* tell you --
including that it hands over a password in cleartext. This checks what the
backend actually returns when a caller asks, which is the place the
disclosure policy (D#34b) and the deadline (D#9) have to be in force.
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

DISPLAY = ":71"
BUS_LAUNCHER = "/usr/libexec/at-spi-bus-launcher"


@pytest.fixture(scope="module")
def wired():
    missing = [t for t in ("Xvfb", "dbus-run-session", "convert", "xwininfo")
               if shutil.which(t) is None]
    if not os.path.exists(BUS_LAUNCHER):
        missing.append(BUS_LAUNCHER)
    if missing:
        pytest.skip("slice 2 needs: " + ", ".join(missing))

    server = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", "1280x800x24"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    inner = (f"{BUS_LAUNCHER} --launch-immediately & sleep 3; "
             f"exec {sys.executable} -m tests.linux_reading_probe")
    probe = subprocess.Popen(
        ["dbus-run-session", "--", "bash", "-c", inner],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        start_new_session=True,
        env=dict(os.environ, DISPLAY=DISPLAY, GSETTINGS_BACKEND="memory",
                 GDK_BACKEND="x11", PYTHONPATH="src"),
    )
    line, deadline = None, time.monotonic() + 180
    try:
        for out in probe.stdout:
            if out.startswith("{") and '"controls"' in out:
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
        pytest.skip("the slice-2 probe produced no report")
    return json.loads(line)


@pytest.mark.parametrize("name", ["plain entry", "password entry", "password widget"])
def test_no_editable_entry_discloses_its_contents(wired, name):
    """The policy in force where it matters. `tests/test_linux_reading.py`
    asserts AT-SPI *will* return `hunter2`; this asserts the backend does
    not, for the hidden entry and the plain one alike -- because nothing
    distinguishes them (D#34b)."""
    assert wired["controls"][name]["read"] is None


def test_a_caption_still_reads(wired):
    """The blast radius stays small. Buttons, labels and tables are not
    somewhere a secret is typed, and withholding them would cost the reads
    `read` mostly exists for. A control with no `Text` interface answers with
    its caption, which is what `WM_GETTEXT` gives such a window on Windows."""
    assert wired["controls"]["Recalculate"]["read"] == "Recalculate"
    assert wired["controls"]["status"]["read"] == "ready"
    assert wired["controls"]["results grid"]["read"] == "results grid"


def test_only_the_declared_password_widget_reports_protected(wired):
    """`is_protected` is deliberately narrower than the disclosure policy: it
    also refuses *typing* (D38), and a wider answer would refuse to type into
    every text field on screen. So the hidden entry is withheld but not
    protected -- undisclosed, still typeable."""
    assert wired["controls"]["password widget"]["protected"] is True
    assert wired["controls"]["password entry"]["protected"] is False
    assert wired["controls"]["plain entry"]["protected"] is False


def test_a_plain_entry_is_indistinguishable_from_one_that_did_not_answer(wired):
    """The known cost, asserted so it cannot be forgotten.

    `None` means "did not answer" everywhere else in this contract, and on
    Windows that is unambiguous because the OS refuses the read only for
    password fields (D37). Here it also means "withheld", and `is_protected`
    separates only the declared widget -- so a perfectly healthy text field
    reads exactly like a hung one.

    That is the confusion D37 exists to prevent, and this slice does not fix
    it: the fix is a disclosure opt-in through the contract, which changes a
    signature Windows shares. Tracked, not smuggled in.
    """
    plain = wired["controls"]["plain entry"]
    assert plain["read"] is None and plain["protected"] is False, (
        "a caller cannot tell this from a control that never replied"
    )


def test_a_window_captures_as_a_real_png(wired):
    """Only toplevels have an X id, so a handle captures its window (D#8).
    Asserted as a decoded size rather than a byte count, because a capture
    that returns bytes and no picture is the trap D66 names."""
    capture = wired["capture"]
    assert "error" not in capture, capture
    assert capture["is_png"] is True
    assert capture["width"] > 100 and capture["height"] > 100, capture
