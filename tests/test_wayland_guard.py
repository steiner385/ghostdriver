"""On a Wayland operator desktop, X is refused -- except where skipping it
is the honest answer (issue 215). Platform-neutral: the session type is
injected, and the refusal happens before Xlib is imported."""

import pytest

# Imported in the fixture, not here: a test module may not bind a backend
# package at import time (test_structure.py).
desktop_claim = display = session_type = tree = None


@pytest.fixture
def wayland(monkeypatch):
    global desktop_claim, display, session_type, tree
    from ghostdriver.backends.linux import desktop_claim, display, session_type, tree
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(desktop_claim, "_environments", {})


def test_the_x_connection_is_refused_on_a_wayland_desktop(wayland):
    with pytest.raises(session_type.X11Only):
        display._display()


def test_a_hidden_desktop_on_a_wayland_host_is_not_refused(wayland, monkeypatch):
    desktop_claim.register("hd-test", DISPLAY=":99")
    # Stop at the point where the real connection would open: reaching it
    # is the proof the guard let the hidden desktop through.
    reached = []
    monkeypatch.setattr(display, "_DISPLAYS", {"hd-test": "a connection"})
    with desktop_claim.desktop("hd-test"):
        reached.append(display._display())
    assert reached == ["a connection"]


def test_frame_correlation_is_skipped_not_refused_on_wayland(wayland, monkeypatch):
    def no_x():
        raise AssertionError("correlation touched X on a Wayland desktop")
    monkeypatch.setattr(display, "client_windows", no_x)

    class Frame:
        handle = 1
        rect = (0, 0, 10, 10)

    tree._correlate_frame(Frame(), pid=1)  # returns, does not raise


def test_the_minimized_watch_refuses_at_construction_on_wayland(wayland):
    """Minimized state is unobservable on Wayland (W4, D#221). The
    interference watch no longer refuses here: its foreground half reads
    AT-SPI and it says it does not watch the pointer
    (tests/test_interference_without_pointer.py, #225)."""
    from ghostdriver.backends.linux.isolate import MinimizedWatch
    with pytest.raises(session_type.X11Only, match="minimized watch"):
        MinimizedWatch(1)


def test_a_snapshot_the_platform_cannot_take_is_not_a_dead_target(wayland, monkeypatch):
    from ghostdriver.backends.linux import modality

    def x_only(pid):
        raise session_type.X11Only("no")
    monkeypatch.setattr(modality, "top_level_state", x_only)
    with pytest.raises(session_type.X11Only):
        modality.snapshot(1)


def test_an_observer_the_platform_cannot_supply_stops_the_action_before_it_runs():
    from ghostdriver.actuate import Actuator, Attempt, Tier
    from ghostdriver.backends import UnsupportedPlatform

    def observe():
        raise UnsupportedPlatform("foreground cannot be read on this desktop")

    ran = []
    result = Actuator(observe=observe, sleep=lambda s: None).perform(
        [Attempt(Tier.WINDOW_MESSAGE, lambda: ran.append(1) or True)])

    assert ran == []
    assert result.ok is False
    assert result.error["kind"] == "denied_by_environment"
    assert "foreground cannot be read" in result.error["message"]


def test_an_action_that_ran_is_not_reported_as_crashed_when_the_after_look_is_refused():
    """The refusal belongs before the action. After it, the action happened,
    and `_changes` promises it is not reported as a crash."""
    from ghostdriver.actuate import Actuator, Attempt, Tier
    from ghostdriver.backends import UnsupportedPlatform
    from ghostdriver.disturbance import Snapshot

    looks = iter([Snapshot(windows={1: "main"})])

    def observe():
        for snap in looks:
            return snap
        raise UnsupportedPlatform("gone mid-action")

    ran = []
    result = Actuator(observe=observe, sleep=lambda s: None).perform(
        [Attempt(Tier.WINDOW_MESSAGE, lambda: ran.append(1) or True)])

    assert ran == [1]
    assert result.ok is True
    assert result.disturbances == []


def test_the_pointer_is_refused_not_reported_as_the_origin_on_wayland(wayland):
    """`cursor` swallows X errors into (0, 0); the Wayland refusal must not
    be swallowed with them -- (0, 0) would be a confident wrong answer
    (found verifying on linux-host-a, #215)."""
    with pytest.raises(session_type.X11Only):
        display.cursor()


def test_capture_on_wayland_says_why_rather_than_blaming_the_handle(wayland, monkeypatch):
    """With no correlation on Wayland there is no xid, and the old message
    called the frame "a control" -- the wrong cause (found on linux-host-a, #215)."""
    from ghostdriver.backends.linux import reading
    monkeypatch.setattr(reading, "_toplevel_xid", lambda handle: None)
    with pytest.raises(session_type.X11Only, match="capture"):
        reading.capture_window(1)


@pytest.mark.parametrize("call", [
    lambda d: d.is_hidden(1),
    lambda d: d.exists(1),
    lambda d: d.window_pid(1),
    lambda d: d.is_modal(1),
    lambda d: d.window_name(1),
])
def test_no_x_fact_degrades_to_a_default_on_wayland(wayland, call):
    """`display.py` swallows X errors into defaults (False, None, ""). On a
    Wayland desktop the refusal must not be swallowed with them: "not
    hidden", "gone", "not modal" would each be a confident wrong answer
    (#215)."""
    with pytest.raises(session_type.X11Only):
        call(display)


# --- final-review fixes: the environment is not the only witness ---------

class _FakeConn:
    def __init__(self, extensions):
        self._extensions = extensions

    def list_extensions(self):
        return list(self._extensions)


@pytest.fixture
def silent_env(monkeypatch):
    """A server launched outside the graphical session: DISPLAY only, no
    XDG_SESSION_TYPE, no WAYLAND_DISPLAY -- measured on linux-host-a (#215)."""
    global desktop_claim, display, session_type, tree
    from ghostdriver.backends.linux import desktop_claim, display, session_type, tree
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(desktop_claim, "_environments", {})
    monkeypatch.setattr(display, "_DISPLAYS", {})
    monkeypatch.setattr(display, "_XWAYLAND", {})


def test_an_xwayland_server_is_wayland_even_when_the_environment_is_silent(
        silent_env, monkeypatch):
    monkeypatch.setattr(display, "_open", lambda name: _FakeConn(["XWAYLAND", "XTEST"]))
    with pytest.raises(session_type.X11Only):
        display._display()
    assert session_type.display_server() == "wayland"


def test_a_plain_x_server_is_x11_when_the_environment_is_silent(silent_env, monkeypatch):
    conn = _FakeConn(["XTEST", "X-Resource"])
    monkeypatch.setattr(display, "_open", lambda name: conn)
    assert display._display() is conn
    assert session_type.display_server() == "x11"


def test_the_mcp_list_targets_still_lists_on_wayland(wayland, monkeypatch):
    """The CLI's list-targets never asked a class name; the tool does, and
    it reached X (found by the final review, #215)."""
    import os

    from ghostdriver import backends
    from ghostdriver.session import SessionManager
    from ghostdriver.tools import Toolbox

    linux = backends.load("linux")
    monkeypatch.setattr(backends, "current", lambda: linux)
    me = os.getpid()
    monkeypatch.setattr(tree, "top_level_windows", lambda pid: [7] if pid == me else [])
    monkeypatch.setattr(tree, "application_name", lambda pid: None)

    result = Toolbox(SessionManager()).list_targets()

    assert result["ok"] is True, result
    assert [t["pid"] for t in result["targets"]] == [me]


def test_attach_can_ask_whether_the_main_window_is_minimized_on_wayland(wayland):
    """`attach` asks `winapi.is_minimized` of the main window; the shim
    refused it, so attach failed on every Linux desktop. On Wayland nothing
    can see it yet (W4), and False means "no hint", not a claim."""
    from ghostdriver.backends.linux import winapi
    assert winapi.is_minimized(7) is False


def test_is_minimized_reads_the_frame_on_x11(monkeypatch):
    from ghostdriver.backends.linux import display, tree, winapi
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setattr(tree, "frame_xid_of", lambda handle: 0x500)
    monkeypatch.setattr(display, "is_hidden", lambda xid: xid == 0x500)
    assert winapi.is_minimized(7) is True


def test_ink_on_wayland_is_refused_not_zero(wayland, monkeypatch):
    """0.0 would read as "paints nothing", dropping D66's read_unreliable
    flag on a control that renders content (final review, #215)."""
    from ghostdriver.backends.linux import reading
    monkeypatch.setattr(reading, "_toplevel_xid", lambda handle: None)
    with pytest.raises(session_type.X11Only):
        reading.ink_fraction(1)


def test_an_empty_read_that_cannot_be_checked_says_so():
    from ghostdriver import disclosure
    value = disclosure.note_unreliable({"value": ""}, None)
    assert "read_unreliable" not in value
    assert "could not be checked" in value["note"]
