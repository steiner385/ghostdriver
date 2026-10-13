"""The environment a nested-display probe runs in (#217).

GNOME 50 removed `gnome-shell --x11`, so the probes that stood up an Xvfb
and ran gnome-shell on it now run a headless `gnome-shell --wayland` and
target its Xwayland instead: `linux_nested_shell.sh` starts it, this builds
what it runs inside. Never imported by the backend.

Each session runs in a transient systemd slice when a user manager answers
and the shell is new enough to run in one (#231, `SCOPED_SHELL_MAJOR`): the sweep below cleans up after a harness that lives to run it, and
a pytest killed outright -- an agent's timeout -- left whole desktops
running, one of which fed RustDesk a dead `DISPLAY`. The next `nested_env`
stops whatever slice such a run left, the same as `HiddenDesktop.prepare`.

The runtime directory is private on purpose. Without one, the accessibility
bus a private session bus activates fell back to a fixed path under
`~/.cache` that another program on linux-host-a also used, and the "nested" bus
listed that program.
"""

import contextlib
import itertools
import os
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

SNIPPET = Path(__file__).parent / "linux_nested_shell.sh"

#: What every nested-display probe needs, beyond its own tools.
NEEDED = ("dbus-run-session", "gnome-shell", "Xwayland", "xprop")

_OPERATORS = ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "XAUTHORITY",
              "XDG_SESSION_TYPE", "AT_SPI_BUS_ADDRESS", "DBUS_SESSION_BUS_ADDRESS")


#: The slice each live `nested_env` runs its session in, by runtime directory.
_SLICES: dict[str, str] = {}
_COUNT = itertools.count()


def session(env: dict[str, str], *argv: str) -> list[str]:
    """`dbus-run-session -- argv`, for `Popen(..., env=env)` with the `env`
    `nested_env` yielded -- inside that environment's slice when it has one.

    `systemd-run` finds the user manager through the operator's runtime
    directory and bus, which `env` deliberately replaces, so the command
    hands it the operator's pair and the session its private one. Only
    those paths go on the command line, which any user can read.
    """
    command = ["dbus-run-session", "--", *argv]
    unit = _SLICES.get(env.get("XDG_RUNTIME_DIR", ""))
    if unit is None:
        return command
    operator = [f"{k}={os.environ[k]}" for k in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
                if k in os.environ]
    return ["env", *operator,
            "systemd-run", "--user", "--scope", "--quiet", "--collect",
            f"--slice={unit}", "--property=TimeoutStopSec=5", "--",
            "env", "-u", "DBUS_SESSION_BUS_ADDRESS", f"XDG_RUNTIME_DIR={env['XDG_RUNTIME_DIR']}",
            *command]


def inner(command: str) -> str:
    """A `bash -c` body: start the nested shell, then exec `command` on it."""
    return f'. "{SNIPPET}" && gd_start_nested_shell && exec {command}'


@contextlib.contextmanager
def nested_env(**extra: str) -> Iterator[dict[str, str]]:
    """The environment for `session(env, "bash", "-c", inner(...))`, with a
    private runtime directory removed afterwards."""
    from ghostdriver.backends.linux import hidden_desktop as hd
    started = hd._process_start(os.getpid())
    unit = None
    if started is not None and hd._user_systemd():
        hd._reap_abandoned_slices()
        if hd._shell_takes_a_scope():
            unit = hd._slice_name(os.getpid(), started, f"nested{next(_COUNT)}")
    # Both kinds: a hidden-desktop probe that crashed before its teardown
    # has its slice stopped here, and its directory is left for this sweep.
    for prefix in ("gd-nested-", "ghostdriver-desktop-"):
        hd._reap_abandoned_runtimes(prefix)
    runtime = tempfile.mkdtemp(prefix=hd._runtime_prefix("gd-nested-", os.getpid(), started))
    if unit is not None:
        _SLICES[runtime] = unit
    env = {k: v for k, v in os.environ.items() if k not in _OPERATORS}
    env.update(XDG_RUNTIME_DIR=runtime, GSETTINGS_BACKEND="memory",
               GIO_USE_VFS="local", GVFS_DISABLE_FUSE="1",
               GDK_BACKEND="x11", PYTHONPATH="src")
    env.update(extra)
    try:
        yield env
    finally:
        unit = _SLICES.pop(runtime, None)
        if unit is not None:
            # Everything the session started, whatever group it moved to.
            subprocess.run(["systemctl", "--user", "stop", unit],
                           capture_output=True, timeout=15)
        # Anything still carrying this runtime directory is the nested
        # desktop's: the headless shell does not always die on SIGTERM, and
        # outlived this harness three times in one run (#217).
        from ghostdriver.backends.linux.hidden_desktop import _mounts_under, _processes_in
        for pid in _processes_in(runtime):
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)
        with contextlib.suppress(OSError), open("/proc/mounts") as f:
            for mount in _mounts_under(runtime, f.read()):
                subprocess.run(["fusermount3", "-u", "-z", mount], capture_output=True, timeout=5)
        # Twice: a service activated on the private bus can recreate its
        # socket directory (measured: `pulse`) while it is still dying.
        shutil.rmtree(runtime, ignore_errors=True)
        time.sleep(1)
        shutil.rmtree(runtime, ignore_errors=True)
