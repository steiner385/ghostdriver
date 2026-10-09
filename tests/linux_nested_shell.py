"""The environment a nested-display probe runs in (#217).

GNOME 50 removed `gnome-shell --x11`, so the probes that stood up an Xvfb
and ran gnome-shell on it now run a headless `gnome-shell --wayland` and
target its Xwayland instead: `linux_nested_shell.sh` starts it, this builds
what it runs inside. Never imported by the backend.

The runtime directory is private on purpose. Without one, the accessibility
bus a private session bus activates fell back to a fixed path under
`~/.cache` that another program on linux-host-a also used, and the "nested" bus
listed that program.
"""

import contextlib
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


def inner(command: str) -> str:
    """A `bash -c` body: start the nested shell, then exec `command` on it."""
    return f'. "{SNIPPET}" && gd_start_nested_shell && exec {command}'


@contextlib.contextmanager
def nested_env(**extra: str) -> Iterator[dict[str, str]]:
    """The environment for `dbus-run-session -- bash -c inner(...)`, with a
    private runtime directory removed afterwards."""
    runtime = tempfile.mkdtemp(prefix="gd-nested-")
    env = {k: v for k, v in os.environ.items() if k not in _OPERATORS}
    env.update(XDG_RUNTIME_DIR=runtime, GSETTINGS_BACKEND="memory",
               GIO_USE_VFS="local", GVFS_DISABLE_FUSE="1",
               GDK_BACKEND="x11", PYTHONPATH="src")
    env.update(extra)
    try:
        yield env
    finally:
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
