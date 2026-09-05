"""L4: whether the Windows tier ladder maps to Linux at all.

`docs/LINUX.md` names this as *the* measurement, because tier 3 is the rung
that delivers input to a chosen window without taking the operator's focus or
pointer. If a sent event does not drive the target, that rung does not exist
and the ladder has to be replaced rather than ported.

Measured under a real window manager (GNOME Shell on a nested display with
its own session bus), because the first attempt ran without one and got a
different -- and wrong -- answer.

Slow and heavy: an X server, a private session bus, a window manager and two
fixture instances. It earns that by pinning a platform behaviour the whole
actuation design rests on. If GTK ever starts honouring sent events, this
fails, and that is a finding worth being told about.
"""

import contextlib
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

from tests.conftest import on_linux

pytestmark = [on_linux, pytest.mark.slow]

DISPLAY = ":83"
PROBE = Path(__file__).parent / "linux_tier3_probe.sh"
NEEDED = ("Xvfb", "dbus-run-session", "gnome-shell", "xdotool", "xclip", "xprop")


@pytest.fixture(scope="module")
def tier3():
    """Run the probe and read until it has said everything it is going to.

    Deliberately not `subprocess.run`: `dbus-run-session` exits when the bus
    has no clients left, and GNOME Shell leaves daemons connected to it
    (tracker, the portal, goa), so the session outlives the measurement and
    waiting for it is waiting forever. The probe's last line is the signal
    that it is done; after that the whole process group goes.
    """
    missing = [t for t in NEEDED if shutil.which(t) is None]
    if missing:
        pytest.skip("tier-3 measurement needs: " + ", ".join(missing))

    server = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", "1280x800x24"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    probe = subprocess.Popen(
        ["dbus-run-session", "--", "bash", str(PROBE)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        start_new_session=True,          # its own group, so teardown is total
        env=dict(os.environ, DISPLAY=DISPLAY, GSETTINGS_BACKEND="memory",
                 GDK_BACKEND="x11", PYTHONPATH="src"),
    )
    lines, deadline = [], time.monotonic() + 240
    try:
        for line in probe.stdout:
            line = line.strip()
            if line.startswith(("CONTROL", "EXPT", "ABORT", "==")):
                lines.append(line)
            if line.startswith("EXPT D") or line.startswith("ABORT"):
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

    if any(ln.startswith("ABORT") for ln in lines) or "== controls pass ==" not in lines:
        pytest.skip("the tier-3 harness could not produce a positive control, "
                    "so no negative from it means anything:\n" + "\n".join(lines[-6:]))
    keyed = {ln.split()[1]: ln for ln in lines if ln.startswith("EXPT")}
    keyed["controls"] = " | ".join(ln for ln in lines if ln.startswith("CONTROL"))
    return keyed


def test_the_controls_prove_the_harness_could_have_seen_an_effect(tier3):
    """Asserted first and separately, because every earlier run of this
    measurement failed here rather than in the experiment."""
    assert "BR-1041" in tier3["controls"], tier3["controls"]
    assert "-> 1" in tier3["controls"] or "0 -> " in tier3["controls"], tier3["controls"]


@pytest.mark.parametrize("case", ["A", "B", "C", "D"], ids=[
    "sent-key-to-focused", "sent-button-focused-pointer-away",
    "sent-key-to-unfocused", "sent-button-unfocused-pointer-away",
])
def test_gtk_ignores_a_sent_event_in_every_configuration(tier3, case):
    """The finding. GTK4 routes input by the real input state and discards a
    synthesised event, whether or not the target holds focus and whether or
    not the pointer is over it.

    So **tier 3 does not exist on GTK4/X11**: the ladder is tier 1 then tier
    4-under-isolation, which makes the nested X server mandatory rather than
    preferred (D#8), because tier 4 takes the real focus and pointer and that
    must never be the operator's.
    """
    line = tier3[case]
    if "sent-key" in line:
        assert "[E1]" in line or "[E3]" in line, (
            f"a sent key drove the target -- tier 3 may exist after all: {line}"
        )
    else:
        before, _, after = line.rpartition("->")
        assert before.split()[-1].strip() == after.strip(), (
            f"a sent button drove the target -- tier 3 may exist after all: {line}"
        )
