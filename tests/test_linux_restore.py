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
from pathlib import Path

import pytest

from tests.conftest import on_linux
from tests.linux_nested_shell import NEEDED as NESTED_NEEDED
from tests.linux_nested_shell import nested_env
from tests.linux_probe_support import collect_lines

pytestmark = [on_linux, pytest.mark.slow]

PROBE = Path(__file__).parent / "linux_l7_probe.sh"
NEEDED = (*NESTED_NEEDED, "xdotool", "xprop")


@pytest.fixture(scope="module")
def l7():
    missing = [t for t in NEEDED if shutil.which(t) is None]
    if missing:
        pytest.skip("the L7 measurement needs: " + ", ".join(missing))

    # A headless gnome-shell's Xwayland, not Xvfb + `gnome-shell --x11`,
    # which GNOME 50 removed (#217).
    with nested_env() as env:
        probe = subprocess.Popen(
            ["dbus-run-session", "--", "bash", str(PROBE)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            start_new_session=True,
            env=env,
        )
        try:
            # A real deadline (collect_lines): the old loop only checked the
            # clock when a line arrived, so a silent probe hung the suite.
            lines = collect_lines(probe.stdout, ("CONTROL", "RESULT", "TIMING", "ABORT", "=="), ("RESULT after_activate", "ABORT"), 260)
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(probe.pid), signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired):
                probe.wait(timeout=20)

    if any(ln.startswith("ABORT") for ln in lines) or "== controls pass ==" not in lines:
        # The whole trace, not a tail. #163: the controls are themselves
        # timed steps now, and which one blew its limit is the difference
        # between a loaded box and a window manager that has changed
        # behaviour -- a six-line tail can cut off exactly that.
        why = ""
        if any(ln.startswith("TIMING focus_") and "ok=0" in ln for ln in lines):
            # #217: the harness focuses a window by activating it, and mutter
            # in Wayland mode (GNOME 50's headless shell) refuses an X
            # client's activation -- so it can only get a focused window
            # when mutter happened to focus one on map.
            why = ("it focuses by activation, which mutter in Wayland mode "
                   "refuses for an X client (D#217); ")
        pytest.skip("the L7 harness could not hide a focused window -- " + why
                    + "so nothing it says about restoring one means anything:\n"
                    + "\n".join(lines))
    return {
        "results": {ln.split()[1]: " ".join(ln.split()[2:])
                    for ln in lines if ln.startswith("RESULT")},
        "timing": [ln for ln in lines if ln.startswith("TIMING")],
    }


def _field(l7, result, key):
    for token in l7["results"].get(result, "").split():
        if token.startswith(key + "="):
            return token.split("=", 1)[1]
    return None


def _why(l7):
    """What the probe's clock says, appended to every assertion here.

    #163: `test_restoring_a_window_necessarily_focuses_it` failed on every
    full-suite run and passed when this module ran alone, and the message said
    only that the foreground had not moved -- which is the consequence, not
    the cause. The probe now waits for the window manager rather than
    assuming two seconds of it, and reports what each step cost; a step
    marked `ok=0` here means the limit was blown, which is a loaded box, and
    a run where every step settled quickly and the assertion still failed is
    a real change in what GNOME Shell does with a restored window.
    """
    return "\nprobe timings:\n  " + "\n  ".join(l7["timing"] or ["(none recorded)"])


def test_a_bare_map_does_not_bring_a_hidden_window_back(l7):
    """`XMapWindow` is the ICCCM way to de-iconify, and it asks for nothing
    else. Under GNOME Shell it does not work: the window stays hidden.

    So there is no "show it without focusing it" route, which is what a
    caller wanting to reveal a window quietly would reach for.
    """
    assert _field(l7, "before_restore", "a_hidden") == "1", _why(l7)
    assert _field(l7, "after_map", "a_hidden") == "1", (
        "a bare map un-hid the window -- there is a quiet route after all, "
        "and restore does not have to take focus" + _why(l7)
    )


def test_the_bare_map_also_does_not_disturb_the_foreground(l7):
    """The other half of the same fact. It changed nothing at all, rather
    than half-restoring the window."""
    assert _field(l7, "after_map", "active") == _field(l7, "after_map", "was"), _why(l7)


def test_activation_neither_restores_nor_focuses_on_the_headless_shell(l7):
    """What restoring a hidden window takes, measured again on GNOME 50 (#217).

    Under `gnome-shell --x11` (D#14) activation was the *only* thing that
    restored a hidden window, so restoring and focusing were one operation.
    GNOME 50 has no X11 mode. Under its headless shell -- mutter in Wayland
    mode, the target an X client of its Xwayland -- activation is refused for
    an X client outright: the window stays hidden and the foreground does not
    move. So on this stack nothing an X client can send restores a hidden
    window, and `restore` reports that rather than claiming it (#217).
    """
    assert _field(l7, "after_activate", "a_hidden") == "1", (
        "activation restored it: mutter now honours an X client's activation, "
        "which it did not when this was measured (#217)" + _why(l7)
    )
    assert _field(l7, "after_activate", "active") == _field(l7, "before_restore", "active"), (
        "the foreground moved without the window coming back" + _why(l7)
    )
