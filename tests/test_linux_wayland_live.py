"""W1-W4 and tier-1 acting, on the operator's own Wayland desktop (#221).

**Opt-in, because it takes the desktop over:** it launches two GTK fixtures
and moves focus between them with mutter's RemoteDesktop keyboard (Alt, Tab,
Super, H, Escape -- nothing is typed). Run it only when the person at the
machine has handed it over:

    GHOSTDRIVER_LIVE_WAYLAND=1 PYTHONPATH=src python -m pytest tests/test_linux_wayland_live.py

The work happens in `tests/linux_wayland_live_probe.py`, a separate process,
so the pytest process does not spend its one accessibility bus on it (the
same reason as `tests/linux_atspi_probe.py`). What each assertion pins was
first measured on linux-host-a (GNOME 50.1, Wayland) on 2026-10-09.
"""

import itertools
import json
import os
import subprocess
import sys

import pytest

from tests.conftest import on_linux

pytestmark = [on_linux, pytest.mark.slow]


def _wayland_session() -> bool:
    return (os.environ.get("XDG_SESSION_TYPE") == "wayland"
            or bool(os.environ.get("WAYLAND_DISPLAY")))


@pytest.fixture(scope="module")
def live() -> dict:
    if os.environ.get("GHOSTDRIVER_LIVE_WAYLAND") != "1":
        pytest.skip("takes the operator's desktop over; set GHOSTDRIVER_LIVE_WAYLAND=1 "
                    "only when the person at the machine has handed it over")
    if not _wayland_session():
        pytest.skip("not a Wayland session")
    done = subprocess.run(
        [sys.executable, "-m", "tests.linux_wayland_live_probe"],
        capture_output=True, text=True, timeout=300,
        env=dict(os.environ, PYTHONPATH="src", GHOSTDRIVER_TRACE="0"),
    )
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith("{")), None)
    if line is None:
        pytest.fail("the live probe printed no report "
                    f"(exit {done.returncode}):\n{done.stdout[-800:]}\n{done.stderr[-800:]}")
    return json.loads(line)


def test_w1_active_tracks_focus_for_both_kinds_of_client(live):
    """After every switch exactly one fixture frame holds `STATE_ACTIVE`, and
    the two alternate -- native Wayland and XWayland alike."""
    actives = [s["fixture_active"] for s in live["switches"]]
    assert all(len(a) == 1 for a in actives), actives
    assert all(a != b for a, b in itertools.pairwise(actives)), actives


def test_w1_the_x_server_agrees_for_the_x_client_and_only_for_it(live):
    """Ground truth: `_NET_ACTIVE_WINDOW` names the X fixture exactly when
    AT-SPI says it is active -- and names nothing of the Wayland one, which
    is why X was refused on this desktop (D#215)."""
    x_pid, x_xid = live["pids"]["x11"], live["pids"]["x11_xid"]
    for s in live["switches"]:
        assert (s["x_active"] == x_xid) == (s["fixture_active"] == [x_pid]), s


def test_w1_each_switch_announces_itself(live):
    for s in live["switches"]:
        activated = {pid for _, kind, _, pid in s["events"] if kind == "activate"}
        assert s["fixture_active"][0] in activated, s["events"]


def test_w2_a_modal_is_a_frame_marked_modal_with_no_owner_relation(live):
    modals = [f for f in live["w2_modal"]["frames"] if "modal" in f["states"]]
    assert [f["name"] for f in modals] == ["Confirm"]
    assert all(f["relations"] == [] for f in modals)


def test_w3_frame_extents_are_window_relative(live):
    assert all(f["extents"][:2] == [0, 0] for f in live["w3_frames"]), live["w3_frames"]


def test_w4_a_minimized_frame_looks_shown(live):
    """The one thing AT-SPI cannot say on Wayland: a minimized GTK4 frame
    keeps SHOWING and VISIBLE. Only focus leaving it shows anything moved."""
    if not live.get("wayland_focused_for_w234"):
        pytest.skip("could not focus the Wayland fixture to minimize it")
    minimized = live["w4_minimized"]
    frame = next(f for f in minimized["frames"] if "modal" not in f["states"])
    assert {"showing", "visible"} <= set(frame["states"])
    assert "iconified" not in frame["states"]
    assert minimized["fixture_active"] != [live["pids"]["wayland"]]


def test_the_actuator_can_observe_a_wayland_target(live):
    """The snapshot the actuator takes around each action comes from AT-SPI
    here (#221): the target is alive, and the front -- another application's
    -- is not one of its windows. Without this, an empty disturbance list
    could be a silent miss."""
    snap = live["act_snapshot"]
    assert snap["alive"] is True and snap["windows"] >= 1
    assert snap["foreground"] == -live["pids"]["x11"]
    assert snap["foreground_is_target"] is False


def test_attach_works_on_a_wayland_desktop(live):
    assert live["act_attach"]["ok"] is True, live["act_attach"]


@pytest.mark.parametrize("step, saw", [
    ("act_click", {"event": "toolbar", "name": "Save"}),
    ("act_set_value", {"event": "bound_changed", "text": "w221"}),
])
def test_a_tier_1_action_lands_and_the_front_does_not_move(live, step, saw):
    """The promise, on Wayland: with another application at the front, the
    action reaches the target through AT-SPI and focus stays where it was."""
    result = live[step]
    assert result["ok"] is True, result
    assert result["tier_used"] == 1
    assert saw in result["fixture_saw"], result["fixture_saw"]
    assert result["front_after"] == live["act_front_before"]
    assert result["disturbances"] == []


def test_nothing_is_left_behind_and_the_operators_front_is_back(live):
    assert live["left_running"] == []
    assert live["operator_active_after"] == live["operator_active_before"]
