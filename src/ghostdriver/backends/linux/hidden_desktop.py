"""The `hidden_desktop` isolation strategy: a nested display, not a thread.

`docs/LINUX.md`'s proposed mechanism, built: a nested X server (`Xvfb`) with
its own `DISPLAY`, its own D-Bus session bus (so it does not find the
operator's accessibility bus and enumerate the operator's applications --
D#8), its own accessibility bus on that session bus (`at-spi-bus-launcher`),
and its own window manager (`gnome-shell --x11`, D75 -- a bare `Xvfb` sets
neither `_NET_CLIENT_LIST` nor `_NET_ACTIVE_WINDOW`, so nothing above the
backend boundary can be answered without one). The guarantee is the same
structural one Windows has: a window on a display that is not the input
display has no foreground to steal.

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

import json
import os
import random
import shutil
import subprocess
import time
from collections.abc import Callable
from typing import TypeVar

from . import desktop_claim, display

T = TypeVar("T")

#: The one binary this needs beyond Xvfb and dbus-daemon, both of which
#: `docs/LINUX.md`'s own nested-bus measurement (`tests/test_linux_atspi.
#: py`) already depends on. Not on `PATH` on every distribution, which is
#: why `_unavailable` checks the literal path rather than `shutil.which`.
BUS_LAUNCHER = "/usr/libexec/at-spi-bus-launcher"

#: How long to wait for each piece of the stack to answer before giving up
#: and reporting why, rather than hanging `launch_isolated` on a service
#: that will never start (D#9's reasoning, applied to setup rather than a
#: single call).
STARTUP_TIMEOUT_S = 10.0
POLL_S = 0.1


class Unsupported(RuntimeError):
    """Raised when a strategy cannot do what was asked of it."""


def _unavailable() -> list[str]:
    """What is missing, or an empty list when the stack can be built."""
    missing = [t for t in ("Xvfb", "dbus-daemon", "dbus-send", "gnome-shell")
               if shutil.which(t) is None]
    if not os.path.exists(BUS_LAUNCHER):
        missing.append(BUS_LAUNCHER)
    return missing


def _free_display_number() -> int:
    """A display number nothing is listening on yet.

    `/tmp/.X{n}-lock` is what a running `Xvfb` leaves behind; picking a
    random band and stepping past whatever is taken is enough to make
    concurrent launches (two tests, or two sessions) not collide, without
    needing a registry of what this process has already claimed.
    """
    base = random.randint(150, 900)
    for offset in range(200):
        candidate = base + offset
        if not os.path.exists(f"/tmp/.X{candidate}-lock"):
            return candidate
    raise Unsupported("no free nested display number found in the 150-900 band")


class HiddenDesktop:
    """A nested display, its own accessibility bus, and the process it runs
    the target on. Not reusable and not thread-safe by design, the same as
    the Windows strategy this mirrors: one instance owns one nested stack.
    """

    def __init__(self, name: str = "ghostdriver") -> None:
        self.name = name
        self.pid: int = 0
        self._env: dict[str, str] = {}
        self._procs: list[subprocess.Popen] = []
        self._target: subprocess.Popen | None = None
        self._bus_pid: int | None = None

    # -- lifecycle --------------------------------------------------------

    def prepare(self) -> None:
        """Stand up the nested display, its bus, and its window manager.

        Claims the process for this desktop's name before anything else
        runs, so a process that already talks to the operator's own
        accessibility bus refuses here, loudly, instead of after a target
        has been launched onto a display nothing can then read from.
        """
        with desktop_claim.desktop(self.name):
            desktop_claim.claim()

        missing = _unavailable()
        if missing:
            raise Unsupported(
                "the nested-display stack needs " + ", ".join(missing)
                + ", which this machine does not have. hidden_desktop is "
                "the Linux isolation strategy (docs/LINUX.md); without it "
                "there is no launch-only guarantee to offer."
            )

        display_number = self._start_xvfb()
        bus_address = self._start_private_bus()
        atspi_address = self._start_bus_launcher(display_number, bus_address)
        display_name = f":{display_number}"
        self._env = dict(
            os.environ,
            DISPLAY=display_name,
            DBUS_SESSION_BUS_ADDRESS=bus_address,
            AT_SPI_BUS_ADDRESS=atspi_address,
            GDK_BACKEND="x11",
            GSETTINGS_BACKEND="memory",
        )
        # What `display.py` and `tree.py` look up by claimant instead of
        # reading the ambient environment (D#40f) -- registered before the
        # window manager readiness poll below, which is the first caller.
        desktop_claim.register(
            self.name, DISPLAY=display_name,
            DBUS_SESSION_BUS_ADDRESS=bus_address, AT_SPI_BUS_ADDRESS=atspi_address,
        )
        self._start_window_manager()

    def _spawn(self, command: list[str], *, env: dict[str, str] | None = None) -> subprocess.Popen:
        proc = subprocess.Popen(
            command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._procs.append(proc)
        return proc

    def _start_xvfb(self) -> int:
        for _ in range(5):
            number = _free_display_number()
            proc = self._spawn(["Xvfb", f":{number}", "-screen", "0", "1280x800x24"])
            time.sleep(0.3)
            if proc.poll() is None:
                return number
            self._procs.remove(proc)
        raise Unsupported("Xvfb would not start on any of five tried display numbers")

    def _start_private_bus(self) -> str:
        """A session bus of its own (D#8): the reason the nested display
        isolates rather than merely runs somewhere else. `dbus-daemon
        --fork --print-address` rather than `dbus-run-session`, because
        this process needs the address as data to hand to the pieces it
        starts next, not as an environment already applied to an `exec`."""
        out = subprocess.run(
            ["dbus-daemon", "--session", "--fork",
             "--print-address=1", "--print-pid=1"],
            capture_output=True, text=True, timeout=STARTUP_TIMEOUT_S,
        )
        lines = out.stdout.splitlines()
        if out.returncode != 0 or len(lines) < 2:
            raise Unsupported(
                f"dbus-daemon would not start a private session bus: {out.stderr[:300]}"
            )
        self._bus_pid = int(lines[1].strip())
        return lines[0].strip()

    def _start_bus_launcher(self, display_number: int, bus_address: str) -> str:
        env = dict(os.environ, DISPLAY=f":{display_number}",
                   DBUS_SESSION_BUS_ADDRESS=bus_address, GSETTINGS_BACKEND="memory")
        self._spawn([BUS_LAUNCHER, "--launch-immediately"], env=env)
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
            "at-spi-bus-launcher did not answer GetAddress within "
            f"{STARTUP_TIMEOUT_S:.0f}s of starting"
        )

    def _start_window_manager(self) -> None:
        """A WM, not just a server (D75): `_NET_CLIENT_LIST` and
        `_NET_ACTIVE_WINDOW` -- what everything above the tree read from
        this display -- come from the window manager, and a bare `Xvfb`
        sets neither."""
        self._spawn(["gnome-shell", "--x11"], env=self._env)
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        with desktop_claim.desktop(self.name):
            while time.monotonic() < deadline:
                if display.wm_present():
                    return
                time.sleep(POLL_S)
        raise Unsupported(
            f"gnome-shell did not attach to the nested display within "
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
        if self._target is not None and self._target.poll() is None:
            self._target.terminate()
        for proc in reversed(self._procs):
            if proc.poll() is None:
                proc.terminate()
        for proc in reversed(self._procs):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if self._bus_pid:
            try:
                os.kill(self._bus_pid, 15)
            except OSError:
                pass
