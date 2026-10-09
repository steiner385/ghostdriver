"""The `hidden_desktop` isolation strategy: a nested display, not a thread.

`docs/LINUX.md`'s proposed mechanism, built: a nested desktop with its own
`DISPLAY`, its own D-Bus session bus (so it does not find the operator's
accessibility bus and enumerate the operator's applications -- D#8), its
own accessibility bus on that session bus, and its own window manager
(D75 -- `_NET_CLIENT_LIST` and `_NET_ACTIVE_WINDOW` come from one, so
nothing above the backend boundary can be answered without it). The
guarantee is the same structural one Windows has: a window on a display
that is not the input display has no foreground to steal.

**The nested display is a headless gnome-shell's own Xwayland (#217).** It
was an `Xvfb` with `gnome-shell --x11` on it, and GNOME 50 removed the X11
backend, so that stack cannot start there. A headless `gnome-shell
--wayland` is still mutter: the target runs as an X client of the shell's
Xwayland and gets the same window manager, so everything this backend reads
from X reads the same way -- measured on linux-host-a against the GTK fixture
(client list, active window, iconify, capture, XTest), with the operator's
foreground unmoved. Everything runs under a private `XDG_RUNTIME_DIR`:
without one the accessibility bus fell back to a fixed path under
`~/.cache` that another program also used, and the "nested" bus listed it.

**Where this stops mapping onto Windows.** `CreateDesktopW` gives one
process several desktops and binds a *thread* to whichever one it should
see; the bind is `SetThreadDesktop`, called once per worker thread, and
every call the worker makes afterward sees that desktop and nothing else.
There is no Linux counterpart to bind a thread to a display -- `DISPLAY`
and `AT_SPI_BUS_ADDRESS` are process environment, not thread state, so
`docs/LINUX.md` proposed "no thread binding needed -- the display is an
environment variable" for the ordinary case of one desktop at a time.

**Measured (issue #40 slice 5b): that is true for X11, and false for
AT-SPI, in a way that changes the shape of `run`.** An `Xlib.display.
Display()` is a plain object -- nothing stops a process holding two of
them, one per display, and `display.py` now caches by claimant rather than
once for the whole process. But `Atspi.init()` is a C-library singleton: a
second call against a different `AT_SPI_BUS_ADDRESS` does not reconnect, a
forked child inherits the first call's live connection regardless of its
own environment, and `Atspi.exit()` corrupts the library's state rather
than freeing it for a second `init()`. All three were tried against two
real nested buses before writing this; none of them let one process reach
two accessibility buses. `desktop_claim.py` carries the measurement and the
consequence: this process claims exactly one accessibility bus for its
whole life, hidden desktop or operator's, decided by whichever asks first.

So `run` does not marshal onto a worker thread the way Windows' does --
there is nothing to marshal onto, a claimed process already only has the
one bus reachable. What it does is mark the call as belonging to this
desktop's claim (`desktop_claim.desktop`), so the ordinary contract
functions this backend already has -- `tree.enumerate_process`, `reading.
read_window_text`, and the rest -- correctly recognise a hidden desktop's
own driving of its target as the claim it holds, and a *different* claimant
reaching the same shared connection is still refused rather than silently
misrouted.
"""

from __future__ import annotations

import contextlib
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable
from typing import TypeVar

from . import desktop_claim, display

T = TypeVar("T")

#: How long to wait for each piece of the stack to answer before giving up
#: and reporting why, rather than hanging `launch_isolated` on a service
#: that will never start (D#9's reasoning, applied to setup rather than a
#: single call). Measured on linux-host-a: the shell announces its Xwayland in
#: ~0.2s once it has a runtime directory.
STARTUP_TIMEOUT_S = 10.0
POLL_S = 0.1

#: The size of the nested desktop's one virtual monitor.
VIRTUAL_MONITOR = "1280x800"

_PUBLIC_DISPLAY = re.compile(r"Using public X11 display (:\d+)")


class Unsupported(RuntimeError):
    """Raised when a strategy cannot do what was asked of it."""


def _unavailable() -> list[str]:
    """What is missing, or an empty list when the stack can be built.

    `gnome-shell` must also be able to run headless -- every version this
    backend has met (46, 50) can, but a shell that cannot is named here
    rather than failing later with a log nobody reads.
    """
    missing = [t for t in ("dbus-daemon", "dbus-send", "gnome-shell")
               if shutil.which(t) is None]
    if "gnome-shell" not in missing:
        helped = subprocess.run(["gnome-shell", "--help"], capture_output=True,
                                text=True, timeout=STARTUP_TIMEOUT_S)
        if "--headless" not in helped.stdout + helped.stderr:
            missing.append("a gnome-shell that runs --headless")
    return missing


def _public_display(log: str) -> str | None:
    """The Xwayland display the shell chose, from its own log line.

    The shell picks a free number itself and says so on stderr
    ("Using public X11 display :2, ..."). Measured, not assumed: watching
    `/tmp/.X11-unix` for a new socket missed it, because the name was one a
    stale socket already held.
    """
    found = _PUBLIC_DISPLAY.search(log)
    return found.group(1) if found else None


def _target_env(*, display: str, xauthority: str, bus: str, atspi: str,
                runtime: str) -> dict[str, str]:
    """What the target runs with: an X client of the nested Xwayland.

    Never the operator's `WAYLAND_DISPLAY`: a toolkit that prefers Wayland
    (Qt, Chromium) would open on the operator's own desktop -- the one thing
    this strategy exists to prevent. And the backends forced to X, because
    everything this backend reads about a window it reads from X (#217).
    """
    env = {k: v for k, v in os.environ.items()
           if k not in ("WAYLAND_DISPLAY", "WAYLAND_SOCKET")}
    env.update(
        DISPLAY=display,
        XAUTHORITY=xauthority,
        DBUS_SESSION_BUS_ADDRESS=bus,
        AT_SPI_BUS_ADDRESS=atspi,
        XDG_RUNTIME_DIR=runtime,
        XDG_SESSION_TYPE="x11",
        GDK_BACKEND="x11",
        QT_QPA_PLATFORM="xcb",
        GSETTINGS_BACKEND="memory",
    )
    return env


def _processes_in(runtime: str, proc: str = "/proc") -> list[int]:
    """Every process whose `XDG_RUNTIME_DIR` is this desktop's.

    That is what belongs to a nested desktop -- the shell, its Xwayland, and
    the portals and services it activated, whatever process group they ended
    up in. Swept by teardown because the headless shell does not always die
    on SIGTERM, and outlived its harness three times in one run (#217).
    """
    marker = b"XDG_RUNTIME_DIR=" + runtime.encode()
    found = []
    for entry in sorted(os.listdir(proc), key=lambda e: (len(e), e)):
        if not entry.isdigit() or int(entry) == os.getpid():
            continue
        try:
            with open(os.path.join(proc, entry, "environ"), "rb") as f:
                if marker in f.read().split(b"\0"):
                    found.append(int(entry))
        except OSError:
            continue
    return found


def _mounts_under(directory: str, mounts: str) -> list[str]:
    """Mount points inside `directory`, from `/proc/mounts` text.

    The nested shell can activate the document portal, which FUSE-mounts
    itself under the runtime directory; left mounted, the directory cannot be
    removed (measured on linux-host-a, #217). Deepest first, for unmounting.
    """
    prefix = directory.rstrip("/") + "/"
    found = [line.split()[1] for line in mounts.splitlines()
             if len(line.split()) > 1 and line.split()[1].startswith(prefix)]
    return sorted(found, key=len, reverse=True)


def _await_group_gone(pgid: int, timeout: float = 5.0) -> None:
    """Wait for a process group to empty, then make sure it has.

    Removing the runtime directory while the group is still shutting down
    lets a dying service write into it again; measured once on linux-host-a, a
    gvfs mount point reappeared a few seconds after the directory went.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        except OSError:
            return
        time.sleep(POLL_S)
    with contextlib.suppress(OSError):
        os.killpg(pgid, signal.SIGKILL)


class HiddenDesktop:
    """A nested desktop, its own buses, and the process it runs the target
    on. Not reusable and not thread-safe by design, the same as the Windows
    strategy this mirrors: one instance owns one nested stack.
    """

    def __init__(self, name: str = "ghostdriver") -> None:
        self.name = name
        self.pid: int = 0
        self._env: dict[str, str] = {}
        self._procs: list[subprocess.Popen] = []
        self._target: subprocess.Popen | None = None
        self._bus_pid: int | None = None
        self._runtime: str | None = None

    # -- lifecycle --------------------------------------------------------

    def prepare(self) -> None:
        """Stand up the nested desktop: a private runtime directory and
        session bus, a headless gnome-shell, and its Xwayland.

        Claims the process for this desktop's name before anything else
        runs, so a process that already talks to the operator's own
        accessibility bus refuses here, loudly, instead of after a target
        has been launched onto a display nothing can then read from. A
        failure part-way tears down what was already started.
        """
        with desktop_claim.desktop(self.name):
            desktop_claim.claim()

        missing = _unavailable()
        if missing:
            raise Unsupported(
                "the nested-desktop stack needs " + ", ".join(missing)
                + ", which this machine does not have. hidden_desktop is "
                "the Linux isolation strategy (docs/LINUX.md); without it "
                "there is no launch-only guarantee to offer."
            )
        try:
            self._prepare()
        except BaseException:
            self.teardown()
            raise

    def _prepare(self) -> None:
        # Private, so the accessibility bus and the shell's sockets land
        # here. Without one, the bus fell back to a fixed path under
        # ~/.cache that another program on linux-host-a also used, and the
        # "nested" bus listed RustDesk (#217).
        self._runtime = tempfile.mkdtemp(prefix="ghostdriver-desktop-")
        bus_address = self._start_private_bus()
        display_name, xauthority = self._start_shell(bus_address)
        atspi_address = self._a11y_address(bus_address)
        self._env = _target_env(display=display_name, xauthority=xauthority,
                                bus=bus_address, atspi=atspi_address,
                                runtime=self._runtime)
        # What `display.py` and `tree.py` look up by claimant instead of
        # reading the ambient environment (D#40f) -- registered before the
        # window manager readiness poll below, which is the first caller.
        desktop_claim.register(
            self.name, DISPLAY=display_name, XAUTHORITY=xauthority,
            DBUS_SESSION_BUS_ADDRESS=bus_address, AT_SPI_BUS_ADDRESS=atspi_address,
        )
        self._await_window_manager()

    def _base_env(self, bus_address: str | None = None) -> dict[str, str]:
        assert self._runtime is not None
        env = {k: v for k, v in os.environ.items()
               if k not in ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET",
                            "XAUTHORITY", "XDG_SESSION_TYPE", "AT_SPI_BUS_ADDRESS")}
        # No gvfs: a nested desktop needs no virtual filesystems, and its
        # daemons outlived the bus long enough to recreate their mount point
        # in the runtime directory after teardown removed it (measured).
        env.update(XDG_RUNTIME_DIR=self._runtime, GSETTINGS_BACKEND="memory",
                   GIO_USE_VFS="local", GVFS_DISABLE_FUSE="1")
        if bus_address is not None:
            env["DBUS_SESSION_BUS_ADDRESS"] = bus_address
        return env

    def _start_private_bus(self) -> str:
        """A session bus of its own (D#8): the reason the nested desktop
        isolates rather than merely runs somewhere else. `dbus-daemon
        --fork --print-address` rather than `dbus-run-session`, because
        this process needs the address as data to hand to the pieces it
        starts next. Started inside the private runtime directory, so the
        services it activates -- the accessibility bus among them -- put
        their sockets there too."""
        out = subprocess.run(
            ["dbus-daemon", "--session", "--fork",
             "--print-address=1", "--print-pid=1"],
            capture_output=True, text=True, timeout=STARTUP_TIMEOUT_S,
            env=self._base_env(),
        )
        lines = out.stdout.splitlines()
        if out.returncode != 0 or len(lines) < 2:
            raise Unsupported(
                f"dbus-daemon would not start a private session bus: {out.stderr[:300]}"
            )
        self._bus_pid = int(lines[1].strip())
        return lines[0].strip()

    def _start_shell(self, bus_address: str) -> tuple[str, str]:
        """A headless gnome-shell, and the Xwayland it announces.

        Not `gnome-shell --x11` on an Xvfb (D75): GNOME 50 removed the X11
        backend (#217). The shell is still mutter, so the target -- an X
        client of the shell's own Xwayland -- gets the same window manager,
        and with it `_NET_CLIENT_LIST`, `_NET_ACTIVE_WINDOW` and iconify,
        measured on linux-host-a against the GTK fixture.
        """
        assert self._runtime is not None
        log_path = os.path.join(self._runtime, "gnome-shell.log")
        with open(log_path, "w") as log:
            proc = subprocess.Popen(
                ["gnome-shell", "--headless", "--wayland",
                 "--virtual-monitor", VIRTUAL_MONITOR,
                 "--wayland-display", f"ghostdriver-{os.getpid()}-{self.name}"],
                env=self._base_env(bus_address), stdout=subprocess.DEVNULL,
                stderr=log, start_new_session=True,
            )
        self._procs.append(proc)
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            with open(log_path) as log:
                found = _public_display(log.read())
            if found is not None:
                cookies = glob.glob(os.path.join(self._runtime, ".mutter-Xwaylandauth.*"))
                if cookies:
                    return found, cookies[0]
            if proc.poll() is not None:
                break
            time.sleep(POLL_S)
        with open(log_path) as log:
            tail = log.read()[-400:]
        raise Unsupported(
            "the headless gnome-shell did not announce an Xwayland display "
            f"within {STARTUP_TIMEOUT_S:.0f}s. Its log ends: {tail}"
        )

    def _a11y_address(self, bus_address: str) -> str:
        """The private accessibility bus's address, activated on the
        private session bus by asking for it."""
        env = self._base_env(bus_address)
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            got = subprocess.run(
                ["dbus-send", "--session", "--print-reply", "--dest=org.a11y.Bus",
                 "/org/a11y/bus", "org.a11y.Bus.GetAddress"],
                env=env, capture_output=True, text=True, timeout=2,
            )
            if got.returncode == 0:
                lines = got.stdout.strip().splitlines()
                if lines:
                    # `   string "unix:path=...,guid=..."` -- the quoted value.
                    return lines[-1].strip().split('"', 1)[1].rsplit('"', 1)[0]
            time.sleep(POLL_S)
        raise Unsupported(
            "the private accessibility bus did not answer GetAddress within "
            f"{STARTUP_TIMEOUT_S:.0f}s"
        )

    def _await_window_manager(self) -> None:
        """The shell manages its Xwayland's clients (D75's reason for a WM:
        `_NET_CLIENT_LIST` and `_NET_ACTIVE_WINDOW` come from it)."""
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        with desktop_claim.desktop(self.name):
            while time.monotonic() < deadline:
                if display.wm_present():
                    return
                time.sleep(POLL_S)
        raise Unsupported(
            f"the nested shell did not manage its Xwayland within "
            f"{STARTUP_TIMEOUT_S:.0f}s; without a window manager this "
            "display cannot answer top_level_windows or restore_process"
        )

    def run(self, fn: Callable[[], T]) -> T:
        """Run `fn` with every backend call inside it recognised as this
        desktop's own -- see the module docstring for what that does and
        does not do relative to Windows' thread-bound `run`."""
        with desktop_claim.desktop(self.name):
            return fn()

    def launch(self, command: list[str], *, announces_pid: bool = False) -> int:
        """Start `command` on the nested display; return the target's pid.

        `announces_pid` is the same opt-in as the Windows strategy's: a
        launcher that re-execs so the process this starts is a stub owning
        no windows while the real interpreter runs under a different pid.
        Such a target prints one JSON line naming its real pid -- the GTK
        fixture does this already, for the same reason the Windows one
        does -- read back here over the child's stdout. Off by default,
        because the wrong default would hang launch on a target that never
        prints one.
        """
        if not self._env:
            raise RuntimeError("prepare() has not been called")
        self._target = subprocess.Popen(
            command, env=self._env,
            stdout=subprocess.PIPE if announces_pid else subprocess.DEVNULL,
            text=True,
        )
        if not announces_pid:
            self.pid = self._target.pid
            return self.pid
        assert self._target.stdout is not None
        line = self._target.stdout.readline()
        try:
            self.pid = json.loads(line)["pid"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise OSError(
                f"target did not announce a pid on its first stdout line: {line[:200]!r}"
            ) from exc
        return self.pid

    def attach(self, pid: int) -> None:
        raise Unsupported(
            "hidden_desktop cannot adopt a running process: a window's "
            "display is fixed at creation, so a target already on another "
            "display cannot be moved to this one. Launch it instead"
        )

    def teardown(self) -> None:
        """Stop everything this desktop started, and remove its runtime
        directory. Safe to call on a half-built desktop: `prepare` calls it
        when a step fails, which it did not before -- every failed run on
        linux-host-a left an X server and a private bus behind (#217)."""
        if self._target is not None and self._target.poll() is None:
            self._target.terminate()
        for proc in reversed(self._procs):
            if proc.poll() is None:
                # The shell runs in its own session and takes Xwayland down
                # with it; the group catches anything it started besides.
                with contextlib.suppress(OSError):
                    os.killpg(proc.pid, signal.SIGTERM)
        for proc in reversed(self._procs):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(OSError):
                    os.killpg(proc.pid, signal.SIGKILL)
        if self._bus_pid:
            # `--fork` puts the daemon in a session of its own, so its group
            # holds the services it activated: the accessibility bus, and
            # the shell's helpers (ibus, the portal).
            with contextlib.suppress(OSError):
                os.killpg(self._bus_pid, signal.SIGTERM)
            with contextlib.suppress(OSError):
                os.kill(self._bus_pid, signal.SIGTERM)
            _await_group_gone(self._bus_pid)
            self._bus_pid = None
        if self._runtime is not None:
            # Whatever still carries this desktop's runtime directory is
            # ours, in any process group: put down last, and hard.
            for pid in _processes_in(self._runtime):
                with contextlib.suppress(OSError):
                    os.kill(pid, signal.SIGKILL)
            with contextlib.suppress(OSError), open("/proc/mounts") as f:
                for mount in _mounts_under(self._runtime, f.read()):
                    subprocess.run(["fusermount3", "-u", "-z", mount],
                                   capture_output=True, timeout=5)
            shutil.rmtree(self._runtime, ignore_errors=True)
            self._runtime = None
