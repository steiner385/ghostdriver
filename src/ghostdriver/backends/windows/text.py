"""Read control text from another process.

GetWindowTextW returns the cached window text and comes back empty for many
cross-process controls. WM_GETTEXT asks the control itself and is the more
reliable read, at the cost of needing a timeout so an unresponsive target
cannot block us.

These are read-only operations. WM_GETTEXT and WM_GETTEXTLENGTH ask a
control for its text; EM_GETPASSWORDCHAR asks whether it hides it. None of
them changes anything, which is what lets them run at the read-only tier.
"""

from . import winapi


def read_window_text(hwnd: int, timeout_ms: int = 200) -> str | None:
    """Return the control's text.

    Returns "" when the control answered and has no text, and None when it
    did not answer at all. Callers must not collapse the two: "no caption"
    and "target is not responding" are different facts.
    """
    length = winapi.send_message_timeout(
        hwnd, winapi.WM_GETTEXTLENGTH, 0, 0, timeout_ms
    )
    if length is None:
        return None
    if length <= 0:
        return ""

    import ctypes

    buf = ctypes.create_unicode_buffer(length + 1)
    result = winapi.send_message_timeout(
        hwnd,
        winapi.WM_GETTEXT,
        length + 1,
        ctypes.cast(buf, ctypes.c_void_p).value or 0,
        timeout_ms,
    )
    if result is None:
        return None
    return buf.value


#: Asks a control which character it paints instead of its contents. Only
#: EDIT-derived windows implement it; everything else lets DefWindowProc
#: answer 0. That makes it a better test than the style bit, which is
#: ES_PASSWORD only on an EDIT -- 0x0020 means something else entirely on
#: another class, and a superclassed field keeps its vendor class name, so
#: there is no way to know from the name whether to read the bit that way.
EM_GETPASSWORDCHAR = 0x00D2


def is_protected(hwnd: int) -> bool:
    """Whether this control hides its own contents.

    Measured, and the reason this exists: Windows refuses a cross-process
    `WM_GETTEXT` on a password field, so the read comes back with no answer
    -- which is indistinguishable from a control that never replied. One is
    a target that has stopped pumping messages and the other is a field
    working exactly as designed, and telling a caller the wrong one sends
    them to diagnose a hang that is not happening.
    """
    return bool(winapi.send_message_timeout(hwnd, EM_GETPASSWORDCHAR, 0, 0))
