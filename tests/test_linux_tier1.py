"""L3: tier 1 -- what the accessibility API can drive without synthesising input.

The rung below the ladder's problems. `docs/LINUX.md` sets three expectations
and this checks all three; the third turned out the other way from Windows,
which is the finding.

On Windows, writing a value straight into a control went *around* the
toolkit: the control displayed the new text while the binding never heard of
it, so the committed value and the shown value disagreed (D21). That split is
why `WM_SETTEXT` was deleted rather than kept as a fast path (D25).

AT-SPI's `EditableText` goes *through* GtkEditable, so the binding does hear.
Tier 1 is stronger here than on Windows, and these tests pin that -- if it
ever starts behaving like Windows, the ladder has to change back.
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

DISPLAY = ":74"
BUS_LAUNCHER = "/usr/libexec/at-spi-bus-launcher"


@pytest.fixture(scope="module")
def tier1():
    missing = [t for t in ("Xvfb", "dbus-run-session") if shutil.which(t) is None]
    if not os.path.exists(BUS_LAUNCHER):
        missing.append(BUS_LAUNCHER)
    if missing:
        pytest.skip("nested AT-SPI stack unavailable: " + ", ".join(missing))

    server = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", "1280x800x24"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    inner = (f"{BUS_LAUNCHER} --launch-immediately & sleep 3; "
             f"exec {sys.executable} -m tests.linux_tier1_probe")
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
            if out.startswith("{") and '"drawn_button"' in out:
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
        pytest.skip("the tier-1 probe produced no report")
    return json.loads(line)


def test_a_real_button_is_driven_by_the_accessibility_api(tier1):
    """The rung that costs nothing: no synthesised input, no focus taken."""
    assert tier1["real_button"]["actions"] == ["click"]
    assert tier1["real_button"]["do_action"] is True
    assert any(e.get("event") == "applied" for e in tier1["real_button"]["events"]), (
        "the action reported success without the application doing anything"
    )


def test_an_owner_drawn_control_offers_no_action_at_all(tier1):
    """D21's "a button that is not a BUTTON", in its Linux form. The
    DrawingArea exposes an accessible role because the fixture gives it one
    (D#8), but a role is not an implementation: there is no Action interface
    behind it, so tier 1 cannot reach it and the ladder has to.

    A negative that matters: if this ever gains an action, owner-drawn
    controls stop needing the rungs below.
    """
    assert tier1["drawn_button"]["actions"] == []
    assert isinstance(tier1["drawn_button"]["do_action"], str), "it gained an action"
    assert tier1["drawn_button"]["events"] == []


def test_writing_a_value_goes_through_the_toolkit_not_around_it(tier1):
    """The divergence. On Windows the write reached the control and not the
    binding, and the two disagreed until something committed (D21) -- which
    is why that path was deleted (D25). Here the toolkit's own `changed`
    signal fires, so a binding sees the write, and the value that gets
    committed is the one that was written."""
    entry = tier1["bound_entry"]
    assert "EditableText" in entry["interfaces"]
    assert entry["set_text"] is True
    assert entry["before"] == "original"
    assert entry["after"] == "written-by-atspi"

    changed = [e for e in entry["events"] if e.get("event") == "bound_changed"]
    assert changed, "the binding never heard of the write -- this is D21's split"
    assert changed[-1]["text"] == "written-by-atspi"


def test_the_write_is_a_delete_then_an_insert_and_a_binding_sees_both(tier1):
    """Worth pinning rather than discovering. `set_text_contents` clears and
    re-inserts, so `changed` fires twice and a binding that validates on every
    change sees a transient *empty* value it was never given.

    Harmless for a mirror; not harmless for a field that rejects empty, or one
    that fires a lookup per keystroke. A driver that writes values has to know
    the intermediate state exists.
    """
    changed = [e for e in tier1["bound_entry"]["events"]
               if e.get("event") == "bound_changed"]
    assert len(changed) >= 2, changed
    assert changed[0]["text"] == "", (
        "expected the clear-then-insert to show an empty intermediate state"
    )


def test_focus_cannot_be_taken_through_the_accessibility_api(tier1):
    """Recorded because slice 4 needs it. Tier 4 is the only actuation rung
    that exists here (D#11) and it needs the target focused -- and
    `Atspi.Component.grab_focus` does not work, so focus has to come from the
    window manager and keyboard navigation instead."""
    assert tier1["grab_focus"] is not True, (
        "grab_focus works now -- slice 4 has an easier route than assumed"
    )
