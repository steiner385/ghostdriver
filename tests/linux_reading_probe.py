"""Slice 2 exercised through the backend contract, inside the nested bus.

Calls `current()` rather than the module directly, so what is tested is what
a caller actually reaches. Never imported; run as a module.
"""

import json
import os
import subprocess
import sys
import time


def main():
    app = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp_gtk", "--quit-after", "60000"],
        stdout=subprocess.PIPE, text=True,
        env=dict(os.environ, GDK_BACKEND="x11"),
    )
    announced = json.loads(app.stdout.readline())
    time.sleep(3)

    from ghostdriver.backends import current

    backend = current()
    trees = backend.enumerate_process(announced["pid"])
    report = {"trees": len(trees), "controls": {}}

    for node in (n for tree in trees for n in tree.walk()):
        if not node.text:
            continue
        report["controls"][node.text] = {
            "role": node.class_name,
            "read": backend.read_window_text(node.handle),
            "protected": backend.is_protected(node.handle),
            # The third state, by name rather than borrowing None (D#43).
            "disclosure": backend.disclosure(node.handle),
            # And the opt-in. Asked for every control on purpose: the
            # interesting assertion is that it changes the answer for a
            # *withheld* field and changes nothing for a protected one.
            "read_disclosed": backend.read_window_text(node.handle, disclose=True),
        }

    try:
        png, width, height = backend.capture_window(trees[0].handle)
        report["capture"] = {"bytes": len(png), "width": width, "height": height,
                             "is_png": png[:4] == b"\x89PNG"}
    except Exception as exc:
        report["capture"] = {"error": f"{type(exc).__name__}: {exc}"}

    print(json.dumps(report), flush=True)
    app.terminate()
    app.wait(timeout=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
