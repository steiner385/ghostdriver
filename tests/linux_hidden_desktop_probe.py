"""Runs *inside its own process*, as JSON, one line.

`HiddenDesktop`'s claim (D#40f) never releases: once this process's one
accessibility bus is spent on a nested display, no ordinary session in the
*same* process can ever reach the operator's again. The pytest process runs
`test_mcp_server.py` and friends, which need exactly that ordinary reach --
so this has to spend its one claim somewhere that is not the test runner,
the same reason `tests/linux_atspi_probe.py` is a separate process rather
than a fixture the pytest process joins.

Never imported -- run as `python -m tests.linux_hidden_desktop_probe`.
"""

import json
import os
import sys
import time


def main() -> int:
    from ghostdriver.backends import current
    from ghostdriver.backends.linux import desktop_claim, display, hidden_desktop

    report: dict = {}

    instance = hidden_desktop.HiddenDesktop(name="ghostdriver-test")
    instance.prepare()
    report["claimed_by"] = desktop_claim.claimed_by()

    other = hidden_desktop.HiddenDesktop(name="ghostdriver-test-2")
    try:
        other.prepare()
        report["second_hidden_desktop_refused"] = False
    except desktop_claim.AlreadyClaimed:
        report["second_hidden_desktop_refused"] = True

    try:
        display.client_windows()
        report["operator_call_refused"] = False
    except desktop_claim.AlreadyClaimed:
        report["operator_call_refused"] = True

    pid = instance.launch(
        [sys.executable, "-m", "tests.fixtureapp_gtk", "--quit-after", "60000"]
    )
    # The fixture takes a moment to register on the AT-SPI bus after its
    # process starts; polled rather than a flat sleep.
    deadline = time.monotonic() + 10
    trees: list = []
    while time.monotonic() < deadline and not trees:
        trees = instance.run(lambda: current().enumerate_process(pid))
    names = [node.text for tree in trees for node in tree.walk()]
    report["found_fixture"] = "Ghostdriver GTK fixture" in names

    with open(f"/proc/{pid}/environ", "rb") as f:
        target_env = dict(item.split(b"=", 1) for item in f.read().split(b"\0") if b"=" in item)
    report["nested_display"] = instance._env["DISPLAY"]
    report["target_display"] = target_env.get(b"DISPLAY", b"").decode()
    wl = target_env.get(b"WAYLAND_DISPLAY")
    report["target_wayland_display"] = wl.decode() if wl else None

    started = [p.pid for p in instance._procs] + [instance._bus_pid, pid]
    runtime = instance._runtime
    instance.teardown()

    def alive(p):
        try:
            return not open(f"/proc/{p}/stat").read().split(") ")[1].startswith("Z")
        except OSError:
            return False

    def naming_runtime():
        # The shell's own children (Xwayland's -auth is under it) are not
        # in `started`; anything still naming the runtime directory is ours.
        found = []
        for entry in os.listdir("/proc"):
            if entry.isdigit():
                try:
                    with open(f"/proc/{entry}/cmdline", "rb") as f:
                        if runtime and runtime.encode() in f.read() and alive(entry):
                            found.append(int(entry))
                except OSError:
                    pass
        return found

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and (
            naming_runtime() or any(p and alive(p) for p in started)):
        time.sleep(0.2)
    report["left_running"] = sorted({p for p in started if p and alive(p)} | set(naming_runtime()))
    report["runtime_removed"] = runtime is not None and not os.path.exists(runtime)
    print(json.dumps(report), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
