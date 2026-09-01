"""Read control text from another process.

GetWindowTextW returns the cached window text and comes back empty for many
cross-process controls. WM_GETTEXT asks the control itself and is the more
reliable read, at the cost of needing a timeout so an unresponsive target
cannot block us.

This is a read-only operation. WM_GETTEXT and WM_GETTEXTLENGTH are the only
messages Iteration 1 is permitted to send.
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
