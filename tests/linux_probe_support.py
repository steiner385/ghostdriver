"""Settling and budget accounting for the nested-display Linux probes (#163).

Every probe under `tests/linux_*_probe.py` drives a real X display, a real
window manager and a real GTK application, and each of them bounded its steps
with a fixed `sleep`. That is a guess about how long the machine will take,
and #163 measured what the guess costs: across three full-suite runs on one
box the failing set was different every time, run duration for identical work
varied 387s-681s, and the same modules passed when run alone.

Two distinct guesses were in play, and they fail differently:

* **A dwell after an action.** `xdotool windowactivate` then `sleep 2`, then
  read `_NET_ACTIVE_WINDOW`. Under load the window manager has not finished,
  so the probe photographs the *previous* state and the assertion reports a
  window manager that did not activate. `settle()` replaces this: poll the
  condition, stop the moment it holds, and record how long it took.

* **A budget before a timer.** The GTK fixture arms its disruptions with
  `GLib.timeout_add(options.modal_after, ...)`, an absolute timer from app
  start. A probe that wants to sample the calm state *before* the disruption
  is racing that timer with its own setup work. `Budget` replaces the guess
  that the work fits: it names the deadline, and reports the margin.

Neither is a retry. D45 is explicit that an intermittent failure gets
instrumented rather than retried, because a retry takes the evidence with it
-- so nothing here re-runs an assertion. `settle()` waits on the *precondition*
a measurement needs and then measures once; when the precondition never
arrives it says so, with the elapsed time and the last thing it saw, and the
caller decides whether that is a skip or a failure.

The separation matters more than either helper. A probe that could not reach
the state a test is about has measured nothing, and four tests failing on
"a modal before one was raised" describe the harness, not the product. A
probe that reached the state and then saw the promise broken has found a
real defect. These records are what let the fixtures tell those apart.

Pure stdlib, imported by probes running in a subprocess under `-m tests.X`.
Nothing here binds a platform at import time.
"""

import json
import queue
import threading
import time

#: How often to re-ask a settle predicate. Short enough that a fast condition
#: is not rounded up into a visible dwell, long enough not to spin a loaded
#: box -- which is the condition these exist for in the first place.
INTERVAL = 0.25

#: Prefix for a timing record streamed out as it is taken.
TIMING = "TIMING "


def emit(record):
    """Print a timing record the moment it is taken, and return it.

    Streamed rather than only collected, because a report assembled at the
    end is a report you do not get. Measured while building this: a probe
    whose fixture application exited early sat for 200s with every settle
    burning its full limit, produced no final JSON at all, and the fixture
    could say nothing except "the probe produced no report" -- the same
    uninformative failure #163 is about, arrived at from the other side.

    A record on the wire survives that. Whatever the probe does next, the
    steps it already completed are already out.
    """
    print(TIMING + json.dumps(record), flush=True)
    return record


def collect(stdout, marker, seconds):
    """Read a probe's stdout until its report arrives, keeping the trace.

    Returns `(report_line_or_None, [timing records])`.

    The deadline is real. The loop this replaces checked the clock *inside*
    `for line in stdout:`, so it only ever expired when a line arrived and a
    silent probe blocked on the pipe forever -- it bounded a slow probe, not
    a stalled one, which is the wrong half. Reading on a thread and taking
    lines off a queue makes the timeout mean what it says.
    """
    lines: queue.Queue = queue.Queue()

    def pump():
        for line in stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()

    report, trace, deadline = None, [], time.monotonic() + seconds
    while report is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            line = lines.get(timeout=min(remaining, 1.0))
        except queue.Empty:
            continue
        if line is None:
            break
        if line.startswith(TIMING):
            trace.append(json.loads(line[len(TIMING):]))
        elif line.startswith("{") and marker in line:
            report = line
    return report, trace


def settle(what, predicate, timeout, interval=INTERVAL, giveup=None):
    """Poll `predicate` until it is true, and report what happened.

    Returns a record rather than raising, and rather than returning a bare
    bool: the record is what ends up in the probe's JSON and therefore in the
    assertion message of whatever fails next. `ok` is the answer, `seconds` is
    the evidence -- a step that settled in 0.3s locally and 7.2s in CI is the
    difference between "this timeout is generous" and "this timeout is next
    year's flake", and neither is visible without the number.

    `predicate` is called immediately, so a condition that already holds costs
    nothing. An exception from `predicate` is caught and recorded, not raised:
    reading window-manager state on a display that is still coming up fails in
    ways that are ordinary here, and the last one is worth more in the report
    than a traceback out of a subprocess whose stderr is `DEVNULL`.

    `giveup` says the condition has become *impossible* rather than merely
    late -- the fixture application has exited, so the escape being waited
    for is never coming. Without it a generous limit is a liability: measured
    while building this, a probe whose application had already quit spent
    every remaining limit in full and turned a 35s module into a 200s one.
    Waiting longer for something that cannot happen is not patience.
    """
    started = time.monotonic()
    deadline = started + timeout
    polls, last_error = 0, None
    while True:
        polls += 1
        try:
            if predicate():
                return emit({"what": what, "ok": True, "polls": polls,
                             "seconds": round(time.monotonic() - started, 2),
                             "timeout": timeout, "error": last_error})
        except Exception as exc:
            # Recorded rather than raised; see the docstring.
            last_error = f"<{type(exc).__name__}: {exc}>"
        if giveup is not None and giveup():
            return emit({"what": what, "ok": False, "polls": polls,
                         "seconds": round(time.monotonic() - started, 2),
                         "timeout": timeout, "error": last_error,
                         "gave_up": "the condition became impossible"})
        if time.monotonic() >= deadline:
            return emit({"what": what, "ok": False, "polls": polls,
                         "seconds": round(time.monotonic() - started, 2),
                         "timeout": timeout, "error": last_error})
        time.sleep(interval)


class Budget:
    """The time a probe has before a fixture timer fires, and what it used.

    The GTK fixture's `--modal-after` / `--present-after` are absolute
    timers from its own start, so a probe wanting to observe the state
    *before* the disruption is on a clock from the moment it reads the
    announce line. Nothing in the probes said so, which is why overrunning
    read as a window manager fault rather than a harness one.

    `spent` is what the work took, `margin` is what was left. A negative
    margin is the diagnosis: the disruption fired before the probe finished
    sampling the calm state, so the calm state in the report is not calm and
    every assertion about it is describing the overrun.
    """

    def __init__(self, what, seconds):
        self.what = what
        self.seconds = seconds
        self.started = time.monotonic()

    @property
    def spent(self):
        return round(time.monotonic() - self.started, 2)

    def record(self):
        """The dict that goes in the report. `ok` false means the probe lost
        the race, which the fixture reads as "measured nothing" rather than
        "measured a failure"."""
        spent = self.spent
        return emit({"what": self.what, "ok": spent < self.seconds, "budget": self.seconds,
                     "spent": spent, "margin": round(self.seconds - spent, 2)})


def describe(timing):
    """Render a probe's timing records for an assertion message.

    Every one of these lands in a pytest failure or skip, read by someone who
    has just been told a test failed and does not yet know whether the box was
    busy. Ordered as recorded, so it reads as the sequence the probe went
    through, and marked so the eye finds the step that did not settle.
    """
    if not timing:
        return "(the probe recorded no timings)"
    lines = []
    for record in timing:
        mark = "ok " if record.get("ok") else "OVERRAN"
        if "budget" in record:
            lines.append(f"  {mark} {record['what']}: spent {record['spent']}s of "
                         f"{record['budget']}s, margin {record['margin']}s")
        else:
            kind = "dwelled" if record.get("dwell") else "settled in"
            detail = f"  {mark} {record['what']}: {kind} {record['seconds']}s"
            if not record.get("dwell"):
                detail += f" of {record['timeout']}s allowed"
            if record.get("gave_up"):
                detail += f", gave up -- {record['gave_up']}"
            if record.get("error"):
                detail += f", last error {record['error']}"
            lines.append(detail)
    return "\n".join(lines)


#: The characters GTK masks a hidden entry with over AT-SPI: the invisible
#: character, which differs by backend -- U+2022 under X11 and U+25CF under
#: Wayland, measured on GTK 4.22.4 and 3.24.52 (#219).
MASK_CHARACTERS = frozenset("\u2022\u25cf*")


def leaked_or_masked(text: str, secret: str) -> str | None:
    """What a hidden field's Text interface handed out: "leaked" (the secret
    in cleartext -- GTK 4.14.5, D#34a), "masked" (one mask character per
    secret character -- GTK 4.22.4 and 3.24.52, #219), or None for anything
    else, which is a change nobody has measured yet."""
    if text == secret:
        return "leaked"
    if len(text) == len(secret) and len(set(text)) == 1 and text[0] in MASK_CHARACTERS:
        return "masked"
    return None
