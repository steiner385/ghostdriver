"""The interference watch where the pointer cannot be read (issue 225).

On a Wayland desktop the foreground can be read from AT-SPI (W1, D#221) and
the pointer cannot (W5): there is no global pointer query. The watch used to
refuse there outright, which refused macro replay and workflow runs with it.
Now it watches what it can and says what it cannot, so an empty event list
is never read as "the pointer did not move". Platform-neutral: samplers are
injected and the session type is set, so this runs on any platform.
"""

import pytest

from ghostdriver.interference import InterferenceWatch


def test_a_watch_with_no_pointer_still_reports_the_foreground():
    watch = InterferenceWatch(7, foreground_pid=lambda: 0, cursor=None)
    watch.observe(7, None, last_foreground=3, last_cursor=None)
    assert [e["kind"] for e in watch.events()] == ["foreground_taken"]


def test_a_watch_with_no_pointer_says_so():
    assert InterferenceWatch(7, foreground_pid=lambda: 0, cursor=None).watches_pointer is False
    assert InterferenceWatch(7, foreground_pid=lambda: 0,
                             cursor=lambda: (0, 0)).watches_pointer is True


def test_a_watch_with_no_pointer_runs(monkeypatch):
    """The poll thread itself must not call a sampler it does not have."""
    import time
    fronts = iter([3, 3, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7])
    watch = InterferenceWatch(7, foreground_pid=lambda: next(fronts, 7), cursor=None,
                              poll_s=0.005)
    watch.start()
    time.sleep(0.1)
    watch.stop()
    assert [e["kind"] for e in watch.events()] == ["foreground_taken"]


@pytest.fixture
def wayland(monkeypatch):
    from ghostdriver.backends.linux import desktop_claim
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(desktop_claim, "_environments", {})


def test_the_linux_watch_on_wayland_reads_the_front_from_at_spi(wayland, monkeypatch):
    from ghostdriver.backends.linux import tree
    from ghostdriver.backends.linux.interference import InterferenceWatch as LinuxWatch
    monkeypatch.setattr(tree, "active_frame", lambda: (42, 1073741824))
    watch = LinuxWatch(42)
    assert watch.watches_pointer is False
    assert watch._foreground_pid() == 42


def test_nothing_at_the_front_is_pid_zero_on_wayland(wayland, monkeypatch):
    from ghostdriver.backends.linux import tree
    from ghostdriver.backends.linux.interference import InterferenceWatch as LinuxWatch
    monkeypatch.setattr(tree, "active_frame", lambda: None)
    assert LinuxWatch(42)._foreground_pid() == 0


def test_a_result_says_the_pointer_was_not_watched():
    from ghostdriver.interference import watch_fields
    blind = InterferenceWatch(7, foreground_pid=lambda: 0, cursor=None)
    sighted = InterferenceWatch(7, foreground_pid=lambda: 0, cursor=lambda: (0, 0))
    assert watch_fields(sighted, []) == {}
    assert watch_fields(sighted, [{"kind": "cursor_moved"}]) == {
        "interference": [{"kind": "cursor_moved"}]}
    assert "pointer" in watch_fields(blind, [])["interference_unwatched"]


def test_macro_replay_runs_on_wayland_and_says_what_it_did_not_watch(tmp_path, monkeypatch):
    """The macro tool used to refuse on Wayland because its watch did. Now
    it runs, and its result carries the note (#225). Backend-free: the
    watch and the macro body are fakes."""
    import os

    from ghostdriver import backends
    from ghostdriver.operator import ENV_VAR
    from ghostdriver.policy import ConsentSource, Tier
    from ghostdriver.session import SessionManager
    from ghostdriver.tools import Toolbox, macro

    monkeypatch.setenv(ENV_VAR, str(tmp_path / "ops"))

    class Backend:
        def InterferenceWatch(self, pid, family=None):
            return InterferenceWatch(pid, foreground_pid=lambda: 0, cursor=None)

    monkeypatch.setattr(backends, "current", lambda: Backend())
    monkeypatch.setattr(macro, "run_macro_body",
                        lambda *a, **k: {"ok": True, "steps": [], "completed": 0})
    box = Toolbox(SessionManager())
    box.macro_save("noop", [{"tool": "describe", "args": {}}], tier="read_only")
    pid = os.getpid()
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    sid = box.sessions.attach(pid, command_line=["pytest"], tier=Tier.READ_ONLY).session_id

    out = box.macro_replay(sid, "noop")

    assert out["ok"] is True, out
    assert "pointer" in out["interference_unwatched"]
