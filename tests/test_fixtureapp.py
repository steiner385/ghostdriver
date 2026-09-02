"""The fixture is a claim about what a Profile L1 target is like.

If it drifts, every actuation test built on it is testing something else, so
each characteristic spec section 10 requires is asserted here rather than
assumed from the code that creates it.
"""

import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes

import psutil
import pytest

from tests.conftest import on_windows

pytestmark = on_windows

BM_CLICK = 0x00F5
WM_GETDLGCODE = 0x0087
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_CHAR, WM_SETTEXT = 0x0102, 0x000C
MK_LBUTTON = 0x0001
DLGC_HASSETSEL = 0x0008
#: The low nibble of a BUTTON's style says which kind it is. A window with
#: none of those bits never told the system it was a button.
BS_MASK = 0x0000000F


@pytest.fixture(scope="module")
def app():
    """The fixture application, quiet by default.

    Module-scoped: it is a real process with fifty-odd windows, and standing
    one up per test would dominate the suite's runtime for no benefit --
    none of these tests leave state behind that another would see.
    """
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp"],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        announced = proc.stdout.readline()
        if not announced.startswith("{"):
            raise RuntimeError(f"fixture did not start: {announced!r}")
        handles = json.loads(announced)
        time.sleep(0.4)  # let the child windows finish being created
        yield handles
    finally:
        pid = locals().get("handles", {}).get("pid")
        if pid and pid != proc.pid:
            try:
                psutil.Process(pid).terminate()
            except psutil.Error:
                pass
        proc.terminate()
        proc.wait(timeout=5)


@pytest.fixture
def user32():
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                               wintypes.LPARAM]
    u.SendMessageW.restype = ctypes.c_ssize_t
    u.PostMessageW.argtypes = u.SendMessageW.argtypes
    u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.GetWindowLongW.restype = ctypes.c_long
    return u


def tree_of(pid):
    from ghostdriver.backends.windows.enumerate import enumerate_process
    from ghostdriver.model.window import select_main_tree

    return select_main_tree(enumerate_process(pid))


def find(pid, cls, text=None):
    return [n for n in tree_of(pid).walk()
            if n.class_name == cls and (text is None or n.text == text)]


# --- the profile it exists to reproduce ----------------------------------

def test_the_fixture_classifies_as_profile_l1(app):
    """The whole point, and the thing most likely to drift.

    An early version had sixteen windows, several of them native EDIT and
    STATIC controls that the HWND-to-UIA bridge describes with patterns.
    That inverts the ratio a real target has and classified as M1 -- the
    wrong profile to develop a driver against. "One window per control" is
    not decoration; it is the profile.
    """
    from ghostdriver.probe.runner import run_phase1

    document = run_phase1(app["pid"]).to_dict()

    assert document["matched_profile"] == "L1", document["classification_reason"]
    assert document["window_count"] >= 50, "one window per control"


# --- section 10, item by item --------------------------------------------

def test_1_buttons_are_a_vendor_class_that_says_nothing_about_itself(app, user32):
    button = find(app["pid"], "GhostFixtureCommandButton")[0]
    style = user32.GetWindowLongW(wintypes.HWND(button.handle), -16) & 0xFFFFFFFF
    dlgcode = user32.SendMessageW(wintypes.HWND(button.handle),
                                  WM_GETDLGCODE, 0, 0)

    assert style & BS_MASK == 0, "no BS_* style bits"
    assert dlgcode == 0, "nothing about this window says 'button'"


def test_2_bm_click_does_nothing_and_the_input_pair_actuates(app, user32):
    """The single most important property of the fixture.

    A semantic message is implemented by a specific window class and is
    discarded by anything else. If BM_CLICK worked here, a driver that only
    ever sent BM_CLICK would pass every test and fail on the first real
    target.
    """
    from ghostdriver.backends.windows.text import read_window_text

    button = find(app["pid"], "GhostFixtureCommandButton", "Expand All")[0]
    before = read_window_text(app["status"])

    user32.SendMessageW(wintypes.HWND(button.handle), BM_CLICK, 0, 0)
    time.sleep(0.15)
    assert read_window_text(app["status"]) == before, "BM_CLICK was ignored"

    user32.PostMessageW(wintypes.HWND(button.handle), WM_LBUTTONDOWN,
                        MK_LBUTTON, 0)
    user32.PostMessageW(wintypes.HWND(button.handle), WM_LBUTTONUP, 0, 0)
    time.sleep(0.25)
    after = read_window_text(app["status"])

    assert after != before, "the input-shaped pair actuated"
    assert "Expand All" in after, "and the application knows which control"


def test_3_the_grid_exposes_nothing_through_any_surface(app):
    from ghostdriver.backends.windows.enumerate import direct_children
    from ghostdriver.backends.windows.msaa import assess_msaa
    from ghostdriver.backends.windows.text import read_window_text
    from ghostdriver.backends.windows.uia import assess_uia

    grid = find(app["pid"], "GhostFixtureDataGrid")[0]

    assert direct_children(grid.handle) == [], "no per-cell windows"
    assert not read_window_text(grid.handle), "no text"
    assert assess_uia(grid.handle, view="raw", max_depth=6).element_count <= 1
    assert assess_msaa([grid.handle]).named == 0


def test_3b_the_grid_is_classified_as_needing_pixels(app):
    """A driver has to be able to *tell* that this one needs a capture."""
    from ghostdriver.backends.windows.region import region_evidence
    from ghostdriver.surface import SurfaceKind, surface_map

    regions = surface_map(tree_of(app["pid"]), region_evidence)
    grids = [r for r in regions if r.class_name == "GhostFixtureDataGrid"]

    assert grids, "the grid is in the surface map"
    assert grids[0].kind is SurfaceKind.OPAQUE


def test_4_the_edits_are_superclassed_natives(app, user32):
    """They answer EDIT's own messages while carrying a vendor class name --
    which is what superclassing is, and what makes them read like a native
    field to everything except a class-name check."""
    plain = find(app["pid"], "GhostFixturePlainEdit")[0]
    dlgcode = user32.SendMessageW(wintypes.HWND(plain.handle),
                                  WM_GETDLGCODE, 0, 0)

    assert dlgcode & DLGC_HASSETSEL, "still behaves as an EDIT"
    assert plain.class_name != "Edit", "but does not answer to that name"


def test_4b_wm_settext_changes_the_display_but_not_the_bound_value(
    app, user32
):
    """The `set_text` question the spec records as unverified, made
    observable.

    The field shows the new text while the application still holds the old
    value. A caller that sets text and reads the display back cannot tell
    the difference -- which is exactly why an action needs a postcondition
    that checks the thing that matters rather than the thing that is easy.
    """
    from ghostdriver.backends.windows.text import read_window_text

    bound = find(app["pid"], "GhostFixtureBoundEdit")[0]
    committed_before = read_window_text(app["bound_mirror"])

    buffer = ctypes.create_unicode_buffer("SET-BY-MESSAGE")
    user32.SendMessageW(wintypes.HWND(bound.handle), WM_SETTEXT, 0,
                        ctypes.cast(buffer, ctypes.c_void_p).value)
    time.sleep(0.15)

    assert read_window_text(bound.handle) == "SET-BY-MESSAGE", "display changed"
    assert read_window_text(app["bound_mirror"]) == committed_before, (
        "but the bound value did not"
    )

    user32.SendMessageW(wintypes.HWND(bound.handle), WM_CHAR, ord("Z"), 0)
    time.sleep(0.15)
    assert read_window_text(app["bound_mirror"]) != committed_before, (
        "the keyboard path does commit"
    )


def test_6_identical_captions_at_identical_rects_on_stacked_pages(app):
    """Only an ancestor tells these apart. Coordinates cannot, and neither
    can a caption -- which is what ancestor scoping exists for."""
    applies = find(app["pid"], "GhostFixtureCommandButton", "Apply")

    assert len(applies) == 2
    assert applies[0].rect == applies[1].rect
    assert applies[0].handle != applies[1].handle


def test_6b_ancestor_scoping_separates_them(app):
    from ghostdriver.model.locator import Locator
    from ghostdriver.resolve import resolve

    tree = tree_of(app["pid"])
    unscoped = resolve(tree, Locator(text="Apply", visible=None))
    scoped = resolve(tree, Locator(
        text="Apply", visible=None,
        within=Locator(class_name="GhostFixturePage", text="Operations",
                       visible=None),
    ))

    assert len(unscoped) == 2
    assert len(scoped) == 1


def test_8_the_process_is_dpi_unaware(app):
    """DPI virtualization: rects come back in virtualized coordinates, which
    is what makes coordinate-based approaches fragile on this profile."""
    shcore = ctypes.WinDLL("shcore")
    awareness = ctypes.c_int()
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, app["pid"])
    shcore.GetProcessDpiAwareness(handle, ctypes.byref(awareness))

    assert awareness.value == 0, "0 = unaware"


def test_9_no_application_supplied_uia_provider(app):
    """Every HWND gets a bridge element whether the application wants one or
    not, so the assertion is about *proportion*: a tree of vendor classes
    the bridge cannot describe, not an empty tree.
    """
    from ghostdriver.backends.windows.uia import assess_uia

    assessed = assess_uia(tree_of(app["pid"]).handle, view="control",
                          max_depth=8)

    assert assessed.element_count > 1, "the bridge is present, as it always is"
    assert assessed.richness < 0.5, (
        "but almost nothing carries a pattern, which is the profile"
    )


# --- the induced failures: items 5 and 7 ---------------------------------
#
# These are the characteristics that exist because a naive fixture would not
# exhibit them. They are opt-in at the application level -- off by default --
# because a suite has to be runnable on a machine somebody is working at.

def test_7_a_modal_appears_mid_run_and_holds_the_application():
    """A dialog that was not there when the run started.

    An automated caller that plans against the screen it first saw will
    retry into a disabled window forever, which is why blocking state is
    reported rather than left to be inferred from failures.
    """
    from ghostdriver.backends.windows.modality import top_level_state
    from ghostdriver.modality import find_modal_blocks

    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp", "--modal-after", "400"],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        handles = json.loads(proc.stdout.readline())
        time.sleep(0.3)

        blocks, _ = find_modal_blocks(top_level_state(handles["pid"]))
        assert not blocks, "nothing is blocking yet"

        time.sleep(0.6)
        blocks, _ = find_modal_blocks(top_level_state(handles["pid"]))

        assert blocks, "the modal appeared mid-run and was detected"
        assert blocks[0].dialog.text == "Confirm Delete Record"
    finally:
        try:
            psutil.Process(handles["pid"]).terminate()
        except Exception:
            pass
        proc.terminate()
        proc.wait(timeout=5)


@pytest.mark.skipif(
    os.environ.get("GHOSTDRIVER_ALLOW_FOCUS_TESTS") != "1",
    reason=(
        "takes the foreground, so it is opt-in: set "
        "GHOSTDRIVER_ALLOW_FOCUS_TESTS=1 to run it. Everything else in this "
        "suite leaves the desktop alone."
    ),
)
def test_5_the_application_grabs_the_foreground_after_acting(user32):
    """Section 10 item 5, and the reason isolation exists at all.

    The delay is what makes it a problem: the click succeeds, the caller
    moves on, and the window arrives in front of whoever is using the
    machine a moment later.
    """
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp", "--onscreen",
         "--grab-foreground-after", "300"],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        handles = json.loads(proc.stdout.readline())
        time.sleep(0.4)
        before = user32.GetForegroundWindow()

        from ghostdriver.backends.windows.enumerate import enumerate_process
        from ghostdriver.model.window import select_main_tree

        tree = select_main_tree(enumerate_process(handles["pid"]))
        button = next(n for n in tree.walk()
                      if n.class_name == "GhostFixtureCommandButton")
        user32.PostMessageW(wintypes.HWND(button.handle), WM_LBUTTONDOWN,
                            MK_LBUTTON, 0)
        user32.PostMessageW(wintypes.HWND(button.handle), WM_LBUTTONUP, 0, 0)

        time.sleep(0.15)
        during = user32.GetForegroundWindow()
        time.sleep(0.6)
        after = user32.GetForegroundWindow()

        assert during == before, "nothing happens immediately -- that is the trap"
        assert after == handles["main"], "and then it takes the foreground"
    finally:
        try:
            psutil.Process(handles["pid"]).terminate()
        except Exception:
            pass
        proc.terminate()
        proc.wait(timeout=5)
