"""The tier-4 click: real input on the operator's own display, gated hard (#124, D#111).

A control that hit-tests the *real* cursor -- a Delphi panel that asks
`GetCursorPos` rather than reading the message's coordinates -- never sees a
posted click. `delivered_to` names the right window and nothing happens, and
the only thing left is a person's click, which is what this sends: the cursor
placed at the point, the button pressed and released through `SendInput`.
That moves the pointer and needs the window frontmost -- exactly the
interference this project exists to avoid (D9) -- so it is allowed only under
the live grant a session records at attach (D#111):

* the operator named a window of the target that was *already* the
  foreground (`live_window`), so nothing here changes what they are looking
  at, and the control clicked must belong to that window;
* the foreground and the pointer are re-checked before the cursor is placed
  and again before the button goes down, and any change **aborts** -- it is
  reported as a disturbance (D28), never smoothed into a posted click;
* an `InterferenceWatch` is armed around the whole action by the tool layer,
  so a move the guard misses between checks is still seen and reported;
* the pointer is put back where it was afterwards, because the click was the
  tool's and the pointer is the person's.

The guard is a plain function of injected samplers, so its logic is testable
without a desktop. `input.py` keeps its promise ("nothing here moves the
cursor or touches the foreground"); everything that does is in this file.
"""

from __future__ import annotations

import ctypes
import time
from collections.abc import Callable
from ctypes import wintypes

from . import input as win_input
from . import winapi

user32 = winapi.user32

INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040

#: The down/up flag pair for each button a real click can press.
REAL_BUTTONS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long), ("dy", ctypes.c_long),
        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTUNION(ctypes.Union):
    # The keyboard and hardware members are larger than MOUSEINPUT on no
    # platform this runs on; the union is sized by its largest member, and
    # MOUSEINPUT is that member.
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL


def cursor() -> tuple[int, int]:
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return (point.x, point.y)


def place_cursor(x: int, y: int) -> bool:
    """Move the real pointer to screen (x, y), in the frame this process
    sees. This server is not DPI-aware, so that frame is the logical one
    every rect it reports is in -- the same frame `GetCursorPos` answers in.
    Converting to physical pixels first put every click 1.25x off at 125%
    and clamped one at the screen edge (#130)."""
    return bool(user32.SetCursorPos(int(x), int(y)))


def post_at(hwnd: int, point: tuple[int, int], button: str, count: int) -> bool:
    """The ordinary message pair, posted to `hwnd` at screen `point`, while
    the pointer is already there: a control that hit-tests `GetCursorPos`
    while handling the message sees the cursor where the message says."""
    client = winapi.screen_to_client(hwnd, point)
    return bool(win_input.click(hwnd, button=button, at=client, count=count))


#: How far the pointer may read back from where it was placed before that
#: counts as "could not place it" rather than the operator moving it.
PLACEMENT_TOLERANCE = 2
#: How long a raised window is given to become the foreground.
FOREGROUND_SETTLE_S = 0.15


def press_button(button: str, count: int = 1) -> bool:
    """Press and release `button` where the pointer is, `count` times, as
    one SendInput call -- two pairs back to back is what Windows reads as
    a double-click."""
    down, up = REAL_BUTTONS[button]
    events = []
    for _ in range(max(1, count)):
        for flag in (down, up):
            item = INPUT()
            item.type = INPUT_MOUSE
            item.union.mi.dwFlags = flag
            events.append(item)
    array = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
    return sent == len(events)


class LiveActuationAborted(RuntimeError):
    """The operator's desktop moved under a live action, so it was stopped.

    Carries what changed, so the tool can report it as a disturbance rather
    than a bare failure -- the point of the guard is that the operator sees
    why nothing happened.
    """

    def __init__(self, what: str):
        super().__init__(what)
        self.what = what


def _guard(live_window: int, expected_cursor: tuple[int, int],
           foreground: Callable[[], int],
           cursor_now: Callable[[], tuple[int, int]]) -> None:
    """Raise unless the operator's foreground and pointer are where they
    should be. Called before the cursor is placed and before the press."""
    now = foreground()
    if now != live_window:
        raise LiveActuationAborted(
            f"the foreground window changed (expected {live_window:#x}, found "
            f"{now:#x} -- the operator switched away or something raised "
            "itself); nothing was clicked")
    if cursor_now() != expected_cursor:
        raise LiveActuationAborted(
            "the pointer moved while acting; the operator is at the desk, so "
            "the action was stopped before it could interfere")


def click_real(hwnd: int, point: tuple[int, int], *, live_window: int,
               button: str = "left", count: int = 1, via: str = "input",
               foreground: Callable[[], int] = winapi.foreground_window,
               cursor_now: Callable[[], tuple[int, int]] = cursor,
               root: Callable[[int], int] = winapi.root_window,
               raise_window: Callable[[int], bool] = winapi.bring_foreground,
               settle: Callable[[float], None] = time.sleep,
               place: Callable[[int, int], bool] = place_cursor,
               press: Callable[[str, int], bool] = press_button,
               post: Callable[[int, tuple[int, int], str, int], bool] = post_at) -> bool:
    """A click at screen `point` with the real pointer there, on a control of
    the live window.

    `via` is the route: "posted" places the pointer and posts the ordinary
    message pair to the control -- enough for a hit-test on `GetCursorPos`,
    no button event through the input queue, no foreground needed; "input"
    presses a real button through `SendInput`, which does need the window
    frontmost. Either way the pointer is put back afterwards.

    Returns True when the click was sent, and raises `LiveActuationAborted`
    when the operator's desktop moved, the pointer could not be placed, or
    the control is not in the window the operator consented to. Every
    refusal names its reason: a rung that declined silently reads as "the
    target ignored the click" (#130).
    """
    if live_window == 0:
        raise LiveActuationAborted(
            "no live window was consented at attach, so real input may not be "
            "sent on the operator's display")
    if button not in REAL_BUTTONS:
        raise LiveActuationAborted(f"real input has no {button!r} button")
    if via not in ("posted", "input"):
        raise LiveActuationAborted(f"no real-input route named {via!r}")
    owner = root(hwnd)
    if owner != live_window:
        raise LiveActuationAborted(
            f"the control belongs to window {owner:#x}, not the live window "
            f"{live_window:#x} the operator consented to; nothing was clicked")

    if via == "input":
        # The window the operator consented to may have lost the foreground
        # to the chat they typed the go-ahead in (#130). It is the window
        # they named, so it is brought back rather than refused -- and if it
        # cannot be, that is said.
        now = foreground()
        if now != live_window:
            raise_window(live_window)
            settle(FOREGROUND_SETTLE_S)
            now = foreground()
            if now != live_window:
                raise LiveActuationAborted(
                    f"the live window {live_window:#x} could not be brought to the "
                    f"front (the foreground is {now:#x}); a real button press needs "
                    "it frontmost, so nothing was clicked")

    baseline = cursor_now()
    if cursor_now() != baseline:
        raise LiveActuationAborted(
            "the pointer is moving; the operator is at the desk, so nothing was "
            "sent")

    x, y = int(point[0]), int(point[1])
    if not place(x, y):
        raise LiveActuationAborted(f"SetCursorPos refused to place the pointer at {(x, y)}")
    placed = cursor_now()
    if max(abs(placed[0] - x), abs(placed[1] - y)) > PLACEMENT_TOLERANCE:
        place(*baseline)
        raise LiveActuationAborted(
            f"the pointer could not be placed at {(x, y)}: it read back at {placed} "
            "-- a screen edge clamped it, or the point is in another frame; nothing "
            "was clicked")
    # The pointer is now ours, where it read back: a further move is the
    # person's. Only the real button press needs the foreground.
    if via == "input":
        _guard(live_window, placed, foreground, cursor_now)
        sent = bool(press(button, count))
    else:
        if cursor_now() != placed:
            place(*baseline)
            raise LiveActuationAborted(
                "the pointer moved while acting; the operator is at the desk, so "
                "the action was stopped before it could interfere")
        sent = bool(post(hwnd, (x, y), button, count))
    place(*baseline)  # the click was the tool's; the pointer is the person's
    return sent
