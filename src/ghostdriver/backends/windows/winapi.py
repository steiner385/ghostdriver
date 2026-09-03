"""ctypes declarations for the Windows backend.

This is the only place Win32 constants and signatures live. argtypes and
restype are set explicitly on every function: without them ctypes truncates
64-bit pointers to int, which produces silent wrong answers rather than
errors.
"""

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t

# Read-only messages. Iteration 1 must never send anything else.
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E

SMTO_ABORTIFHUNG = 0x0002

GW_CHILD = 5
GW_HWNDNEXT = 2
#: The window that owns this one. Distinct from a parent: an owned window is
#: top-level, appears in EnumWindows, and is what a modal dialog is.
GW_OWNER = 4

# Window-manager state, read and (only by the `restore` command) written.
#
# ShowWindow is not a message send: it asks the window manager to change a
# window's show state, and no WM_* reaches the target's controls because of
# it. That distinction is what keeps the read-only guarantee above intact --
# `restore` is the one command permitted to change on-screen state, and even
# it never sends a message a control could act on.
GWL_STYLE = -16
WS_VISIBLE = 0x10000000
WS_MINIMIZE = 0x20000000

# Restores a minimized window *without* activating it. SW_RESTORE would do
# the same job and take the foreground with it, which is the one outcome a
# non-interfering driver must not cause.
SW_SHOWNOACTIVATE = 4

# Minimizes a window *without* activating whatever is behind it. Plain
# SW_MINIMIZE activates the next window in Z-order, which on a shared
# desktop is whatever the person was using -- the watchdog putting the
# target away must not shuffle their windows to do it.
SW_SHOWMINNOACTIVE = 7

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

WNDENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
)

user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL

user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND

user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int

user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL

user32.IsWindowEnabled.argtypes = [wintypes.HWND]
user32.IsWindowEnabled.restype = wintypes.BOOL

user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL

user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL

user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL

# GWL_STYLE is a 32-bit value on every architecture, so GetWindowLongW is
# the right call even on 64-bit; c_long states that the result is signed and
# must not be widened.
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long

user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND

user32.GetWindowThreadProcessId.argtypes = [
    wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
]
user32.SendMessageTimeoutW.restype = LRESULT

# kernel32 handle-returning calls need explicit restype: without it ctypes
# assumes c_int and silently truncates a 64-bit HANDLE, which fails as a
# wrong answer rather than as an error.
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

kernel32.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
kernel32.IsWow64Process.restype = wintypes.BOOL


def owner_window(hwnd: int) -> int:
    """The window that owns `hwnd`, or 0.

    Ownership is the relationship a modal dialog has to the window it
    blocks, and it is not visible in a parent/child walk: an owned window
    is itself top-level.
    """
    return user32.GetWindow(wintypes.HWND(hwnd), GW_OWNER) or 0


def window_style(hwnd: int) -> int:
    """The window's style bits, as an unsigned 32-bit value."""
    return user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE) & 0xFFFFFFFF


def is_minimized(hwnd: int) -> bool:
    return bool(window_style(hwnd) & WS_MINIMIZE)


def is_visible_style(hwnd: int) -> bool:
    """WS_VISIBLE on this window alone, ignoring its ancestors.

    IsWindowVisible answers for the whole chain, which is the right question
    for a control and the wrong one for a top-level window whose owner is
    minimized.
    """
    return bool(window_style(hwnd) & WS_VISIBLE)


def foreground_window() -> int:
    return user32.GetForegroundWindow() or 0


def show_no_activate(hwnd: int) -> None:
    """Restore `hwnd` from minimized without giving it the foreground."""
    user32.ShowWindow(wintypes.HWND(hwnd), SW_SHOWNOACTIVATE)


def minimize_no_activate(hwnd: int) -> None:
    """Minimize `hwnd` without activating whatever sits behind it."""
    user32.ShowWindow(wintypes.HWND(hwnd), SW_SHOWMINNOACTIVE)


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return pid.value


def class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(wintypes.HWND(hwnd), buf, 256)
    return buf.value


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return (0, 0, 0, 0)
    return (rect.left, rect.top, rect.right, rect.bottom)


def send_message_timeout(
    hwnd: int, msg: int, wparam: int, lparam: int, timeout_ms: int = 200
) -> int | None:
    """Send a message with a hard timeout.

    Returns the message result, or None if the target did not answer.
    SMTO_ABORTIFHUNG is mandatory: a target that has stopped pumping
    messages must not be able to block the tool indefinitely.
    """
    out = ctypes.c_size_t()
    ok = user32.SendMessageTimeoutW(
        wintypes.HWND(hwnd), msg, wparam, lparam,
        SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(out),
    )
    if not ok:
        return None
    return out.value

# Toolhelp: one snapshot of the process list, for the process tree.
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.Process32FirstW.restype = wintypes.BOOL
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.Process32NextW.restype = wintypes.BOOL
