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

    instance.teardown()
    print(json.dumps(report), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
