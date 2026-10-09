"""L6: the operator's foreground must never move, and the watchdog.

This is the guarantee the project exists to provide, so it is asserted rather
than argued: the operator runs a full desktop on their own display while the
target is driven on a nested one, and `_NET_ACTIVE_WINDOW` on *their* display
is read before and after every step.

Two things the Windows design assumed that had to be re-derived here:

* **What "iconified" looks like.** Not `Map State`, which a compositing window
  manager leaves at `IsViewable`, but `_NET_WM_STATE_HIDDEN`.
* **Whether a hidden window can still be captured.** On Windows `PrintWindow`
  asks the window to render itself, which is why the minimized strategy works
  (D49, D55). X11 has no such call -- but under a compositor the contents
  survive, measured pixel-identical. That is a property of the *compositor*,
  not of X11, and is stated as such.

Heavy: an X server, a private session bus, GNOME Shell and a fixture. It
earns that by measuring the one claim everything else rests on.
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
from tests.linux_nested_shell import NEEDED as NESTED_NEEDED
from tests.linux_nested_shell import nested_env

pytestmark = [on_linux, pytest.mark.slow]

PROBE = Path(__file__).parent / "linux_l6_probe.sh"
NEEDED = (*NESTED_NEEDED, "xdotool", "xprop",
          "xwd", "convert")


@pytest.fixture(scope="module")
def l6():
    missing = [t for t in NEEDED if shutil.which(t) is None]
    if missing:
        pytest.skip("the L6 measurement needs: " + ", ".join(missing))
    if not os.environ.get("DISPLAY"):
        pytest.skip("no operator display to prove the target never disturbs")

    # A headless gnome-shell's Xwayland, not Xvfb + `gnome-shell --x11`,
    # which GNOME 50 removed (#217).
    with nested_env(GHOSTDRIVER_OPERATOR_DISPLAY=os.environ["DISPLAY"],
                    GHOSTDRIVER_OPERATOR_XAUTHORITY=os.environ.get("XAUTHORITY", "")) as env:
        probe = subprocess.Popen(
            ["dbus-run-session", "--", "bash", str(PROBE)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            start_new_session=True,
            env=env,
        )
        lines, deadline = [], time.monotonic() + 260
        try:
            for line in probe.stdout:
                line = line.strip()
                if line.startswith(("OPERATOR", "CONTROL", "RESULT", "ABORT", "==")):
                    lines.append(line)
                if line.startswith("RESULT operator_final") or line.startswith("ABORT"):
                    break
                if time.monotonic() > deadline:
                    break
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(probe.pid), signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired):
                probe.wait(timeout=20)

    if any(ln.startswith("ABORT") for ln in lines) or "== controls pass ==" not in lines:
        pytest.skip("the L6 harness could not drive the target, so a still "
                    "foreground proves nothing:\n" + "\n".join(lines[-6:]))
    out = {}
    for ln in lines:
        parts = ln.split()
        if parts[0] in ("RESULT", "CONTROL", "OPERATOR") and len(parts) > 1:
            out[parts[1]] = " ".join(parts[2:])
    return out


def _field(blob, key):
    for token in blob.split():
        if token.startswith(key + "="):
            return token.split("=", 1)[1]
    return None


def test_the_control_proves_the_target_was_actually_driven(l6):
    """First, because "the foreground did not move" is trivially true of a
    harness that did nothing."""
    assert "->" in l6["drive"], l6["drive"]
    before, _, after = l6["drive"].partition("->")
    assert before.strip() != after.strip()


@pytest.mark.parametrize("moment", [
    "operator_after_drive", "operator_after_iconify",
    "operator_after_present", "operator_final",
])
def test_no_window_this_run_launched_ever_became_the_operators(l6, moment):
    """The guarantee, stated as attribution rather than stillness.

    An earlier version of this test asserted the operator's active window was
    the *same handle* throughout, and it failed the first time it ran while
    someone was using the machine -- because they clicked something, which is
    not a defect in the driver. The Windows focus guard has always framed it
    correctly: what must never happen is that *a window belonging to a
    process this run launched* becomes the operator's foreground
    (`tests/test_zz_focus_guard.py`).

    So the operator's foreground may move freely. It may never move *to the
    target*, including while the target is deliberately grabbing the
    foreground on its own display.
    """
    fixture_pid = _field(l6["baseline"], "fixture_pid")
    owner = _field(l6[moment], "owner_pid")
    assert owner != fixture_pid, (
        f"at {moment} the operator's foreground was owned by the process this "
        f"run launched (pid {owner}) -- the target took the operator's focus"
    )


def test_hidden_is_the_iconified_signal_not_map_state(l6):
    """A compositing window manager leaves an iconified window `IsViewable`,
    so the Windows habit of asking whether it is mapped answers wrongly here.
    `_NET_WM_STATE_HIDDEN` is what moves."""
    assert _field(l6["mapped"], "hidden") == "0"
    assert _field(l6["iconified"], "hidden") == "1"


def test_an_iconified_window_can_still_be_captured(l6):
    """What makes the minimized strategy possible at all. On Windows
    `PrintWindow` asks the window to render itself; X11 has no equivalent, and
    an unmapped window's contents are not guaranteed to survive. Under a
    compositor they do -- measured identical, not merely non-empty, because a
    capture that succeeds and returns a blank buffer is worse than one that
    fails (D66).

    This is a property of the compositor. A non-compositing window manager is
    expected to lose the contents, and that is unmeasured.
    """
    mapped = int(_field(l6["mapped"], "colours"))
    hidden = int(_field(l6["iconified"], "colours"))
    assert mapped > 100, f"the mapped capture is nearly blank ({mapped} colours)"
    assert hidden == mapped, (
        f"the iconified capture lost content: {mapped} colours mapped, {hidden} hidden"
    )


def test_a_target_that_presents_itself_stays_put_away(l6):
    """The disruption the watchdog exists for, asked again on GNOME 50 (#217).

    Under `gnome-shell --x11` the fixture's timed present() cleared HIDDEN and
    took the nested foreground -- a foreground grab, observable, which is what
    D49's watchdog reports. Under GNOME 50's headless shell, mutter in Wayland
    mode refuses an X client's present() while it is iconified: the window
    stays hidden and the foreground stays where it was. The escape that does
    still happen on this stack is a modal (tests/linux_watch_probe.py).
    """
    assert _field(l6["after_present"], "hidden") == "1", (
        "present() un-iconified the target: mutter now honours it, which it "
        "did not when this was measured (#217)")
    assert _field(l6["after_present"], "nested_active") != _field(l6["after_present"], "target")
