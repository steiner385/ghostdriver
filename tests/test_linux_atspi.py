"""L1: a nested X server with an AT-SPI bus of its own -- which is also the
Linux isolation strategy, not merely the way these tests are run.

`docs/LINUX.md` names three pieces: `Xvfb`, `at-spi-bus-launcher`, and
something to list the tree. It turns out to need a fourth, and the fourth is
the one that makes the isolation real: **its own D-Bus session bus.** AT-SPI
is discovered *through* the session bus, so a nested display sharing the
operator's bus would find the operator's accessibility bus and see the
operator's applications. `dbus-run-session` is what keeps them apart, and
`test_the_nested_bus_sees_only_the_fixture` is what proves it did.
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

from tests.conftest import on_linux

pytestmark = [on_linux, pytest.mark.slow]

DISPLAY = ":96"
BUS_LAUNCHER = "/usr/libexec/at-spi-bus-launcher"


def _unavailable():
    missing = [t for t in ("Xvfb", "dbus-run-session") if shutil.which(t) is None]
    if not os.path.exists(BUS_LAUNCHER):
        missing.append(BUS_LAUNCHER)
    return missing


@pytest.fixture(scope="module")
def report():
    """One nested stack, one probe, parsed once: it costs several seconds to
    stand up, and every test here asks a question of the same tree."""
    missing = _unavailable()
    if missing:
        pytest.skip("nested AT-SPI stack unavailable: " + ", ".join(missing))

    server = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", "1280x800x24"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        inner = (f"{BUS_LAUNCHER} --launch-immediately & sleep 3; "
                 f"exec {sys.executable} -m tests.linux_atspi_probe")
        done = subprocess.run(
            ["dbus-run-session", "--", "bash", "-c", inner],
            capture_output=True, text=True, timeout=120,
            env=dict(os.environ, DISPLAY=DISPLAY, GSETTINGS_BACKEND="memory",
                     PYTHONPATH="src"),
        )
        line = next((ln for ln in done.stdout.splitlines()
                     if ln.startswith("{") and '"desktop_children"' in ln), None)
        if line is None:
            pytest.skip("the AT-SPI probe produced no report:\n" + done.stdout[-800:]
                        + "\n" + done.stderr[-800:])
        yield json.loads(line)
    finally:
        server.terminate()
        server.wait(timeout=10)


def test_the_nested_bus_sees_only_the_fixture(report):
    """The isolation guarantee, asserted rather than assumed. The operator is
    running a full desktop on :0; if any of it were visible here the nested
    display would not be isolating anything."""
    assert report["desktop_children"] == 1, (
        "the nested a11y bus should hold exactly the fixture, but holds: "
        + ", ".join(f"{a['name']}({a['pid']})" for a in report["apps"])
    )
    assert report["found"], "the fixture did not appear on its own bus"


def test_the_application_node_is_named(report):
    """`Unnamed` is what an application node reports when nothing set a program
    name, and it leaves a locator nothing to match the application on -- the
    counterpart of the process/main-window pairing on Windows."""
    assert report["apps"][0]["name"] == "ghostdriver-fixture"
    assert report["apps"][0]["pid"] == report["announced"]["pid"]


def test_the_toplevel_is_a_frame_carrying_the_window_title(report):
    """A `WindowNode` on Linux is an AT-SPI frame, not an X window: this is the
    node a window locator has to resolve to."""
    frames = [n for n in report["tree"] if n["role"] == "frame"]
    assert [f["name"] for f in frames] == ["Ghostdriver GTK fixture"], frames


def test_the_owner_drawn_grid_is_one_node_with_no_children(report):
    """D50's shape, and the reason exact text out of it is a real problem: the
    grid paints three rows and exposes none of them. Anything that reads its
    contents has to come from a copy route, not from the tree."""
    grid = report["by_name"]["results grid"]
    assert grid["children"] == 0, "the grid gained children; it is no longer owner-drawn"
    assert report["announced"]["grid_rows"] > grid["children"], (
        "the grid paints rows that the accessible tree does not expose -- "
        "that asymmetry is the whole point of this fixture shape"
    )


def test_the_drawn_button_is_reachable_by_name(report):
    """A DrawingArea defaults to a generic panel with no name. It is only
    locatable because the fixture gives it an accessible role, which is
    itself the finding: an owner-drawn control that does not do this cannot
    be named at all."""
    assert report["by_name"]["Recalculate"]["role"] == "push button"
