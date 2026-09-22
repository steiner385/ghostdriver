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
There is no longer any exception: `WM_SETTEXT` was the one call here that
had to be sent, and it is gone.

**Nothing sets text programmatically.** `WM_SETTEXT` was removed rather than
kept as a fast path. Measured, it bought about twelve milliseconds on a
twenty-character field -- against a settle of two hundred and fifty -- while
costing a silent split between what a control displays and what the
application accepted. It also produces no input events at all, which is the
most detectable thing this module could do on a target that watches for
automation. A rung that can only tie or lose is not worth the hazard.

**Typing is paced.** Posted characters land about 0.6ms apart, a rate no
person types at. Where a target looks, `cadence` puts human gaps between
them; see `ghostdriver.cadence`. The messages are identical either way --
only the timing changes.

**And shaped as far as a posted message can be.** Keyboard messages carry
the hardware scan code of the key pressed, and a release carries the
previous-state and transition bits; everything here used to send zero and
one, which is not what any keyboard produces. Measured against what Windows
itself puts in the field, and now matched.

Two parts of the gap remain, both deliberately. A real keystroke arrives as
`WM_KEYDOWN` then `WM_CHAR` then `WM_KEYUP`; posting the triple ourselves
double-types, because the target's own `TranslateMessage` synthesises the
`WM_CHAR` from the `WM_KEYDOWN` -- and letting it do so makes uppercase and
symbols depend on a shift state that cannot be set from outside the target's
thread. And `GetAsyncKeyState` never moves for a posted message at all,
which no amount of care at this tier can change. Both are left until there
is a target that demonstrably inspects them, because neither can be
validated against anything else.

**A click is a move, then the pair.** Every click a person makes arrives
after a `WM_MOUSEMOVE` at the same point, and a toolkit's hot and
mouse-in-control state is set from that message before the button ever
goes down. The pair used to be posted bare; a control that gates its click
on that state ignored it (D#69). The move is posted, like everything else
here: it carries the point in the message and moves nothing on screen.

Nothing here moves the cursor or touches the foreground.
"""

import ctypes
import random
import time
from collections.abc import Callable
from ctypes import wintypes

from ...cadence import ROBOT, Cadence
from . import winapi

user32 = winapi.user32

WM_MOUSEMOVE = 0x0200
#: The VCL's private "the mouse entered you" notification (CM_BASE + 19).
#: A VCL control's belief that the mouse is over it is set by the
#: application on idle from the real cursor, not from mouse messages, and
#: delivered as this; a control that acts on a click only in that state
#: has to be told first (#133). Only posted where asked for -- the value
#: is in the WM_APP range, and another toolkit could mean something else
#: by it.
CM_MOUSEENTER = 0xB013
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
#: The double-click message of each button is its down message + 2.
DBLCLK_OFFSET = 2
WM_CHAR = 0x0102
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SETFOCUS = 0x0007
EM_SETSEL = 0x00B1
#: Replace the selection with a string: the paste without the clipboard.
#: One of the few messages whose string the system marshals across
#: processes, which is what makes it deliverable from here (D70).
EM_REPLACESEL = 0x00C2
WM_CLEAR = 0x0303
WM_CUT = 0x0300
WM_COPY = 0x0301
WM_PASTE = 0x0302
WM_UNDO = 0x0304

#: Editing actions a control performs on a message, not a keystroke. The
#: way past the modifier problem: a posted Ctrl+V carries no Ctrl, but
#: WM_PASTE is what Ctrl+V becomes inside an edit control anyway.
EDIT_ACTIONS = {"paste": WM_PASTE, "copy": WM_COPY, "cut": WM_CUT, "undo": WM_UNDO,
                "select-all": EM_SETSEL}

MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002
MK_SHIFT = 0x0004
MK_CONTROL = 0x0008
MK_MBUTTON = 0x0010

#: Mouse buttons a click can use, and the message pair each sends.
BUTTONS = {
    "left": (WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON),
    "right": (WM_RBUTTONDOWN, WM_RBUTTONUP, MK_RBUTTON),
    "middle": (WM_MBUTTONDOWN, WM_MBUTTONUP, MK_MBUTTON),
}
#: Modifiers a click can claim. Carried in the message's own flags, which is
#: the only place a posted message can carry them: the real keyboard is
#: not pressed, so a target that asks GetKeyState sees nothing. A target
#: that reads the flags -- a VCL application does -- sees the modifier.
MODIFIERS = {"ctrl": MK_CONTROL, "control": MK_CONTROL, "shift": MK_SHIFT}

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
    # Caret movement: what clears a field in a host that ignores the
    # edit-control selection messages (an embedded web engine does).
    # Named keys carry nothing, so they are allowed where characters
    # are refused.
    "home": 0x24, "end": 0x23, "left": 0x25, "up": 0x26, "right": 0x27,
    "down": 0x28, "pageup": 0x21, "pagedown": 0x22, "insert": 0x2D,
    # The function keys: f4 opens a combo's list, f2 a grid cell's editor,
    # on most toolkits (#195). Named keys carry nothing.
    **{f"f{n}": 0x6F + n for n in range(1, 13)},
}

user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND,
                                 ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.restype = wintypes.BOOL


MAPVK_VK_TO_VSC = 0

user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
user32.VkKeyScanW.restype = ctypes.c_short


def _scan_code(character: str) -> int:
    """The scan code a keyboard would produce for `character`.

    Real keyboard messages carry the hardware scan code of the key pressed.
    Everything posted here carried zero, which is not a value any keyboard
    produces -- a free tell for any target that looks, measured against what
    Windows itself puts in the field.

    Zero when the character has no key on the current layout. That is the
    honest answer: there is no scan code for a character nobody can type,
    and inventing one would be worse than admitting it.
    """
    vk = user32.VkKeyScanW(character)
    if vk == -1:
        return 0
    return user32.MapVirtualKeyW(vk & 0xFF, MAPVK_VK_TO_VSC)


def _key_lparam(scan: int, *, released: bool = False) -> int:
    """The lParam a keyboard message carries.

    Repeat count 1, the scan code, and on a release the previous-state and
    transition bits set -- which is what says "this key was down and is now
    coming up" rather than "a key changed somehow".
    """
    value = (scan << 16) | 1
    if released:
        value |= (1 << 30) | (1 << 31)
    return value


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


def button_pair(button: str = "left", modifiers=()) -> tuple[int, int, int, int]:
    """(down message, up message, down flags, up flags) for a click.

    Raises ValueError for a button or modifier this cannot send, so a tool
    refuses by name rather than posting the wrong message.
    """
    try:
        down_msg, up_msg, button_flag = BUTTONS[button]
    except KeyError:
        raise ValueError(f"unknown mouse button {button!r}; expected one of "
                         f"{sorted(BUTTONS)}") from None
    flags = 0
    for name in modifiers:
        try:
            flags |= MODIFIERS[name.lower()]
        except KeyError:
            raise ValueError(f"unknown modifier {name!r}; expected one of "
                             f"{sorted(MODIFIERS)}") from None
    return down_msg, up_msg, flags | button_flag, flags


def client_size(hwnd: int) -> tuple[int, int]:
    rect = wintypes.RECT()
    if not user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return 0, 0
    return rect.right - rect.left, rect.bottom - rect.top


def post_click(hwnd: int, x: int, y: int, *, button: str = "left", modifiers=(),
               count: int = 1, hover: bool = False) -> bool:
    """A mouse-move to client point (x, y), then the button pair there,
    `count` times.

    The move first, because that is what a pointer does before a button
    goes down, and a toolkit sets its hot state from it (D#69). It carries
    the modifier flags and no button, which is the state of the mouse the
    instant before the press.

    A second click is the double-click message the window would receive
    from a person: down, up, then the button's DBLCLK and another up. The
    message is posted whether or not the class asked for double-clicks,
    because a control that handles it handles it, and one that does not
    sees two clicks -- which is what a person would have delivered too.
    """
    down_msg, up_msg, down_flags, up_flags = button_pair(button, modifiers)
    point = _lparam_for_point(x, y)
    target = wintypes.HWND(hwnd)
    ok = True
    if hover:
        # Before the move: the control must already believe the mouse is
        # over it when the pair arrives (#133).
        ok = bool(user32.PostMessageW(target, CM_MOUSEENTER, 0, 0))
    ok &= bool(user32.PostMessageW(target, WM_MOUSEMOVE, up_flags, point))
    ok &= bool(user32.PostMessageW(target, down_msg, down_flags, point))
    ok &= bool(user32.PostMessageW(target, up_msg, up_flags, point))
    if count >= 2:
        ok &= bool(user32.PostMessageW(target, down_msg + DBLCLK_OFFSET, down_flags, point))
        ok &= bool(user32.PostMessageW(target, up_msg, up_flags, point))
    return ok


def click(hwnd: int, *, button: str = "left", modifiers=(), at=None,
          count: int = 1, hover: bool = False) -> bool:
    """Press and release a button over `hwnd`: at its middle, or at `at`.

    The pair, not just the down: a toolkit decides a click happened on the
    *up*, having seen the down, and half of it leaves a control stuck
    looking pressed. Modifiers ride in the message flags (see MODIFIERS).
    `at` is a client-relative (x, y): the way into a region that paints its
    own rows and exposes none of them -- a capture says where the row is,
    and this clicks there, still without activating anything.
    """
    x, y = client_centre(hwnd) if at is None else client_point(hwnd, at)
    target, tx, ty = deepest_child_at(hwnd, x, y)
    return post_click(target, tx, ty, button=button, modifiers=modifiers, count=count,
                      hover=hover)


def client_offset(hwnd: int) -> tuple[int, int]:
    """Where the client area starts inside the window rectangle: (0, 0) for
    a child control, the frame and title bar for a top-level window."""
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(origin))
    left, top, _right, _bottom = winapi.window_rect(hwnd)
    return (origin.x - left, origin.y - top)


def client_point(hwnd: int, at) -> tuple[int, int]:
    """`at`, given from the window's top-left as `find` reports it and a
    capture of it shows, as the client point the message needs.

    They differ by the frame: a dialog's client area starts below its title
    bar, so an offset measured on a dialog's capture landed ~30px low when
    it was handed over as a client point (#203). A child control has no
    frame, which is why the same `at` was right there and wrong on a
    top-level window."""
    dx, dy = client_offset(hwnd)
    return (int(at[0]) - dx, int(at[1]) - dy)


#: `ChildWindowFromPointEx` flags: skip children that are hidden, or that
#: let the mouse through (WS_EX_TRANSPARENT).
CWP_SKIPINVISIBLE = 0x0001
CWP_SKIPTRANSPARENT = 0x0004
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.ChildWindowFromPointEx.argtypes = [wintypes.HWND, wintypes.POINT, wintypes.UINT]
user32.ChildWindowFromPointEx.restype = wintypes.HWND


def deepest_child_at(hwnd: int, x: int, y: int) -> tuple[int, int, int]:
    """The innermost visible child window under client point (x, y) of
    `hwnd`, with the point in that window's own client coordinates.

    A click posted to a panel over a *windowed* child is dropped: the
    panel's toolkit hands mouse messages to its non-windowed children only,
    and a child that is a window of its own never sees a message addressed
    to its parent. Four clicks on a toolbar reported delivered and did
    nothing that way (D66). A person's click goes to the window under the
    pointer; so does this. (`hwnd`, x, y) comes back when nothing is under
    the point but `hwnd` itself.
    """
    current, cx, cy = hwnd, x, y
    for _ in range(32):  # a window tree is not that deep; a loop here is a bug
        child = user32.ChildWindowFromPointEx(
            wintypes.HWND(current), wintypes.POINT(cx, cy),
            CWP_SKIPINVISIBLE | CWP_SKIPTRANSPARENT)
        if not child or child == current:
            break
        point = wintypes.POINT(cx, cy)
        user32.ClientToScreen(wintypes.HWND(current), ctypes.byref(point))
        user32.ScreenToClient(wintypes.HWND(child), ctypes.byref(point))
        current, cx, cy = int(child), point.x, point.y
    return current, cx, cy


def set_text_by_typing(
    hwnd: int,
    text: str,
    *,
    cadence: Cadence = ROBOT,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
) -> bool:
    """Replace a control's text one character at a time.

    The only way this module sets text, and correct more often than any
    programmatic alternative. Every character travels the toolkit's own
    keyboard path, so whatever a toolkit does on keystrokes -- validate,
    reformat, commit to a bound field, refuse past a length limit -- happens
    exactly as it would for a person.

    That last one is worth stating plainly, because it looks like a bug and
    is not: a single-line field without ES_AUTOHSCROLL stops accepting
    keystrokes at its visible width, so a long value arrives truncated.
    Measured at about twenty characters on a field whose declared limit is
    thirty thousand. Being subject to the control's input handling is the
    same property that makes a bound value commit; a driver that widened the
    field to get the whole string in would be changing the target to make
    its own action succeed. Read the value back instead.

    Clearing first through the control's own selection messages rather than
    by sending backspaces: a field with a length limit or an input mask can
    swallow backspaces in ways that leave residue.

    `cadence` spaces the characters. The default sends them as fast as the
    queue takes them, which is roughly 0.6ms apart and unmistakably not a
    person.
    """
    ok = user32.PostMessageW(wintypes.HWND(hwnd), EM_SETSEL, 0, -1)
    ok = user32.PostMessageW(wintypes.HWND(hwnd), WM_CLEAR, 0, 0) and ok
    for character, pause in zip(text, cadence.delays(text, rng), strict=True):
        if pause:
            sleep(pause)
        ok = user32.PostMessageW(
            wintypes.HWND(hwnd), WM_CHAR, ord(character),
            _key_lparam(_scan_code(character)),
        ) and ok
    return bool(ok)


def send_keys(
    hwnd: int,
    keys: list[str],
    *,
    cadence: Cadence = ROBOT,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
) -> bool:
    """Send a sequence of keystrokes.

    A named key goes as a down/up pair, because its meaning lives in the
    virtual-key code and a toolkit acts on the keydown. A single character
    goes as `WM_CHAR`, because that is what the system would synthesise for
    it and what a text control listens for.

    Paced like typing, and for the same reason: a burst of keystrokes at
    queue speed is as much of a tell as a burst of characters. The gaps are
    computed over the number of keys, so a named key counts as one keystroke
    rather than as the length of its name.
    """
    ok = True
    for key, pause in zip(keys, cadence.delays("k" * len(keys), rng), strict=True):
        if pause:
            sleep(pause)
        lowered = key.lower()
        if lowered in EDIT_ACTIONS:
            if lowered == "select-all":
                ok = user32.PostMessageW(wintypes.HWND(hwnd), EM_SETSEL, 0, -1) and ok
            else:
                ok = user32.PostMessageW(wintypes.HWND(hwnd), EDIT_ACTIONS[lowered], 0, 0) and ok
        elif lowered in NAMED_KEYS:
            code = NAMED_KEYS[lowered]
            scan = user32.MapVirtualKeyW(code, MAPVK_VK_TO_VSC)
            ok = user32.PostMessageW(
                wintypes.HWND(hwnd), WM_KEYDOWN, code,
                _key_lparam(scan)) and ok
            ok = user32.PostMessageW(
                wintypes.HWND(hwnd), WM_KEYUP, code,
                _key_lparam(scan, released=True)) and ok
        elif len(key) == 1:
            ok = user32.PostMessageW(
                wintypes.HWND(hwnd), WM_CHAR, ord(key),
                _key_lparam(_scan_code(key))) and ok
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


def insert_text(hwnd: int, text: str, *, settle_s: float = 0.15,
                timeout_ms: int = 2000) -> bool:
    """Replace a control's text with `text` in one message, through the
    control's own edit path, touching nothing shared.

    Atomic where typing is not: a control that drops a character now and
    then -- measured on an address field that lost `N`, `@`, `ht` and
    `ch` across six attempts at two cadences -- cannot lose part of a value
    that arrives whole. The earlier form of this rung put the value on the
    clipboard and pasted; the clipboard is the person's, and taking it
    even for a moment is a disruption they notice (D70). EM_REPLACESEL is
    the paste without the clipboard: the edit control inserts the string
    at the selection exactly as it would a paste, and the system marshals
    the string across the process boundary. Select-all first, so the
    insert replaces rather than appends.
    """
    from .winapi import send_message_timeout

    # Sent, not posted, and before the replace: a posted select-all can be
    # processed after a sent replace, which then inserts at the caret and
    # appends -- measured as 'INSERTED-0001plain text' under load (D70).
    send_message_timeout(hwnd, EM_SETSEL, 0, -1, timeout_ms=timeout_ms)
    buffer = ctypes.create_unicode_buffer(text)
    answered = send_message_timeout(hwnd, EM_REPLACESEL, 1, ctypes.addressof(buffer),
                                    timeout_ms=timeout_ms)
    time.sleep(settle_s)
    return answered is not None
