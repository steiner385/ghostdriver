"""The tier-4 commit, on the operator's own display, gated hard (D#111).

D#102 measured that on wxGTK3 a value only reaches the application through a
real Enter -- there is no tier-1 commit -- and that `grab_focus` both works
and raises the window to the foreground. So committing a setting in the
Studio the operator is watching means taking the real keyboard for an
instant (tier 4), which D9 excludes by default. This is the one place it is
allowed, and only under the "operator-present live actuation" consent a
session records at attach:

* the operator has named a window of the target that is *already* the
  foreground (`live_window`), so nothing this action does changes which
  top-level the operator is looking at;
* the foreground and the pointer are re-checked immediately before the
  focus and again before the Enter, and any change **aborts** the action --
  it is reported as a disturbance (D28), never smoothed into a display-only
  write;
* an `InterferenceWatch` is armed around the whole action by the tool layer,
  so a move the guard misses between checks is still seen and reported.

The guard is a plain function of two samplers, so its logic is testable
without a desktop; the desktop calls are injected.
"""

from __future__ import annotations

from collections.abc import Callable

from . import display
from . import input as linux_input


class LiveActuationAborted(RuntimeError):
    """The operator's desktop moved under a live action, so it was stopped.

    Carries what changed, so the tool can report it as a disturbance rather
    than a bare failure -- the point of the guard is that the operator sees
    why nothing happened.
    """

    def __init__(self, what: str):
        super().__init__(what)
        self.what = what


def _guard(live_window: int, baseline_cursor: tuple[int, int],
           active: Callable[[], int | None],
           cursor: Callable[[], tuple[int, int]]) -> None:
    """Raise unless the operator's foreground and pointer are where they
    were. Called before the focus and before the Enter."""
    now = active()
    if now != live_window:
        raise LiveActuationAborted(
            f"the foreground window changed (expected {live_window:#x}, "
            f"found {now:#x} -- the operator switched away or something "
            "raised itself); nothing was committed")
    if cursor() != baseline_cursor:
        raise LiveActuationAborted(
            "the pointer moved while acting; the operator is at the desk, so "
            "the action was stopped before it could interfere")


def commit_value(handle: int, text: str, *, live_window: int,
                 active: Callable[[], int | None] = display.active_window,
                 cursor: Callable[[], tuple[int, int]] = display.cursor,
                 write: Callable[[int, str], bool] | None = None,
                 focus: Callable[[int], bool] | None = None,
                 enter: Callable[[], bool] | None = None) -> bool:
    """Write `text` into the field and commit it with a real Enter.

    Returns True when the Enter was delivered, False when a step declined,
    and raises `LiveActuationAborted` when the operator's desktop moved.
    The value is written first (tier 1, no input), then the field is focused
    and Enter pressed (tier 4). The write alone would show the value without
    committing it (D#102), which is why this is one operation and reports as
    one tier -- the rung that actually reached the application is the Enter.
    """
    write = write or linux_input.set_text_via_editable
    focus = focus or linux_input.focus_via_component
    enter = enter or (lambda: display.press_key("Return"))

    if live_window == 0:
        raise LiveActuationAborted(
            "no live window was consented at attach, so a real keystroke "
            "may not be sent on the operator's display")

    baseline_cursor = cursor()
    _guard(live_window, baseline_cursor, active, cursor)

    if not write(handle, text):
        return False
    _guard(live_window, baseline_cursor, active, cursor)

    focus(handle)  # raises the (already foreground) live window; sets the caret
    _guard(live_window, baseline_cursor, active, cursor)

    return bool(enter())
