"""The capture path crosses the two identifier spaces through the tree's
correlation, not through `_NET_WM_PID` (D#101a).

D#101 measured that a Flatpak target's top-levels carry **no** `_NET_WM_PID`
and that the pid AT-SPI reports is its `xdg-dbus-proxy`'s, one process off
the real one. It named four paths the absent property silently empties --
`top_level_state`, `snapshot`, the capture-by-frame path, and the
interference watch -- and three of them were rewired onto `display.windows_of`
and the XRes bridge. The fourth was not: `reading._toplevel_xid` went on
forking `xwininfo -root -children` and then `xprop _NET_WM_PID` per
candidate, matching on the a11y pid.

For a sandboxed target that is wrong twice over. No window answers the
property, so every candidate compares `None`; and the pid being compared
against is the proxy's, which is not the pid the X server knows any window
by. `capture` therefore raised "no X window behind this handle" for a target
that was on screen, enumerating fully, and already correlated.

`tests/linux_xid_probe.py` had already written the indictment down -- the pid
match "returns the first pid match, which is the wrong answer whenever there
is a modal up" -- and the bridge it produced (`tree._correlate_frame`,
exposed as `tree.frame_xid_of`) was built and left with no callers. These
tests are what wires it in.

Gated to Linux because the subject is the Linux backend, the mirror of the
`on_windows` convention (`docs/LINUX.md`). They need no a11y bus, no display
and no window manager: the frame correlation is fed in directly, which is the
point -- what is under test is *which bridge the capture path asks*, not the
bridge. The backend import is inside each function, never at module scope
(`test_no_test_module_binds_a_platform_at_import_time`).
"""

import pytest

from tests.conftest import on_linux

pytestmark = on_linux

#: Measured on linux-host-a against Bambu Studio 02.08.02.61, recorded in D#101.
#: The pid AT-SPI reports for the application node -- the proxy's.
PROXY_PID = 1461887
#: The operator Studio's top-level, and a modal of the same process. Two
#: windows of one pid is the case the old pid match could not answer.
MAIN_XID = 0x680010B
MODAL_XID = 0x680019C


class _Accessible:
    """Enough of an AT-SPI node for the walk the old route performed.

    It answers `get_role_name`, `get_parent` and `get_process_id`, so a test
    that still reached the pid-matching route would get all the way into it
    rather than failing earlier for an unrelated reason.
    """

    def __init__(self, role, name, parent=None):
        self._role, self._name, self._parent = role, name, parent

    def get_role_name(self):
        return self._role

    def get_name(self):
        return self._name

    def get_parent(self):
        return self._parent

    def get_process_id(self):
        return PROXY_PID


class _NoSubprocess:
    """Stands in for the `subprocess` module in `reading`, and fails the test
    if the capture path shells out to find a window.

    Two processes per call is the shape D#40c named a fork bomb, and the
    answer was already in the tree.
    """

    #: Carried so a caller's `except` clause resolves and the test fails on
    #: the fork it is about, rather than on a missing attribute.
    TimeoutExpired = __import__("subprocess").TimeoutExpired

    def run(self, argv, *args, **kwargs):
        raise AssertionError(
            "the capture path forked to find its window: " + " ".join(map(str, argv))
        )


def _frames(*correlated):
    """A tree as `enumerate_process` would leave it for a Flatpak target:
    frames correlated to X windows by name and size, with a control under the
    last one. Returns that control's handle.

    `correlated` is one `(index, name, xid)` per frame.
    """
    from ghostdriver.backends.linux import tree

    tree._reset()
    control = None
    for index, name, xid in correlated:
        frame_accessible = _Accessible("frame", name)
        frame = tree._mint((PROXY_PID, index), tree._Entry(
            accessible=frame_accessible, path=(PROXY_PID, index), pid=PROXY_PID,
            role="frame", name=name, states=frozenset(), interfaces=(),
        ))
        tree._HANDLES[frame].xid = xid
        control = tree._mint((PROXY_PID, index, 3), tree._Entry(
            accessible=_Accessible("push button", "Slice plate", frame_accessible),
            path=(PROXY_PID, index, 3), pid=PROXY_PID,
            role="push button", name="Slice plate",
            states=frozenset(), interfaces=(),
        ))
    return control


@pytest.fixture
def captures(monkeypatch):
    """Records the xid the capture path settled on, without rendering it.

    `capture_xid` is the seam below the question these tests ask: what is
    under test is which window gets photographed, not the photograph.
    """
    from ghostdriver.backends.linux import reading

    seen = []

    def record(xid, *, region=None):
        seen.append(xid)
        return (b"png", 1, 1)

    monkeypatch.setattr(reading, "capture_xid", record)
    return seen


def test_capture_reaches_a_target_whose_windows_carry_no_net_wm_pid(
        captures, monkeypatch):
    """The Flatpak case (D#101). Every top-level answers "not found" for
    `_NET_WM_PID`, and the capture still finds the window, because the tree
    correlated it by name and size when it enumerated it."""
    from ghostdriver.backends.linux import display, reading

    control = _frames((0, "Bambu Studio", MAIN_XID))
    monkeypatch.setattr(display, "window_pid", lambda xid: None)

    reading.capture_window(control)

    assert captures == [MAIN_XID]


def test_the_capture_path_forks_nothing_to_find_its_window(captures, monkeypatch):
    """The old route ran `xwininfo` once and `xprop` per candidate on every
    capture. The correlation is already in hand, so the answer costs no
    processes at all."""
    from ghostdriver.backends.linux import reading

    control = _frames((0, "Bambu Studio", MAIN_XID))
    monkeypatch.setattr(reading, "subprocess", _NoSubprocess())

    reading.capture_window(control)

    assert captures == [MAIN_XID]


def test_a_control_inside_a_modal_captures_the_modal_not_the_window_behind_it(
        captures):
    """Two windows of one process is the case matching on pid could not
    answer: it returned the first, so a control in a dialog photographed the
    window underneath. The tree keys on the frame's *path*, so it cannot."""
    control = _frames((0, "Bambu Studio", MAIN_XID),
                      (1, "Unsaved changes", MODAL_XID))

    from ghostdriver.backends.linux import reading

    reading.capture_window(control)

    assert captures == [MODAL_XID]


def test_a_handle_whose_frame_was_never_correlated_is_refused_not_guessed(
        captures, monkeypatch):
    """An uncorrelated frame is the ambiguous case `_correlate_frame` declines
    to resolve (D33), and the capture says so rather than photographing
    whatever else is on the display."""
    from ghostdriver.backends.linux import display, reading

    control = _frames((0, "Bambu Studio", 0))
    monkeypatch.setattr(display, "window_pid", lambda xid: None)

    with pytest.raises(reading.CaptureError) as raised:
        reading.capture_window(control)

    assert "no X window" in str(raised.value)
    assert captures == []
