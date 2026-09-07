"""L5: how a driver can tell an application is held by a modal.

D48 measured the Windows shape and the trap in it: a modal disables the
*top-level* and every control inside still reports enabled, so a driver that
asks the control alone sees nothing wrong and actuates into a held
application. Modality there is not declared -- it is inferred from something
being disabled.

Linux inverts that. Modality *is* declared, by the window manager and by
AT-SPI, and **nothing is disabled at all**. So the Windows mechanism has no
counterpart here, and the check has to run the other way round: not "is
anything above me disabled" but "is anything modal transient for me".

L5's third question -- whether a sent event to a held window is honoured --
needs no measurement: D#11 found sent events ignored in every configuration,
held or not.
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

DISPLAY = ":63"
NEEDED = ("Xvfb", "dbus-run-session", "gnome-shell", "xprop")
BUS_LAUNCHER = "/usr/libexec/at-spi-bus-launcher"


@pytest.fixture(scope="module")
def modality():
    missing = [t for t in NEEDED if shutil.which(t) is None]
    if not os.path.exists(BUS_LAUNCHER):
        missing.append(BUS_LAUNCHER)
    if missing:
        pytest.skip("the modality measurement needs: " + ", ".join(missing))

    server = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", "1280x800x24"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    inner = ('gnome-shell --x11 >/dev/null 2>&1 & '
             'for i in $(seq 1 30); do '
             'xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -q 0x && break; '
             'sleep 1; done; '
             f'{BUS_LAUNCHER} --launch-immediately & sleep 3; '
             f'exec {sys.executable} -m tests.linux_modality_probe')
    probe = subprocess.Popen(
        ["dbus-run-session", "--", "bash", "-c", inner],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        start_new_session=True,
        env=dict(os.environ, DISPLAY=DISPLAY, GSETTINGS_BACKEND="memory",
                 GDK_BACKEND="x11", PYTHONPATH="src"),
    )
    line, deadline = None, time.monotonic() + 220
    try:
        for out in probe.stdout:
            if out.startswith("{") and '"during"' in out:
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
        pytest.skip("the modality probe produced no report")
    return json.loads(line)


def _frame(report, when, name_contains):
    for entry in report[when]:
        if entry["role"] == "frame" and name_contains in entry["name"]:
            return entry
    return None


def test_the_modal_declares_itself_to_the_accessibility_api(modality):
    """`STATE_MODAL`, directly. Nothing has to be inferred, which is already
    a better position than Windows, where modality is only visible as a side
    effect of the owner being disabled."""
    modal = _frame(modality, "during", "Confirm")
    assert modal is not None, modality["during"]
    assert "MODAL" in modal["states"]


def test_the_modal_declares_itself_to_the_window_manager(modality):
    """`_NET_WM_STATE_MODAL`, and `WM_TRANSIENT_FOR` naming the window it
    holds -- which is exactly the `owner` field `TopLevel` carries, available
    for free rather than derived."""
    modals = [x for x in modality["x"].values()
              if "_NET_WM_STATE_MODAL" in x["wm_state"]]
    assert modals, modality["x"]
    assert "0x" in modals[0]["transient_for"], modals[0]


def test_the_held_window_is_not_disabled_and_that_is_the_finding(modality):
    """The Windows mechanism does not port.

    There, `blocking_ancestor` walks up looking for a window that reports
    disabled, because a modal disables its owner. Here the owner keeps
    `SENSITIVE` throughout -- so a driver that asks whether anything above a
    control is disabled gets "no" while the application is completely held.

    D48's trap is that asking the *control* is not enough. The Linux version
    is sharper: asking any accessible is not enough, including the top-level.
    The question has to be put to the window manager instead.
    """
    before = _frame(modality, "before", "fixture")
    during = _frame(modality, "during", "fixture")
    assert "SENSITIVE" in before["states"]
    assert "SENSITIVE" in during["states"], (
        "the owner went insensitive -- the Windows mechanism ports after all"
    )


def test_what_does_change_on_the_owner_is_active(modality):
    """The one signal that does move, and it is not enough on its own: a
    window loses `ACTIVE` whenever anything else takes focus, modal or not.
    Recorded so it is not mistaken for a modality check.

    Skips rather than fails when the window manager never focused the
    fixture. A baseline taken before that happened records "not active" and
    then compares it against "not active", which is a race dressed as a
    result -- and this test failed exactly that way once, in a full-suite run
    where the machine was busier than when it passed alone.
    """
    if not modality.get("baseline_was_active"):
        pytest.skip("the window manager never focused the fixture, so there is "
                    "no baseline to compare the modal against")
    before = _frame(modality, "before", "fixture")
    during = _frame(modality, "during", "fixture")
    assert "ACTIVE" in before["states"]
    assert "ACTIVE" not in during["states"]
