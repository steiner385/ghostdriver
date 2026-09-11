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


def confirms_value(hwnd: int, expected: str) -> bool | None:
    """Whether the control currently shows `expected`, without disclosing it.

    The contract's shared shape (D#105). Windows never withholds -- the OS
    refuses a cross-process read of a password field, so there is nothing to
    protect in software -- so this is a plain compare of the read text, and
    `None` means the control did not answer (a hung control, D4), which is
    neither a match nor a mismatch. A password field reads as not-answering
    cross-process, so it confirms nothing, which is the safe direction.
    """
    seen = read_window_text(hwnd)
    if seen is None:
        return None
    return seen == expected


def read_window_text(hwnd: int, timeout_ms: int = 200, *,
                     disclose: bool = False) -> str | None:
    """Return the control's text.

    Returns "" when the control answered and has no text, and None when it
    did not answer at all. Callers must not collapse the two: "no caption"
    and "target is not responding" are different facts.

    **`disclose` is accepted and has no effect here, deliberately.** This
    platform never withholds: the OS itself refuses a cross-process
    `WM_GETTEXT` on a password field, so a value that must be protected is
    not available to hand over and there is nothing to opt into. Linux has
    to withhold in software, because a hidden entry is indistinguishable
    from a plain one by inspection (D#34b), and the opt-in exists for it.

    Kept in the signature rather than pushed onto the caller, because the
    tool layer is platform-neutral (D59) and must not have to know which
    backend it is talking to. `disclosure()` is the name that reports the
    difference where a caller needs it (D#43).
    """
    del disclose
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


def disclosure(hwnd: int) -> str:
    """Why a read of this control may come back empty-handed: the third state.

    `read_window_text` returns `str | None`, and `None` has to carry every
    empty-handed outcome. Here there are two -- the control did not answer,
    or the OS protects it -- and `is_protected` has always separated them
    (D37). On Linux there is a third, because a driver that cannot tell a
    hidden entry from a plain one declines to look at either (D#34b), and
    without a name for it a healthy text field reads exactly like a hung one.

    So the state gets a name rather than borrowing `None`. Three values:

    * `"allowed"` -- the value is returned as read.
    * `"protected"` -- the platform hides it and always will.
    * `"withheld"` -- the driver did not look, and `disclose=True` would
      make it look.

    **This platform never answers `"withheld"`**, and that is the honest
    answer rather than a gap: it does not withhold anything, because it does
    not have to. The OS is fail-closed on the one field that matters.
    """
    return "protected" if is_protected(hwnd) else "allowed"
