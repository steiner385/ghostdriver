"""L7: what it costs to give a hidden window back.

D55 says to assume the window manager focuses a restored window until
measured, and D4 permits `restore` at `read_only` precisely because it is the
operator's own escape hatch -- the one place a focus change is legitimate.

The measurement says something stronger than the assumption: under GNOME
Shell you **cannot** un-hide without focusing. A bare map leaves the window
hidden, and the only thing that brings it back is activation, which focuses
it by definition.

Both legitimate routes are covered. `_NET_WM_STATE_HIDDEN` is
window-manager-managed and a client may not set it, so the alternatives are
`XMapWindow` (ICCCM) and `_NET_ACTIVE_WINDOW` (EWMH) -- `windowmap` and
`windowactivate` respectively.
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

DISPLAY = ":69"
PROBE = Path(__file__).parent / "linux_l7_probe.sh"
NEEDED = ("Xvfb", "dbus-run-session", "gnome-shell", "xdotool", "xprop")


@pytest.fixture(scope="module")
def l7():
    missing = [t for t in NEEDED if shutil.which(t) is None]
    if missing:
        pytest.skip("the L7 measurement needs: " + ", ".join(missing))

    server = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", "1280x800x24"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    probe = subprocess.Popen(
        ["dbus-run-session", "--", "bash", str(PROBE)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        start_new_session=True,
        env=dict(os.environ, DISPLAY=DISPLAY, GSETTINGS_BACKEND="memory",
                 GDK_BACKEND="x11", PYTHONPATH="src"),
    )
    lines, deadline = [], time.monotonic() + 260
    try:
        for line in probe.stdout:
            line = line.strip()
            if line.startswith(("CONTROL", "RESULT", "ABORT", "==")):
                lines.append(line)
            if line.startswith("RESULT after_activate") or line.startswith("ABORT"):
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
        pytest.skip("the L7 harness could not hide a focused window, so nothing "
                    "it says about restoring one means anything:\n"
                    + "\n".join(lines[-6:]))
    return {ln.split()[1]: " ".join(ln.split()[2:])
            for ln in lines if ln.startswith("RESULT")}


def _field(blob, key):
    for token in blob.split():
        if token.startswith(key + "="):
            return token.split("=", 1)[1]
    return None


def test_a_bare_map_does_not_bring_a_hidden_window_back(l7):
    """`XMapWindow` is the ICCCM way to de-iconify, and it asks for nothing
    else. Under GNOME Shell it does not work: the window stays hidden.

    So there is no "show it without focusing it" route, which is what a
    caller wanting to reveal a window quietly would reach for.
    """
    assert _field(l7["before_restore"], "a_hidden") == "1"
    assert _field(l7["after_map"], "a_hidden") == "1", (
        "a bare map un-hid the window -- there is a quiet route after all, "
        "and restore does not have to take focus"
    )


def test_the_bare_map_also_does_not_disturb_the_foreground(l7):
    """The other half of the same fact. It changed nothing at all, rather
    than half-restoring the window."""
    assert _field(l7["after_map"], "active") == _field(l7["after_map"], "was")


def test_restoring_a_window_necessarily_focuses_it(l7):
    """The answer to D55, stronger than the assumption it replaced. D55 said
    to assume the window manager focuses a restored window; in fact
    activation is the *only* thing that restores it, so restoring and
    focusing are one operation and cannot be separated.

    That is acceptable -- D4 permits `restore` at `read_only` because it is
    the operator's escape hatch, and handing the window back is the point.
    What it forbids is any code path that wants a window visible but not
    focused: on this window manager there isn't one.
    """
    assert _field(l7["after_activate"], "a_hidden") == "0", "activation did not restore it"
    assert _field(l7["after_activate"], "active") == _field(l7["before_restore"], "target"), (
        "the restored window is not the active one"
    )
    assert _field(l7["after_activate"], "active") != _field(l7["before_restore"], "active"), (
        "the foreground did not move, so this proves nothing about focus"
    )
