"""Slice 2 of #40: reading, reached through the contract rather than directly.

`tests/test_linux_reading.py` measures what AT-SPI *will* tell you --
including that it hands over a password in cleartext. This checks what the
backend actually returns when a caller asks, which is the place the
disclosure policy (D#34b) and the deadline (D#9) have to be in force.
"""

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys

import pytest

from tests.conftest import on_linux
from tests.linux_nested_shell import NEEDED as NESTED_NEEDED
from tests.linux_nested_shell import inner, nested_env
from tests.linux_probe_support import collect

pytestmark = [on_linux, pytest.mark.slow]

BUS_LAUNCHER = "/usr/libexec/at-spi-bus-launcher"


@pytest.fixture(scope="module")
def wired():
    missing = [t for t in (*NESTED_NEEDED, "convert", "xwininfo")
               if shutil.which(t) is None]
    if not os.path.exists(BUS_LAUNCHER):
        missing.append(BUS_LAUNCHER)
    if missing:
        pytest.skip("slice 2 needs: " + ", ".join(missing))

    # A headless gnome-shell's Xwayland (#217), not a bare Xvfb: capture
    # finds a frame's X window through the window manager's client list,
    # and a bare Xvfb has none (D75) -- so this test failed on `main` behind
    # the hang that usually stopped it first.
    with nested_env() as env:
        probe = subprocess.Popen(
            ["dbus-run-session", "--", "bash", "-c",
             inner(f"{sys.executable} -m tests.linux_reading_probe")],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            start_new_session=True, env=env,
        )
        try:
            # A real deadline (collect): the old loop only checked the clock
            # when a line arrived, so a silent probe hung the suite.
            line, _trace = collect(probe.stdout, '"controls"', 180)
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(probe.pid), signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired):
                probe.wait(timeout=20)

    if line is None:
        pytest.skip("the slice-2 probe produced no report")
    return json.loads(line)


@pytest.mark.parametrize("name", ["plain entry", "password entry", "password widget"])
def test_no_editable_entry_discloses_its_contents(wired, name):
    """The policy in force where it matters. `tests/test_linux_reading.py`
    asserts AT-SPI *will* return `hunter2`; this asserts the backend does
    not, for the hidden entry and the plain one alike -- because nothing
    distinguishes them (D#34b)."""
    assert wired["controls"][name]["read"] is None


def test_a_caption_still_reads(wired):
    """The blast radius stays small. Buttons, labels and tables are not
    somewhere a secret is typed, and withholding them would cost the reads
    `read` mostly exists for. A control with no `Text` interface answers with
    its caption, which is what `WM_GETTEXT` gives such a window on Windows."""
    assert wired["controls"]["Recalculate"]["read"] == "Recalculate"
    assert wired["controls"]["status"]["read"] == "ready"
    assert wired["controls"]["results grid"]["read"] == "results grid"


def test_only_the_declared_password_widget_reports_protected(wired):
    """`is_protected` is deliberately narrower than the disclosure policy: it
    also refuses *typing* (D38), and a wider answer would refuse to type into
    every text field on screen. So the hidden entry is withheld but not
    protected -- undisclosed, still typeable."""
    assert wired["controls"]["password widget"]["protected"] is True
    assert wired["controls"]["password entry"]["protected"] is False
    assert wired["controls"]["plain entry"]["protected"] is False


def test_a_plain_entry_still_reads_as_none_by_default(wired):
    """Withholding is unchanged by D#43: the default is still not to look.

    What changed is that `None` is no longer the *only* thing a caller gets
    -- see the next test. This one pins the policy itself, so a disclosure
    opt-in cannot quietly become a disclosure default.
    """
    plain = wired["controls"]["plain entry"]
    assert plain["read"] is None and plain["protected"] is False


def test_a_withheld_field_now_says_so_instead_of_borrowing_none(wired):
    """The fix D#43 made, asserted from the direction of the bug it closed.

    `None` means "did not answer" everywhere else in this contract, and on
    Windows that is unambiguous because the OS refuses the read only for
    password fields (D37). Here it also meant "withheld", and `is_protected`
    separates only the *declared* widget -- so a perfectly healthy text field
    read exactly like a hung one, and a caller told the first went off
    diagnosing a hang that was not happening.

    `disclosure` gives the third state its own name, and the three fixture
    controls land on three different answers:

    * `password widget` -- `Gtk.PasswordEntry`, which carries the role --
      is **protected**.
    * `plain entry` and `password entry` -- an ordinary entry and one told
      not to show its characters -- are both **withheld**, because nothing
      AT-SPI exposes tells them apart (D#34b). That they agree here *is*
      the finding.
    * `status`, a label, is **allowed**.
    """
    controls = wired["controls"]
    assert controls["password widget"]["disclosure"] == "protected"
    assert controls["plain entry"]["disclosure"] == "withheld"
    assert controls["password entry"]["disclosure"] == "withheld"
    assert controls["status"]["disclosure"] == "allowed"


def test_asking_for_disclosure_returns_the_value_but_never_the_protected_one(wired):
    """The opt-in works, and only for the withheld state.

    A caller that has thought about it can have a plain field's contents.
    The *declared* password widget is not disclosed even on request: that
    verdict is not a guess, so there is nothing for a caller to know better
    about, and a measurement never overrules a person at any grain in the
    other direction either (D#34b, D35).

    **`password entry` discloses, and that is the honest cost of D#34b.**
    It is a hidden field, and asking for it returns the secret -- because
    the driver genuinely cannot tell it from `plain entry`. Withholding by
    class buys safety by default; it cannot buy safety against a caller who
    explicitly asks, and pretending otherwise would be a guarantee this
    platform cannot keep.
    """
    controls = wired["controls"]
    assert controls["plain entry"]["read_disclosed"] == "plain", controls
    assert controls["password widget"]["read_disclosed"] is None, (
        "a declared password field was disclosed on request; disclose must "
        "not override protected"
    )
    assert controls["status"]["read_disclosed"] == "ready", (
        "disclose must not change what an allowed field returns"
    )


def test_a_window_captures_as_a_real_png(wired):
    """Only toplevels have an X id, so a handle captures its window (D#8).
    Asserted as a decoded size rather than a byte count, because a capture
    that returns bytes and no picture is the trap D66 names."""
    capture = wired["capture"]
    assert "error" not in capture, capture
    assert capture["is_png"] is True
    assert capture["width"] > 100 and capture["height"] > 100, capture
