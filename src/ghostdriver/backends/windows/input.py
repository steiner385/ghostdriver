"""Actuation primitives: the messages, and nothing above them.

Each function here does one thing to one window and reports whether the
send itself succeeded. None of them decides whether it *worked* -- that is a
postcondition's job, and the distinction matters because almost every
primitive here can succeed at delivering a message that the target then
ignores.

**Input-shaped, not semantic.** `BM_CLICK` is implemented by the BUTTON
class and discarded by anything else, so a vendor class that never
registered as a BUTTON silently swallows it. `WM_LBUTTONDOWN`/`UP` only
assume the toolkit handles mouse input, which any toolkit does. Measured on
both a real Profile L1 client and the fixture: the semantic message returns
success and changes nothing; the input pair actuates.

**Posted, not sent.** Real input arrives on the queue, and a target that is
busy or showing a modal must not block the caller. `SendMessage` into a hung
window blocks the sender too, which is how an automation run stops dead.

The one exception is `WM_SETTEXT`, and it is not a preference. Its lParam is
a pointer, and the system marshals a pointer across a process boundary only
for a *sent* message. Posted, the target receives an address in our address
space and reads whatever happens to be there -- `PostMessage` returns success
and the control does not change. Measured cross-process against the fixture,
which is where it surfaced: in-process it appeared to work. So that one call
is sent, under the same hard timeout every other cross-process read here
uses.

Nothing here moves the cursor or touches the foreground.
"""

import ctypes
from ctypes import wintypes

from . import winapi

user32 = winapi.user32

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_SETTEXT = 0x000C
WM_CHAR = 0x0102
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SETFOCUS = 0x0007
EM_SETSEL = 0x00B1
WM_CLEAR = 0x0303

MK_LBUTTON = 0x0001

#: How long to wait for a target to accept a `WM_SETTEXT`. Longer than a
#: read, because this one asks the target to change something and a busy
#: application is not the same as a hung one; short enough that a hung one
#: costs a fifth of a second rather than the run.
SET_TEXT_TIMEOUT_MS = 500

VK_RETURN = 0x0D
VK_TAB = 0x09
VK_ESCAPE = 0x1B
VK_BACK = 0x08
VK_DELETE = 0x2E

#: Key names a caller can use in `send_keys`, mapped to virtual-key codes.
#: Deliberately small: every one of these is a key whose *effect* a toolkit
#: implements, which is what makes it worth sending as a key rather than as
#: a character.
NAMED_KEYS = {
    "enter": VK_RETURN, "return": VK_RETURN, "tab": VK_TAB,
    "escape": VK_ESCAPE, "esc": VK_ESCAPE,
    "backspace": VK_BACK, "delete": VK_DELETE,
}

user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND,
                                 ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.restype = wintypes.BOOL


def _lparam_for_point(x: int, y: int) -> int:
    """Pack a client-relative point the way a mouse message carries one."""
    return (y << 16) | (x & 0xFFFF)


def client_centre(hwnd: int) -> tuple[int, int]:
    """The middle of a window's client area, in client coordinates.

    Client-relative on purpose. A screen coordinate would have to be
    converted, and on a DPI-virtualized target that conversion is exactly
    where the answer goes wrong.
    """
    rect = wintypes.RECT()
    if not user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return 0, 0
    return (rect.right - rect.left) // 2, (rect.bottom - rect.top) // 2


def click(hwnd: int) -> bool:
    """Press and release the left button over the middle of `hwnd`.

    The pair, not just the down: a toolkit decides a click happened on the
    *up*, having seen the down, and half of it leaves a control stuck
    looking pressed.
    """
    x, y = client_centre(hwnd)
    point = _lparam_for_point(x, y)
    down = user32.PostMessageW(wintypes.HWND(hwnd), WM_LBUTTONDOWN,
                               MK_LBUTTON, point)
    up = user32.PostMessageW(wintypes.HWND(hwnd), WM_LBUTTONUP, 0, point)
    return bool(down and up)


def set_text_by_message(hwnd: int, text: str) -> bool:
    """Replace a control's text with `WM_SETTEXT`.

    The fast path, and the unsafe one. It replaces what the control
    *displays* without the toolkit's keyboard path ever running, so a
    data-bound field can end up showing one value while the application
    still holds another. Verified against the fixture, which reproduces
    exactly that. Never the default; offered because it is enormously
    faster for the many controls where nothing is bound behind them.
    """
    buffer = ctypes.create_unicode_buffer(text)
    # Sent, not posted, because the pointer below is only marshalled across
    # the process boundary for a sent message -- see the module docstring.
    # The timeout is what keeps that from being the blocking call the rest
    # of this module avoids.
    result = winapi.send_message_timeout(
        hwnd, WM_SETTEXT, 0, ctypes.cast(buffer, ctypes.c_void_p).value,
        timeout_ms=SET_TEXT_TIMEOUT_MS,
    )
    return result is not None


def set_text_by_typing(hwnd: int, text: str) -> bool:
    """Replace a control's text one character at a time.

    Slower, and correct more often. Every character travels the toolkit's
    own keyboard path, so whatever a toolkit does on keystrokes -- validate,
    reformat, commit to a bound field -- happens exactly as it would for a
    person. That is why this is the default.

    Clearing first through the control's own selection messages rather than
    by sending backspaces: a field with a length limit or an input mask can
    swallow backspaces in ways that leave residue.
    """
    ok = user32.PostMessageW(wintypes.HWND(hwnd), EM_SETSEL, 0, -1)
    ok = user32.PostMessageW(wintypes.HWND(hwnd), WM_CLEAR, 0, 0) and ok
    for character in text:
        ok = user32.PostMessageW(
            wintypes.HWND(hwnd), WM_CHAR, ord(character), 1
        ) and ok
    return bool(ok)


def send_keys(hwnd: int, keys: list[str]) -> bool:
    """Send a sequence of keystrokes.

    A named key goes as a down/up pair, because its meaning lives in the
    virtual-key code and a toolkit acts on the keydown. A single character
    goes as `WM_CHAR`, because that is what the system would synthesise for
    it and what a text control listens for.
    """
    ok = True
    for key in keys:
        lowered = key.lower()
        if lowered in NAMED_KEYS:
            code = NAMED_KEYS[lowered]
            ok = user32.PostMessageW(
                wintypes.HWND(hwnd), WM_KEYDOWN, code, 1) and ok
            ok = user32.PostMessageW(
                wintypes.HWND(hwnd), WM_KEYUP, code, 1) and ok
        elif len(key) == 1:
            ok = user32.PostMessageW(
                wintypes.HWND(hwnd), WM_CHAR, ord(key), 1) and ok
        else:
            return False
    return bool(ok)


def invoke_via_uia(hwnd: int) -> bool:
    """Actuate through a UIA pattern, when the target provides one.

    Tier 1 of the ladder. Almost nothing on a Profile L1 target answers
    here, which is the whole reason the lower tiers exist -- but a target
    that does answer should be driven through the surface it publishes
    rather than by messages aimed at its window.
    """
    try:
        import comtypes
        import comtypes.client

        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA
    except Exception:
        return False

    try:
        comtypes.CoInitialize()
        iuia = comtypes.client.CreateObject(
            UIA.CUIAutomation, interface=UIA.IUIAutomation
        )
        element = iuia.ElementFromHandle(wintypes.HWND(hwnd))
        if not element:
            return False
        pattern = element.GetCurrentPattern(UIA.UIA_InvokePatternId)
        if not pattern:
            return False
        pattern.QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
        return True
    except Exception:
        return False


def set_value_via_uia(hwnd: int, text: str) -> bool:
    """Set a value through a UIA pattern, when the target provides one."""
    try:
        import comtypes
        import comtypes.client

        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA
    except Exception:
        return False

    try:
        comtypes.CoInitialize()
        iuia = comtypes.client.CreateObject(
            UIA.CUIAutomation, interface=UIA.IUIAutomation
        )
        element = iuia.ElementFromHandle(wintypes.HWND(hwnd))
        if not element:
            return False
        pattern = element.GetCurrentPattern(UIA.UIA_ValuePatternId)
        if not pattern:
            return False
        pattern.QueryInterface(UIA.IUIAutomationValuePattern).SetValue(text)
        return True
    except Exception:
        return False
