"""Slice 5a against a target that fights back: the watch, end to end.

The fixture is told to grab the foreground on a timer, which is what a
foreground grab *is*. The watch should put it away, notice it got out, and
put it away again -- and the event should carry the picture of what appeared,
because that picture is the product.
"""

import json
import os
import subprocess
import sys
import time


def main():
    app = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp_gtk",
         "--present-after", "12000", "--quit-after", "90000"],
        stdout=subprocess.PIPE, text=True,
        env=dict(os.environ, GDK_BACKEND="x11"),
    )
    announced = json.loads(app.stdout.readline())
    time.sleep(5)

    from ghostdriver.backends import current
    from ghostdriver.backends.linux import display

    backend = current()
    xid = announced["main"]
    report = {"pid": announced["pid"], "xid": xid}

    watch = backend.MinimizedWatch(announced["pid"], xid)
    watch.start()
    report["hidden_after_start"] = display.is_hidden(xid)

    # Long enough for the fixture's timed grab to land and be answered.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not watch.events():
        time.sleep(0.5)
    time.sleep(3)
    watch.stop()

    events = watch.events()
    report["events"] = events
    report["kinds"] = [e.get("kind") for e in events]
    # `to_dict` reports whether a picture was taken, not the bytes -- an
    # event log is read by a person and a PNG in it is noise.
    report["any_capture"] = any(e.get("captured") for e in events)
    report["hidden_at_end"] = display.is_hidden(xid)

    print(json.dumps(report), flush=True)
    app.terminate()
    app.wait(timeout=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
