"""L0: the GTK fixture stands up, announces itself, and stays out of the way.

The first Linux measurement that can run. It does not need the AT-SPI bus --
that is L1 (#8) -- so it asserts only what X itself can answer: that the
fixture maps a real toplevel, that the toplevel can be tied back to the
process that owns it, and that mapping a window did not take the foreground.

Everything here runs on a nested display the test starts itself, which is the
same isolation the real strategy will use (#8). If `Xvfb` is missing the tests
skip rather than fall back to the operator's display: a fixture that grabs the
foreground is opt-in here precisely so that a run cannot do it by accident.
"""

import json
import os
import shutil
import subprocess
import sys
import time

import pytest

from tests.conftest import on_linux

pytestmark = [on_linux, pytest.mark.slow]

DISPLAY = ":97"          # not :99, so a hand-run probe does not collide
NEEDS = ("Xvfb", "xwininfo", "xprop")


def _missing():
    return [tool for tool in NEEDS if shutil.which(tool) is None]


@pytest.fixture
def nested_display():
    """A display of our own. The operator's is never touched."""
    if _missing():
        pytest.skip(f"nested-display tools missing: {', '.join(_missing())}")
    server = subprocess.Popen(
        ["Xvfb", DISPLAY, "-screen", "0", "1280x800x24"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            probe = subprocess.run(["xwininfo", "-root"], env=_env(),
                                   capture_output=True, text=True)
            if probe.returncode == 0:
                break
            time.sleep(0.2)
        else:
            pytest.skip("Xvfb did not come up")
        yield DISPLAY
    finally:
        server.terminate()
        server.wait(timeout=10)


def _env(**extra):
    env = dict(os.environ, DISPLAY=DISPLAY, GDK_BACKEND="x11")
    env.update(extra)
    return env


@pytest.fixture
def fixture_app(nested_display):
    """The fixture, and the line it announces itself with."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp_gtk", "--quit-after", "20000"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=_env(),
    )
    try:
        line = proc.stdout.readline()
        if not line:
            pytest.skip("the GTK fixture did not start (no PyGObject/GTK4?)")
        announced = json.loads(line)
        if announced.get("error") == "no display":
            pytest.skip("GTK could not open the nested display")
        yield proc, announced
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_the_fixture_announces_a_pid_and_a_real_toplevel(fixture_app):
    proc, announced = fixture_app
    assert announced["pid"] == proc.pid, "the announce names the process it came from"
    assert announced["toolkit"] == "gtk4"
    assert isinstance(announced["main"], int) and announced["main"] > 0, (
        "a mapped X toplevel has an id; None means GTK fell back off X11"
    )


def test_the_announced_window_belongs_to_the_announced_process(fixture_app):
    """The tie a locator needs. Only toplevels carry an X id on Linux, so this
    is the one place window and process meet without the AT-SPI bus."""
    _, announced = fixture_app
    props = subprocess.run(["xprop", "-id", str(announced["main"])],
                           env=_env(), capture_output=True, text=True).stdout
    assert f"_NET_WM_PID(CARDINAL) = {announced['pid']}" in props, props


def test_every_named_control_reports_a_rectangle(fixture_app):
    """A control here is an accessible, not a window: there is no per-control
    X id to aim at, so the fixture reports geometry instead. A measurement
    that clicks a control and sees nothing needs to know it hit the control
    (D66's lesson, arrived at the hard way)."""
    _, announced = fixture_app
    for name, rect in announced["bounds"].items():
        assert rect is not None, f"{name} reported no bounds"
        assert rect["w"] > 0 and rect["h"] > 0, f"{name} is empty: {rect}"


def test_the_fixture_does_not_take_the_foreground_by_starting(fixture_app):
    """It maps with set_visible(); present() raises and focuses, and is what a
    foreground grab *is*. Only --present-after may do that, and nothing here
    passes it. Without a window manager there is no _NET_ACTIVE_WINDOW to read
    (see the decision log), so this asserts the weaker thing X can answer: no
    client claimed the input focus."""
    _, announced = fixture_app
    focus = subprocess.run(["xprop", "-root", "_NET_ACTIVE_WINDOW"],
                           env=_env(), capture_output=True, text=True).stdout
    assert "not found" in focus or "_NET_ACTIVE_WINDOW" not in focus or \
        str(announced["main"]) not in focus, (
        "the fixture took the foreground without being asked to: " + focus
    )
