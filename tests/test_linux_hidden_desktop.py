"""`HiddenDesktop` end to end (#40 slice 5b): prepare, launch, drive the
fixture through the ordinary contract, teardown -- and the claim (D#40f)
that makes a second, unrelated caller in the same process refuse rather
than silently read the nested display's tree.

The whole thing runs in `tests/linux_hidden_desktop_probe.py`, a separate
process: `HiddenDesktop`'s claim never releases, so the pytest process
itself must not spend its own one accessibility bus on it -- `test_mcp_
server.py` and other tests in the same session need the operator's own
reachable, same reasoning as `tests/linux_atspi_probe.py`.

Slower than most of this backend's tests (a private D-Bus session, a
headless `gnome-shell` and its Xwayland all start from scratch -- #217),
so `pytest.mark.slow`, matching `test_linux_watch.py` and `test_linux_atspi.
py`, the two existing tests that stand up a comparable stack.

The backend import is inside each function, never at module scope
(`test_no_test_module_binds_a_platform_at_import_time`).
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

from tests.conftest import on_linux

pytestmark = [on_linux, pytest.mark.slow]

NEEDED = ("dbus-daemon", "dbus-send", "gnome-shell")


def _unavailable() -> list[str]:
    return [t for t in NEEDED if shutil.which(t) is None]


@pytest.fixture(scope="module")
def report() -> dict:
    missing = _unavailable()
    if missing:
        pytest.skip("hidden_desktop needs: " + ", ".join(missing))

    done = subprocess.run(
        [sys.executable, "-m", "tests.linux_hidden_desktop_probe"],
        capture_output=True, text=True, timeout=60,
        env=dict(os.environ, PYTHONPATH="src"),
    )
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith("{")), None)
    if line is None:
        pytest.fail(
            "the hidden-desktop probe printed no report "
            f"(exit {done.returncode}):\nstdout: {done.stdout[-800:]}\n"
            f"stderr: {done.stderr[-800:]}"
        )
    return json.loads(line)


def test_prepare_claims_the_process_for_this_desktop(report):
    assert report["claimed_by"] == "ghostdriver-test"


def test_a_second_hidden_desktop_cannot_also_claim_it(report):
    assert report["second_hidden_desktop_refused"] is True


def test_the_operators_own_call_refuses_while_the_claim_holds(report):
    """The isolation guarantee from the caller's side: an ordinary call
    reaching for the operator's own desktop instead of this one, in the
    same process, is told why rather than answered wrong."""
    assert report["operator_call_refused"] is True


def test_launch_starts_the_fixture_and_the_tree_finds_it_through_run(report):
    assert report["found_fixture"] is True


def test_the_target_is_an_x_client_of_the_nested_display(report):
    """Not the operator's: its DISPLAY is the nested Xwayland's, and it was
    given no WAYLAND_DISPLAY to open on the operator's desktop with (#217)."""
    assert report["target_display"] == report["nested_display"]
    assert report["target_wayland_display"] is None


def test_teardown_leaves_nothing_running(report):
    """Every failed run on linux-host-a left an X server and a private bus behind;
    a finished one must leave nothing at all (#217)."""
    assert report["left_running"] == []
    assert report["runtime_removed"] is True
