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
