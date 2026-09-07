"""Reads a genuinely hung GTK application, under the deadline, and reports.

Runs inside the nested session bus as its own process, for the same reason
`linux_atspi_probe` does: the pytest process must not join that bus. Never
imported -- run as `python -m tests.linux_timeout_probe`.
"""

import json
import os
import subprocess
import sys
import time

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi  # noqa: E402

from ghostdriver.backends.linux.deadline import call_with_deadline  # noqa: E402

HANG_S = 15.0
DEADLINE_S = 0.5


def _find(node, name):
    if node.get_name() == name:
        return node
    for i in range(node.get_child_count()):
        child = node.get_child_at_index(i)
        if child is not None:
            found = _find(child, name)
            if found is not None:
                return found
    return None


def main():
    app = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp_gtk",
         "--hang-after", "4000", "--hang-for", str(HANG_S), "--quit-after", "45000"],
        stdout=subprocess.PIPE, text=True,
        env=dict(os.environ, GDK_BACKEND="x11"),
    )
    announced = json.loads(app.stdout.readline())
    time.sleep(2.0)

    Atspi.init()
    desktop = Atspi.get_desktop(0)
    mine = next(
        desktop.get_child_at_index(i)
        for i in range(desktop.get_child_count())
        if desktop.get_child_at_index(i).get_process_id() == announced["pid"]
    )
    entry = _find(mine, "plain entry")

    def read():
        count = Atspi.Text.get_character_count(entry)
        return Atspi.Text.get_text(entry, 0, count)

    healthy = call_with_deadline(read, timeout_s=DEADLINE_S)

    while True:                                  # wait for the hang to begin
        line = app.stdout.readline()
        if not line or '"hanging"' in line:
            break

    started = time.monotonic()
    answer = call_with_deadline(read, timeout_s=DEADLINE_S)
    elapsed = time.monotonic() - started

    print(json.dumps({
        "healthy_answer": healthy,
        "answered": answer is not None,
        "answer": answer,
        "elapsed_s": elapsed,
        "deadline_s": DEADLINE_S,
        "hang_s": HANG_S,
    }), flush=True)
    app.terminate()
    app.wait(timeout=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
