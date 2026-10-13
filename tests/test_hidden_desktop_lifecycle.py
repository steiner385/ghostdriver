"""`HiddenDesktop`'s lifecycle, without a desktop (issue 217).

GNOME 50 removed `gnome-shell --x11`, so the nested display is now a
headless `gnome-shell --wayland` whose own Xwayland hosts the target as an
X client. These pin the pieces that do not need one running -- they are
platform-neutral, so they run on Windows too:

* which Xwayland display the shell chose is read from its own log line;
* a `prepare` that fails part-way tears down what it started (it did not:
  every failed run on linux-host-a left an `Xvfb` and a `dbus-daemon` behind);
* the target never inherits the operator's `WAYLAND_DISPLAY`, which would
  put a Qt or Chromium target on the operator's own desktop;
* the X connection to a hidden desktop uses that desktop's cookie.
"""

import os

import pytest


def test_the_xwayland_display_is_read_from_the_shells_own_log():
    from ghostdriver.backends.linux import hidden_desktop
    log = ("libmutter-Message: 09:46:32.377: Using public X11 display :2, "
           "(using unix:/tmp/.X11-unix/X3 for managed services)\n")
    assert hidden_desktop._public_display(log) == ":2"
    assert hidden_desktop._public_display("nothing yet\n") is None


def test_a_prepare_that_fails_part_way_tears_down_what_it_started(monkeypatch, tmp_path):
    from ghostdriver.backends.linux import desktop_claim, hidden_desktop

    monkeypatch.setattr(desktop_claim, "_owner", None)
    monkeypatch.setattr(desktop_claim, "_environments", {})
    monkeypatch.setattr(hidden_desktop, "_unavailable", lambda: [])
    # Neither reaper may reach the host's own systemd or /tmp from here.
    monkeypatch.setattr(hidden_desktop, "_user_systemd", lambda: False)
    monkeypatch.setattr(hidden_desktop, "_reap_abandoned_runtimes", lambda prefix, root=None: [])
    instance = hidden_desktop.HiddenDesktop(name="hd-lifecycle")
    torn = []
    monkeypatch.setattr(instance, "teardown", lambda: torn.append(True))
    monkeypatch.setattr(instance, "_start_private_bus", lambda: "unix:path=/x")
    # Its own runtime directory under pytest's, since teardown is replaced.
    monkeypatch.setattr(hidden_desktop.tempfile, "mkdtemp", lambda prefix="": str(tmp_path))

    def shell_fails(bus):
        raise hidden_desktop.Unsupported("the shell would not start")
    monkeypatch.setattr(instance, "_start_shell", shell_fails)

    with pytest.raises(hidden_desktop.Unsupported):
        instance.prepare()
    assert torn == [True]


def test_the_target_never_inherits_the_operators_wayland_display(monkeypatch):
    from ghostdriver.backends.linux import hidden_desktop
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    env = hidden_desktop._target_env(display=":2", xauthority="/r/auth",
                                     bus="unix:path=/b", atspi="unix:path=/a",
                                     runtime="/r")
    assert "WAYLAND_DISPLAY" not in env
    assert env["XDG_SESSION_TYPE"] == "x11"
    assert env["DISPLAY"] == ":2"
    assert env["GDK_BACKEND"] == "x11"
    assert env["QT_QPA_PLATFORM"] == "xcb"
    assert env["XDG_RUNTIME_DIR"] == "/r"


def test_a_hidden_desktops_x_connection_uses_its_own_cookie(monkeypatch):
    from ghostdriver.backends.linux import desktop_claim, display

    monkeypatch.setattr(desktop_claim, "_environments", {})
    monkeypatch.setattr(desktop_claim, "_owner", None)
    monkeypatch.setattr(display, "_DISPLAYS", {})
    monkeypatch.setenv("XAUTHORITY", "/operator/cookie")
    desktop_claim.register("hd-cookie", DISPLAY=":2", XAUTHORITY="/nested/cookie")
    seen = []

    def fake_open(name):
        seen.append((name, os.environ.get("XAUTHORITY")))
        return object()
    monkeypatch.setattr(display, "_open", fake_open)

    with desktop_claim.desktop("hd-cookie"):
        display._display()

    assert seen == [(":2", "/nested/cookie")]
    assert os.environ["XAUTHORITY"] == "/operator/cookie"


def test_teardown_finds_the_mounts_left_in_its_runtime_directory():
    """The nested shell can activate the document portal, which FUSE-mounts
    itself under the runtime directory; a mount left there makes the
    directory impossible to remove (measured on linux-host-a, #217)."""
    from ghostdriver.backends.linux import hidden_desktop
    mounts = (
        "portal /tmp/ghostdriver-desktop-ab12/doc fuse.portal rw,nosuid 0 0\n"
        "portal /run/user/1000/doc fuse.portal rw,nosuid 0 0\n"
        "tmpfs /tmp tmpfs rw 0 0\n"
    )
    assert hidden_desktop._mounts_under("/tmp/ghostdriver-desktop-ab12", mounts) == [
        "/tmp/ghostdriver-desktop-ab12/doc"]
    assert hidden_desktop._mounts_under("/tmp/ghostdriver-desktop-ab", mounts) == []


def test_what_belongs_to_a_desktop_is_found_by_its_runtime_directory(tmp_path):
    """A nested shell does not always die on SIGTERM, and outlived its
    harness three times in one run on linux-host-a (#217). What belongs to a nested
    desktop is whatever carries its private XDG_RUNTIME_DIR -- the shell,
    its Xwayland, the portals it activated -- so that is what teardown
    sweeps. Found here against fake /proc entries."""
    from ghostdriver.backends.linux import hidden_desktop

    proc = tmp_path / "proc"
    for pid, runtime in ((101, "/tmp/ghostdriver-desktop-ab12"),
                         (102, "/run/user/1000"),
                         (103, "/tmp/ghostdriver-desktop-ab12")):
        (proc / str(pid)).mkdir(parents=True)
        (proc / str(pid) / "environ").write_bytes(
            b"HOME=/h\0XDG_RUNTIME_DIR=" + runtime.encode() + b"\0")
    (proc / "self").mkdir()

    assert hidden_desktop._processes_in("/tmp/ghostdriver-desktop-ab12", proc=str(proc)) == [101, 103]


def test_a_missing_xwayland_is_named_not_met_at_connect(monkeypatch):
    """Without the Xwayland binary the headless shell still announces an X
    display, and nothing ever answers on it: CI's first Linux run failed
    with "connection refused" (mutter only recommends the package). So it
    is a requirement, named up front like the others (#217)."""
    import types

    from ghostdriver.backends.linux import hidden_desktop
    monkeypatch.setattr(hidden_desktop.shutil, "which",
                        lambda tool: None if tool == "Xwayland" else f"/usr/bin/{tool}")
    monkeypatch.setattr(hidden_desktop.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(stdout="--headless", stderr=""))
    assert hidden_desktop._unavailable() == ["Xwayland"]


def test_a_desktop_slice_is_named_for_its_owner_and_read_back():
    """An owner killed before teardown left whole desktops running on linux-host-a,
    and one fed RustDesk a dead DISPLAY (#231). Each desktop's processes go
    in a slice named for the owning pid, which is how a later run tells an
    abandoned slice from a live one. No dash in the part after the prefix:
    systemd reads a dash in a slice name as a parent slice."""
    from ghostdriver.backends.linux import hidden_desktop
    unit = hidden_desktop._slice_name(4242, 987654, "ghostdriver-test")
    assert unit == "ghostdriver_desktop_4242_987654_ghostdrivertest.slice"
    assert "-" not in unit
    assert hidden_desktop._slice_owner(unit) == (4242, 987654)
    assert hidden_desktop._slice_owner("user.slice") is None
    assert hidden_desktop._slice_owner("ghostdriver_desktop_4242_x.slice") is None


def test_the_scope_runs_under_the_operators_manager_and_hands_on_only_paths(monkeypatch):
    """`systemd-run` finds the user manager through the operator's runtime
    directory and bus, so it must run with those; the desktop's private pair
    reaches the command through `env`. Nothing else goes on the command
    line, which any user can read from /proc."""
    from ghostdriver.backends.linux import hidden_desktop
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    private = {"XDG_RUNTIME_DIR": "/tmp/gd-x", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/gd-x/b",
               "SECRET_TOKEN": "hunter2"}

    argv = hidden_desktop._scoped(["gnome-shell", "--headless"], "s.slice", private)
    assert argv[:2] == ["systemd-run", "--user"] and "--slice=s.slice" in argv
    assert argv[argv.index("--") + 1:] == [
        "env", "XDG_RUNTIME_DIR=/tmp/gd-x", "DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/gd-x/b",
        "gnome-shell", "--headless"]
    assert not any("hunter2" in a for a in argv)

    outer = hidden_desktop._operator_env(private)
    assert outer["XDG_RUNTIME_DIR"] == "/run/user/1000"
    assert outer["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1000/bus"
    assert hidden_desktop._scoped(["x"], None, private) == ["x"]


def test_a_shell_before_gnome_50_is_not_scoped(monkeypatch):
    """GNOME Shell 46 in a user unit asks systemd on the desktop's private
    bus to start its X11 services, fails, and never brings Xwayland up --
    every nested probe on CI's Ubuntu 24.04 timed out (#231). 50 has no
    such call. No version at all is treated as too old."""
    import types

    from ghostdriver.backends.linux import hidden_desktop
    for printed, scoped in (("GNOME Shell 46.0\n", False), ("GNOME Shell 49.4\n", False),
                            ("GNOME Shell 50.1\n", True), ("GNOME Shell 51.alpha\n", True),
                            ("", False)):
        monkeypatch.setattr(hidden_desktop.subprocess, "run",
                            lambda *a, out=printed, **k: types.SimpleNamespace(stdout=out))
        assert hidden_desktop._shell_takes_a_scope() is scoped, printed

    def missing(*a, **k):
        raise FileNotFoundError("gnome-shell")
    monkeypatch.setattr(hidden_desktop.subprocess, "run", missing)
    assert hidden_desktop._shell_takes_a_scope() is False


def test_without_a_user_manager_the_desktop_is_built_unscoped(monkeypatch):
    """An ssh shell may have no user manager; that must not stop a desktop."""
    import types

    from ghostdriver.backends.linux import hidden_desktop
    monkeypatch.setattr(hidden_desktop.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(hidden_desktop.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=1))
    assert hidden_desktop._user_systemd() is False


def test_only_abandoned_desktop_slices_are_reaped(monkeypatch):
    """The next `prepare` stops what a killed owner left; it never touches a
    slice whose owner is alive, its own, or a unit that is not a desktop's."""
    import types

    from ghostdriver.backends.linux import hidden_desktop
    listing = ("ghostdriver_desktop_111_5_a.slice loaded active active Slice\n"
               "ghostdriver_desktop_222_5_b.slice loaded active active Slice\n"
               f"ghostdriver_desktop_{os.getpid()}_5_c.slice loaded active active Slice\n"
               "app.slice loaded active active Slice\n")
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return types.SimpleNamespace(stdout=listing if "list-units" in argv else "")

    monkeypatch.setattr(hidden_desktop.subprocess, "run", run)
    monkeypatch.setattr(hidden_desktop, "_is_abandoned",
                        lambda owner, started, proc="/proc": owner != 222)
    assert hidden_desktop._reap_abandoned_slices() == ["ghostdriver_desktop_111_5_a.slice"]
    assert [c for c in calls if "stop" in c] == [
        ["systemctl", "--user", "stop", "ghostdriver_desktop_111_5_a.slice"]]


def test_a_slice_is_abandoned_when_its_owner_exited_or_its_pid_was_reused(tmp_path):
    """Gone means no process has the pid, or the one that does started at
    another time -- the pid was reused while the slice sat there. The start
    time is the kernel's own (stat field 22), compared only with itself."""
    from ghostdriver.backends.linux import hidden_desktop
    proc = tmp_path / "proc"
    (proc / "500").mkdir(parents=True)
    # A command name with a space and a ')' in it, which a naive split misreads.
    rest = " ".join(["S"] + ["0"] * 18 + ["777000"] + ["0"] * 10)
    (proc / "500" / "stat").write_text(f"500 (py thon) x) {rest}\n")

    assert hidden_desktop._process_start(500, proc=str(proc)) == 777000
    assert hidden_desktop._is_abandoned(500, 777000, proc=str(proc)) is False
    assert hidden_desktop._is_abandoned(500, 123, proc=str(proc)) is True
    assert hidden_desktop._is_abandoned(499, 777000, proc=str(proc)) is True


def test_this_process_reads_its_own_start_time():
    """The real /proc, so the field arithmetic is checked against the kernel."""
    import sys

    from ghostdriver.backends.linux import hidden_desktop
    if sys.platform != "linux":
        pytest.skip("no /proc")
    started = hidden_desktop._process_start(os.getpid())
    assert isinstance(started, int) and started > 0
    assert hidden_desktop._is_abandoned(os.getpid(), started) is False


def test_only_unused_and_settled_runtime_directories_are_swept(monkeypatch, tmp_path):
    """Stopping a dead owner's slice ends its processes, not its directory,
    and the portal's FUSE mount in it outlives the portal (#231). Swept: a
    directory no process carries, older than the grace period. Kept: one in
    use, one too young to have its first process yet, and anything else."""
    import time

    from ghostdriver.backends.linux import hidden_desktop
    old = time.time() - 2 * hidden_desktop.RUNTIME_GRACE_S
    for leaf, mtime in (("gd-x-dead", old), ("gd-x-live", old), ("gd-x-new", None), ("other", old)):
        (tmp_path / leaf).mkdir()
        if mtime:
            os.utime(tmp_path / leaf, (mtime, mtime))
    live = str(tmp_path / "gd-x-live")
    monkeypatch.setattr(hidden_desktop, "_processes_in", lambda path: [9] if path == live else [])
    unmounted = []
    monkeypatch.setattr(hidden_desktop.subprocess, "run",
                        lambda argv, **kw: unmounted.append(argv[-1]))
    monkeypatch.setattr(hidden_desktop, "_mounts_under",
                        lambda path, mounts: [path + "/doc"] if path.endswith("dead") else [])

    assert hidden_desktop._reap_abandoned_runtimes("gd-x-", root=str(tmp_path)) == [
        str(tmp_path / "gd-x-dead")]
    assert unmounted == [str(tmp_path / "gd-x-dead") + "/doc"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["gd-x-live", "gd-x-new", "other"]


def test_a_runtime_directory_named_for_a_dead_owner_is_swept_however_new(monkeypatch, tmp_path):
    """A dying desktop writes into its directory as it goes, so the one a
    killed owner leaves looks as new as one being built; measured on linux-host-a,
    the age check kept it. Named for its owner, it is judged by the owner."""
    from ghostdriver.backends.linux import hidden_desktop
    me = hidden_desktop._process_start(os.getpid())
    if me is None:
        pytest.skip("no /proc")
    dead = hidden_desktop._runtime_prefix("gd-y-", 4242, 1) + "abc"
    mine = hidden_desktop._runtime_prefix("gd-y-", os.getpid(), me) + "def"
    for leaf in (dead, mine):
        (tmp_path / leaf).mkdir()
    monkeypatch.setattr(hidden_desktop, "_processes_in", lambda path: [])
    monkeypatch.setattr(hidden_desktop, "_is_abandoned",
                        lambda owner, started, proc="/proc": owner == 4242)

    assert hidden_desktop._reap_abandoned_runtimes("gd-y-", root=str(tmp_path)) == [
        str(tmp_path / dead)]
    assert [p.name for p in tmp_path.iterdir()] == [mine]
