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
from tests.linux_nested_shell import NEEDED as NESTED_NEEDED
from tests.linux_nested_shell import inner, nested_env

pytestmark = [on_linux, pytest.mark.slow]

NEEDED = NESTED_NEEDED
BUS_LAUNCHER = "/usr/libexec/at-spi-bus-launcher"


@pytest.fixture(scope="module")
def modality():
    missing = [t for t in NEEDED if shutil.which(t) is None]
    if not os.path.exists(BUS_LAUNCHER):
        missing.append(BUS_LAUNCHER)
    if missing:
        pytest.skip("the modality measurement needs: " + ", ".join(missing))

    # A headless gnome-shell's Xwayland, not Xvfb + `gnome-shell --x11`,
    # which GNOME 50 removed (#217). The shell activates its own
    # accessibility bus on the private session bus.
    with nested_env() as env:
        probe = subprocess.Popen(
            ["dbus-run-session", "--", "bash", "-c",
             inner(f"{sys.executable} -m tests.linux_modality_probe")],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            start_new_session=True, env=env,
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


def test_active_on_the_owner_is_not_a_modality_signal(modality):
    """`ACTIVE` on the owner is not how to tell it is held, on any stack
    measured.

    Under `gnome-shell --x11` (D#12) the owner *lost* `ACTIVE` when the modal
    came up -- but so does any window when anything else takes focus, modal
    or not. Under GNOME 50's headless shell, mutter in Wayland mode (#217),
    it does not even move: an X client's new modal is not given focus, so the
    owner stays `ACTIVE` with the modal up. Either way the signal is
    `STATE_MODAL` and the window manager's modal state, never this.

    Skips rather than fails when the window manager never focused the
    fixture: a baseline of "not active" compared against "not active" is a
    race dressed as a result (a full-suite run failed exactly that way).
    """
    if not modality.get("baseline_was_active"):
        pytest.skip("the window manager never focused the fixture, so there is "
                    "no baseline to compare the modal against")
    before = _frame(modality, "before", "fixture")
    during = _frame(modality, "during", "fixture")
    assert "ACTIVE" in before["states"]
    assert "ACTIVE" in during["states"], (
        "the owner lost ACTIVE: focus moved to the modal, which mutter in "
        "Wayland mode did not do when this was measured (#217)")
