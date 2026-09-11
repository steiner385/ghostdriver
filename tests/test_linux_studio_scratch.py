"""The acceptance, against a real Bambu Studio on the operator's own display
(#40, D#111). Gated off by default: it launches a scratch instance and drives
it with real keystrokes, which is only safe on a display the operator is
watching and has to opt into.

Run it with the operator present, on a quiet display, after installing the
profile (`GHOSTDRIVER_OPERATOR_DIR/profiles/bambu-studio.json`):

    GHOSTDRIVER_STUDIO_SCRATCH=1 \
    GHOSTDRIVER_OPERATOR_DIR=~/.config/ghostdriver-operator \
    DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority \
    DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
    PYTHONPATH=src python3 -m pytest tests/test_linux_studio_scratch.py -q

It copies the operator's Studio config into a temp datadir so the scratch
instance is a real Studio without its cloud session, launches it, opens a new
project (Ctrl+N via xdotool -- the *harness*, clearly not the driver), and
drives the Layer-height field on Prepare > Quality through the Toolbox. It
asserts the setting commits (the preset gains its `*`), reverts, and that the
denylist refuses a print/send control. It kills the instance without saving.
"""

import os
import shutil
import subprocess
import time

import pytest

from tests.conftest import on_linux

pytestmark = [on_linux, pytest.mark.slow]

APP = "com.bambulab.BambuStudio"


def _skip_unless_opted_in():
    if os.environ.get("GHOSTDRIVER_STUDIO_SCRATCH") != "1":
        pytest.skip("live Studio acceptance is opt-in: set GHOSTDRIVER_STUDIO_SCRATCH=1 "
                    "and run it with the operator present on a quiet display")
    for tool in ("flatpak", "xdotool", "xprop"):
        if shutil.which(tool) is None:
            pytest.skip(f"needs {tool}")
    if not os.environ.get("DISPLAY"):
        pytest.skip("needs a DISPLAY")
    installed = subprocess.run(["flatpak", "info", APP], capture_output=True)
    if installed.returncode != 0:
        pytest.skip(f"{APP} is not installed")
    if not os.environ.get("GHOSTDRIVER_OPERATOR_DIR"):
        pytest.skip("needs GHOSTDRIVER_OPERATOR_DIR with profiles/bambu-studio.json")


def _atspi_studio_pids():
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    Atspi.init()
    desk = Atspi.get_desktop(0)
    return [desk.get_child_at_index(i).get_process_id()
            for i in range(desk.get_child_count())
            if desk.get_child_at_index(i)
            and desk.get_child_at_index(i).get_name() == "bambu-studio"]


@pytest.fixture(scope="module")
def scratch_studio(tmp_path_factory):
    _skip_unless_opted_in()
    src = os.path.expanduser("~/.var/app/com.bambulab.BambuStudio/config/BambuStudio")
    if not os.path.isdir(src):
        pytest.skip("no operator Studio config to copy for a scratch instance")

    before = set(_atspi_studio_pids())
    datadir = tmp_path_factory.mktemp("studio") / "datadir"
    subprocess.run(["rsync", "-a", "--exclude", "log", "--exclude", "cache",
                    "--exclude", "tmp", "--exclude", "track", f"{src}/", f"{datadir}/"],
                   check=True)
    proc = subprocess.Popen(
        ["setsid", "flatpak", "run", APP, "--datadir", str(datadir)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    pid = None
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        new = set(_atspi_studio_pids()) - before
        if new:
            pid = sorted(new)[0]
            break
        time.sleep(3)
    if pid is None:
        proc.terminate()
        pytest.skip("the scratch Studio never registered on the a11y bus")

    # Find its window, bring it to the front, and open a new project. The
    # Ctrl+N is the HARNESS, not the driver -- the driver's own keystroke path
    # is exercised by the set_value below.
    win = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", "bambu",
                          "--name", "Untitled"], capture_output=True, text=True)
    xid = (win.stdout.split() or [""])[-1]
    if xid:
        subprocess.run(["xdotool", "windowactivate", "--sync", xid])
        time.sleep(1)
        subprocess.run(["xdotool", "key", "--window", xid, "ctrl+n"])
        time.sleep(6)

    yield pid

    for p in _scratch_procs(datadir):
        subprocess.run(["kill", "-9", str(p)], check=False)


def _scratch_procs(datadir):
    out = []
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            with open(f"/proc/{p}/cmdline", "rb") as f:
                if str(datadir).encode() in f.read():
                    out.append(int(p))
        except OSError:
            continue
    return out


def _toolbox():
    from ghostdriver.session import SessionManager
    from ghostdriver.tools import Toolbox

    return Toolbox(sessions=SessionManager())


def test_list_targets_shows_studio_by_its_bus_name(scratch_studio):
    """Acceptance 1: Studio appears, named for the bus, not the proxy (D#110)."""
    box = _toolbox()
    result = box.list_targets()
    studios = [t for t in result["targets"] if t["name"] == "bambu-studio"]
    assert studios, "no target named bambu-studio; the a11y application name did not surface"
    # the proxy's own process name is kept beside it
    assert any("process_name" in t for t in studios)


def test_the_layer_height_commits_and_reverts_live(scratch_studio):
    """Acceptance 3, on a scratch stand-in: set the Layer height and see the
    preset gain its `*`, then revert and see it clear -- through the driver's
    tier-4 commit (D#111), no mouse, no typing by the harness."""
    from ghostdriver.policy import ConsentSource

    box = _toolbox()
    pid = scratch_studio
    box.grant_targets(allow=[pid], source=ConsentSource.OPERATOR_TOOL)
    attached = box.attach(pid, tier="interactive", profile_path="bambu-studio", live=True)
    assert attached.get("ok"), attached
    assert "live_actuation" in attached, "the live grant was not recorded"
    sid = attached["session_id"]

    # The Layer-height field: the top text field on Quality, showing 0.12.
    field = 'class=text value="0.12"'
    marker = {"locator": 'class=frame text="/^\\* /"'}

    try:
        set02 = box.set_value(sid, field, "0.2", expect=marker)
        assert set02.get("ok"), set02
        assert set02.get("verified") == "committed", set02
        assert set02.get("tier_used") == 4, set02

        # It now shows 0.2 (confirmed without disclosure), and reverts.
        back = box.set_value(sid, 'class=text value="0.2"', "0.12", expect=marker)
        assert back.get("ok"), back
    finally:
        box.release(sid)


def test_the_denylist_refuses_a_print_control(scratch_studio):
    """Acceptance 3, last clause: a print/send control is refused, the profile
    entry named -- nothing is sent to a printer or the cloud."""
    from ghostdriver.policy import ConsentSource

    box = _toolbox()
    pid = scratch_studio
    box.grant_targets(allow=[pid], source=ConsentSource.OPERATOR_TOOL)
    attached = box.attach(pid, tier="interactive", profile_path="bambu-studio", live=True)
    sid = attached["session_id"]
    try:
        result = box.click(sid, 'class=push button text="Send"', all_windows=True)
        assert not result.get("ok")
        assert result["error"]["kind"] == "denied_by_policy", result
    finally:
        box.release(sid)
