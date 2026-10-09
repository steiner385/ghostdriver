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

from tests.linux_probe_support import Budget, settle

#: When the fixture grabs the foreground, in milliseconds from its own start.
#:
#: #163: this was 12000, and everything the probe has to do before the watch
#: exists -- read the announce line, wait for the window, import the Linux
#: backend and its GI bindings, then `MinimizedWatch.start()`, which waits up
#: to `SETTLE_S` for the window manager to confirm the hide -- had to fit
#: inside it. Under a full suite it did not. The grab then happened before
#: there was anything watching, no escape was recorded, and the tests failed
#: on `any_capture is False` with `events` empty: a report that says nothing
#: arrived and not why.
#:
#: Raised, and the margin is recorded, so the report distinguishes "the watch
#: was late" from "the watch was running and missed it" -- which are a
#: harness problem and a backend defect respectively.
PRESENT_AFTER_MS = 30000

#: How the fixture gets out. A modal, not `present()`: measured on GNOME 50's
#: headless shell (#217), mutter in Wayland mode refuses an X client's
#: `present()` while it is minimized -- the window stayed hidden, so there was
#: no escape to report. A modal does get out: it brings the main window back
#: on screen beside itself, focus unmoved. That is the escape `sample` calls
#: the one that matters most.
ESCAPE_FLAG = "--modal-after"

#: The fixture's announce line is on a 120ms timer armed alongside the grab's.
ANNOUNCE_DELAY_S = 0.12


def main():
    app = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp_gtk",
         ESCAPE_FLAG, str(PRESENT_AFTER_MS), "--quit-after", "120000"],
        stdout=subprocess.PIPE, text=True,
        env=dict(os.environ, GDK_BACKEND="x11"),
    )
    announced = json.loads(app.stdout.readline())

    # The clock the watch is racing. The backend import is inside it on
    # purpose: it is the expensive part, and leaving it out would produce a
    # margin that looks healthy while the watch still starts late.
    budget = Budget("watch_ready", PRESENT_AFTER_MS / 1000 - ANNOUNCE_DELAY_S)

    from ghostdriver.backends import current
    from ghostdriver.backends.linux import display

    backend = current()
    xid = announced["main"]
    report = {"pid": announced["pid"], "xid": xid}

    # Was `time.sleep(5)`, a guess at how long the window takes to map on the
    # nested display. `start()` needs a window to put away, so that is what
    # to wait for.
    # Nothing here can happen once the fixture has exited, so every wait
    # below stops when it does rather than serving out its limit.
    def gone():
        return app.poll() is not None

    timing = [settle("window_mapped", lambda: display.exists(xid), timeout=30, giveup=gone)]

    # Built the way `attach` builds it (#218): no window handed in, so
    # `start` has to find the main window and the X window behind it.
    watch = backend.MinimizedWatch(announced["pid"], family=lambda: [announced["pid"]])
    watch.start()
    report["found_main_xid"] = watch.main_xid
    report["hidden_after_start"] = display.is_hidden(xid)
    timing.append(budget.record())

    # Long enough for the fixture's timed grab to land and be answered. The
    # limit covers the whole of the remaining wait to the grab plus the
    # watchdog's own poll interval, rather than assuming the grab is due.
    timing.append(settle("escape_seen", lambda: bool(watch.events()), timeout=60, giveup=gone))
    # The housekeeping half, which was `time.sleep(3)`. The watchdog puts the
    # target back after it photographs the escape, and that is a condition,
    # so `hidden_at_end` is read once the re-hide has landed instead of three
    # seconds after the escape whether it has or not.
    timing.append(settle("put_back", lambda: display.is_hidden(xid), timeout=20, giveup=gone))
    watch.stop()

    events = watch.events()
    report["timing"] = timing
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
