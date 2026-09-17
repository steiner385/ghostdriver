"""The element view (#104, D#104): elements that are not windows.

`walk_elements_awake`, `is_selected` and `_current_value` were built and
documented (D#104) but never run against a real accessible tree -- every
other Linux slice has a probe against `tests/fixtureapp_gtk.py`, this view
did not. `tests/linux_elements_probe.py` is that probe; this is the nested
stack that runs it, on the pattern `tests/test_linux_atspi.py` set.
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

from tests.conftest import on_linux

pytestmark = [on_linux, pytest.mark.slow]

DISPLAY = ":85"
BUS_LAUNCHER = "/usr/libexec/at-spi-bus-launcher"


def _unavailable():
    missing = [t for t in ("Xvfb", "dbus-run-session") if shutil.which(t) is None]
    if not os.path.exists(BUS_LAUNCHER):
        missing.append(BUS_LAUNCHER)
    return missing


@pytest.fixture(scope="module")
def report():
    missing = _unavailable()
    if missing:
        pytest.skip("nested AT-SPI stack unavailable: " + ", ".join(missing))

    server = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", "1280x800x24"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        inner = (f"{BUS_LAUNCHER} --launch-immediately & sleep 3; "
                 f"exec {sys.executable} -m tests.linux_elements_probe")
        done = subprocess.run(
            ["dbus-run-session", "--", "bash", "-c", inner],
            capture_output=True, text=True, timeout=120,
            env=dict(os.environ, DISPLAY=DISPLAY, GSETTINGS_BACKEND="memory",
                     PYTHONPATH="src"),
        )
        line = next((ln for ln in done.stdout.splitlines()
                     if ln.startswith("{") and '"elements"' in ln), None)
        if line is None:
            pytest.skip("the elements probe produced no report:\n" + done.stdout[-800:]
                        + "\n" + done.stderr[-800:])
        yield json.loads(line)
    finally:
        server.terminate()
        server.wait(timeout=10)


def test_walk_elements_awake_reaches_every_shape(report):
    """One walk from the frame, no wake step (no dormant engine on Linux to
    nudge -- the embedded-document case, L8/#15, is unmeasured here)."""
    assert report["count"] > 20, "the walk should reach most of the fixture"


def test_an_editable_entry_carries_the_value_pattern(report):
    """`EditableText` becomes the neutral `Value` pattern, the name
    `set_value` and `_current_value` look for -- AT-SPI keeps the interfaces
    distinct, the element view does not need the caller to know that."""
    plain = report["elements"]["plain"]
    assert plain["control_type"] == "text"
    assert plain["patterns"] == ["Value"]
    assert plain["enabled"] is True
    assert plain["offscreen"] is False


def test_a_password_widget_is_flagged_and_still_carries_value(report):
    password = report["elements"]["password_widget"]
    assert password["control_type"] == "password text"
    assert password["is_password"] is True
    assert password["patterns"] == ["Value"]


def test_sibling_index_counts_within_role_under_the_same_parent(report):
    """The only identity an unlabelled control has (D#101): position among
    siblings of the *same* control type. Two `text` entries share a parent
    here, so the second is index 2, not 1."""
    assert report["elements"]["plain"]["sibling_index"] == 1
    assert report["elements"]["password"]["sibling_index"] == 2
    # A different role restarts the count.
    assert report["elements"]["password_widget"]["sibling_index"] == 1


def test_a_checkbox_carries_the_selection_item_pattern(report):
    """`_SELECTABLE_ROLES` includes "check box"; AT-SPI carries selection as
    state rather than a pattern, so the element view synthesises the neutral
    pattern name from the role."""
    opt_in = report["elements"]["opt_in"]
    assert opt_in["control_type"] == "check box"
    assert opt_in["patterns"] == ["SelectionItem"]


def test_plain_controls_carry_no_pattern_at_all(report):
    for key in ("toolbar_new", "status", "grid", "drawn"):
        assert report["elements"][key]["patterns"] == [], key


def test_the_window_itself_is_not_one_of_its_own_elements(report):
    """`walk_elements_awake`'s own contract: the frame is the root the walk
    starts from, and is not returned as an element with itself as ancestor."""
    assert report["frame_in_ancestors"] is False


def test_current_value_withholds_every_editable_entry_not_only_passwords(report):
    """D#34b's fail-closed shape, measured rather than assumed: AT-SPI cannot
    tell a plain `Gtk.Entry` from one with `visibility=False`, so *both* come
    back empty, the same as the toolkit-declared `Gtk.PasswordEntry` -- a
    plain field is not spared because nothing on this platform can prove it
    is plain."""
    value = report["value"]
    assert value["plain"] == ""
    assert value["password"] == ""
    assert value["password_widget"] == ""


def test_current_value_discloses_a_control_that_is_not_typed_into(report):
    """The contrast that proves the withhold above is deliberate: a label is
    not a field a secret is typed into, so it is classified `ALLOWED` and
    read normally."""
    assert report["value"]["status"] == "ready"


def test_is_selected_is_none_off_the_selection_item_pattern(report):
    """An element with no `SelectionItem` pattern carries no selection state
    to re-read; `is_selected` says so rather than guessing at False."""
    assert report["is_selected_off_pattern"] is None


def test_is_selected_re_reads_live_state_not_the_enumeration_snapshot(report):
    """The reason `is_selected` re-reads rather than trusting `element.selected`:
    the state that proves a click worked is the one *after* it. The same
    `AccessibleElement`, asked twice around the fixture's own state change,
    answers differently without a re-walk."""
    assert report["opt_in_selected_before"] is False
    assert report["opt_in_selected_after"] is True
