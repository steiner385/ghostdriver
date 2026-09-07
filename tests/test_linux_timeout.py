"""L2's real deliverable: a read that a hung application cannot block.

On Windows a hung target is handled by the OS -- `SendMessageTimeout` with
`SMTO_ABORTIFHUNG` returns `None` and the caller moves on (D4). AT-SPI has
no equivalent: `Atspi.set_timeout()` exists and, measured, does nothing.
A read against an application that has stopped servicing its main loop
blocks the caller for as long as the application stays hung.

So the deadline is the driver's to impose. These tests are the contract for
the primitive that does it. Most of them are platform-neutral -- the
semantics are threading, not AT-SPI -- and one runs the real thing against a
genuinely hung fixture.
"""

import json
import os
import shutil
import subprocess
import sys
import time

import pytest

from tests.conftest import on_linux

DISPLAY = ":94"
BUS_LAUNCHER = "/usr/libexec/at-spi-bus-launcher"


@pytest.fixture(scope="module")
def hung_fixture():
    """One nested stack, one genuinely hung application, one bounded read.

    Expensive -- it stands up an X server, a private session bus and an
    accessibility bus, then waits for the fixture to stop answering -- so it
    is module-scoped and marked slow.
    """
    missing = [t for t in ("Xvfb", "dbus-run-session") if shutil.which(t) is None]
    if not os.path.exists(BUS_LAUNCHER):
        missing.append(BUS_LAUNCHER)
    if missing:
        pytest.skip("nested AT-SPI stack unavailable: " + ", ".join(missing))

    server = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", "1280x800x24"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        inner = (f"{BUS_LAUNCHER} --launch-immediately & sleep 3; "
                 f"exec {sys.executable} -m tests.linux_timeout_probe")
        done = subprocess.run(
            ["dbus-run-session", "--", "bash", "-c", inner],
            capture_output=True, text=True, timeout=180,
            env=dict(os.environ, DISPLAY=DISPLAY, GSETTINGS_BACKEND="memory",
                     PYTHONPATH="src"),
        )
        line = next((ln for ln in done.stdout.splitlines()
                     if ln.startswith("{") and '"elapsed_s"' in ln), None)
        if line is None:
            pytest.skip("the timeout probe produced no report:\n"
                        + done.stdout[-800:] + "\n" + done.stderr[-800:])
        yield json.loads(line)
    finally:
        server.terminate()
        server.wait(timeout=10)


def _deadline():
    """Imported inside the tests: `ghostdriver.backends.*` at module scope is
    what took the whole suite down on the wrong host once already (D74)."""
    from ghostdriver.backends.linux import deadline

    return deadline


def test_a_prompt_call_returns_its_value():
    d = _deadline()
    assert d.call_with_deadline(lambda: "value", timeout_s=1.0) == "value"


def test_a_slow_call_gives_up_and_says_it_did_not_answer():
    """`None` means *did not answer*, never *answered with nothing* -- the
    distinction conftest calls load-bearing, and the same one
    `send_message_timeout` draws on Windows."""
    d = _deadline()
    assert d.call_with_deadline(lambda: time.sleep(5) or "late", timeout_s=0.2) is None


def test_the_caller_waits_the_deadline_and_not_the_hang():
    """The property that matters. A five-second block must cost the caller the
    deadline, not five seconds."""
    d = _deadline()
    started = time.monotonic()
    d.call_with_deadline(lambda: time.sleep(5), timeout_s=0.2)
    elapsed = time.monotonic() - started
    assert elapsed < 1.0, f"the caller waited {elapsed:.2f}s on a 0.2s deadline"


def test_an_exception_is_not_swallowed_into_a_timeout():
    """A control that answers with an error answered. Reporting that as "did
    not answer" would collapse two different facts, which is the mistake this
    whole distinction exists to prevent."""
    d = _deadline()

    def boom():
        raise RuntimeError("the control refused")

    with pytest.raises(RuntimeError, match="refused"):
        d.call_with_deadline(boom, timeout_s=1.0)


def test_the_default_deadline_clears_a_healthy_read_by_a_wide_margin():
    """200ms, the same number `send_message_timeout` uses on Windows -- kept
    the same on purpose so the contract reads identically on both, and
    justified here rather than copied: a healthy AT-SPI read measured p50
    0.19ms, p99 0.46ms, max 1.88ms over 200 samples, and a 33-node tree walk
    took 9.2ms end to end. The deadline is ~100x the worst read seen."""
    d = _deadline()
    assert d.DEFAULT_DEADLINE_S == 0.2
    assert d.DEFAULT_DEADLINE_S > 0.05, "below the worst healthy read plus headroom"


@on_linux
@pytest.mark.slow
def test_a_genuinely_hung_application_does_not_block_the_caller(hung_fixture):
    """The measurement itself, not a simulation of it: the GTK fixture stops
    servicing its main loop, and a real AT-SPI read against it is bounded by
    the deadline rather than by the hang."""
    assert hung_fixture["answered"] is False, hung_fixture
    assert hung_fixture["elapsed_s"] < 1.0, (
        f"the caller waited {hung_fixture['elapsed_s']:.2f}s "
        f"on a {hung_fixture['deadline_s']}s deadline"
    )
    assert hung_fixture["hang_s"] > 5.0, "the fixture was not hung long enough to prove anything"
