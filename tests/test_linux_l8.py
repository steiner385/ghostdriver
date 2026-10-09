"""L8: an embedded document -- the wake, the click, the typing, on Linux.

D58 asked the same question of Chromium on Windows: does the accessibility
tree wake on the first ask, and can a click and a write reach the page
through it. Here the answer diverges from Windows in both halves.

**The wake.** WebKitGTK's GTK4 binding (`WebKit` 6.0) never published a
document over AT-SPI in this measurement -- not once, across a dozen runs
and sixty-second waits, load-complete or not, sandboxed or not. WebKitGTK's
GTK3 binding (`webkit2gtk-4.1`) did, and with the document already complete
the very first time anything asked: no retry ever observed. `docs/LINUX.md`
recorded GTK 3 as unavailable from PyGObject on the host that wrote it
(D75); it is available on this one, which is why the fixture uses it.

**The write.** A web `<input>` here carries no `EditableText` and no
`Value` at all (measured: `Text`, `Action`, `Component`, `Collection`,
`Hyperlink` and nothing writable) -- unlike a native GTK entry, which does
(D#10). So there is no tier-1 write route to a web field on this backend;
typing one would need tier 4 (XTest under the live-actuation gate), which
this test does not exercise. The click and the password-field detection do
not need it: `Action.DoAction` and role-based state reads already work the
same for a web element as for a native one, with no code specific to the
web case at all.
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
from tests.linux_probe_support import collect

pytestmark = [on_linux, pytest.mark.slow]

DISPLAY = ":75"
BUS_LAUNCHER = "/usr/libexec/at-spi-bus-launcher"


@pytest.fixture(scope="module")
def l8():
    missing = [t for t in ("Xvfb", "dbus-run-session") if shutil.which(t) is None]
    if not os.path.exists(BUS_LAUNCHER):
        missing.append(BUS_LAUNCHER)
    if missing:
        pytest.skip("the L8 measurement needs: " + ", ".join(missing))

    server = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", "1280x800x24"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    inner = (f"{BUS_LAUNCHER} --launch-immediately & sleep 3; "
             f"exec {sys.executable} -m tests.linux_l8_probe")
    probe = subprocess.Popen(
        ["dbus-run-session", "--", "bash", "-c", inner],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        start_new_session=True,
        env=dict(os.environ, DISPLAY=DISPLAY, GSETTINGS_BACKEND="memory",
                 GDK_BACKEND="x11", PYTHONPATH="src"),
    )
    try:
        # A real deadline (collect): the old loop only checked the clock
        # when a line arrived, so a silent probe hung the suite.
        line, _trace = collect(probe.stdout, '"found_on_bus"', 120)
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(probe.pid), signal.SIGTERM)
        with contextlib.suppress(subprocess.TimeoutExpired):
            probe.wait(timeout=20)
        server.terminate()
        server.wait(timeout=10)

    if line is None:
        pytest.skip("the L8 probe produced no report")
    report = json.loads(line)
    if not report.get("found_on_bus"):
        pytest.skip("the L8 fixture never appeared on the accessibility bus")
    return report


def test_a_webkitgtk3_document_is_awake_on_the_first_ask(l8):
    """The wake finding, pinned. If this starts failing, WebKitGTK's GTK3
    binding has started behaving like Chromium on Windows (D58) or like
    WebKitGTK's own GTK4 binding measured alongside it (never), and
    `walk_elements_awake`'s docstring needs revisiting either way."""
    if not l8["doc_present"]:
        pytest.skip("no document ever appeared -- see the module docstring's "
                    "GTK4 finding; nothing below this can be measured")
    if not l8.get("load_finished_before_ask"):
        # The first ask is only the wake question once the page has loaded;
        # before that it measures the load. Skipped, with the wait, rather
        # than failed: a harness that never reached the state the test is
        # about has measured nothing (test_linux_restore.py's precedent).
        pytest.skip(f"the page did not finish loading within "
                    f"{l8.get('load_wait_s')}s, so the first ask measured the load")
    assert l8["doc_found_on_first_ask"] is True, (
        f"the loaded page's document was not there on the first ask "
        f"(load took {l8.get('load_wait_s')}s)")
    assert l8["doc_children_on_first_ask"] and l8["doc_children_on_first_ask"] > 0
    assert l8["woke_after_s"] == 0.0


def test_a_page_button_is_driven_by_the_accessibility_api(l8):
    """The same route a native button uses (`act_via_action`,
    `do_action(node, 0)`), unmodified: this passes with no web-specific
    code at all. The action's own name differs from a native button's
    (measured: `press`, not `click`) but nothing here reads that name."""
    if not l8["doc_present"]:
        pytest.skip("no document to click into")
    assert l8["button_found"] is True
    assert l8["button_do_action"] is True
    assert l8["status_after_click"] and "clicks=1" in l8["status_after_click"], (
        "the action reported success without the page doing anything"
    )


def test_a_web_input_has_no_tier_one_write_route(l8):
    """The divergence from D#10's native entry, and from D58's Chromium: no
    `EditableText`, no `Value`. `set_text_via_editable` already returns
    False for this rather than raising (it wraps the call in
    `contextlib.suppress`), so the existing ladder needs no change -- this
    only pins that the field really does lack the interface, so a future
    WebKitGTK version that gains one is noticed rather than assumed away.
    """
    if not l8["doc_present"]:
        pytest.skip("no document to read an entry from")
    assert l8["entry_found"] is True
    assert "EditableText" not in l8["entry_interfaces"]
    assert "Value" not in l8["entry_interfaces"]
    assert l8["entry_before"] == "PART-0001"
    assert isinstance(l8["entry_set_text_contents"], str), (
        "set_text_contents stopped raising -- a web input may have gained "
        "a tier-1 write route; if so, docs/LINUX.md's L8 entry needs "
        "updating alongside this test"
    )
    # Unwritten: no interface reached it.
    assert l8["entry_after"] == "PART-0001"


def test_a_web_password_field_is_detected_the_same_way_as_a_native_one(l8):
    """`is_password = entry.role == "password text"` (`elements.py`) reads
    the role alone, so a web password field needs no code of its own to be
    withheld -- this is the finding that confirms the existing check
    already covers it."""
    if not l8["doc_present"]:
        pytest.skip("no document to find a password field in")
    assert l8["password_role_found"] is True


def test_a_page_tab_carries_selected_state_the_way_a_native_one_does(l8):
    """`is_selected` (`elements.py`) re-reads `SELECTED`/`CHECKED` from the
    live state set, role-based rather than pattern-based (D#104) -- this
    checks a web ARIA tab carries the same state a native `page tab` does,
    so that existing read needs no web-specific branch either."""
    if not l8["doc_present"]:
        pytest.skip("no document to find a tab in")
    if "tab_selected_after" not in l8:
        pytest.skip("the tab was not found or the click could not be measured")
    assert l8["tab_selected_before"] is False
    assert l8["tab_selected_after"] is True
