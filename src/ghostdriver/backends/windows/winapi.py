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

user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND

# WindowFromPoint takes a POINT by value and returns the top-level or child
# window under that screen point -- the z-order question, which GetWindowRect
# cannot answer. Used to tell an occluded window from a visible one.
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND

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


def resolve_live_window(pid: int) -> int:
    """The window to drive live, if the target is the foreground now (D#111).

    Windows does not *need* a live path -- posted messages reach a background
    window without taking the operator's focus -- so this exists for contract
    symmetry and answers honestly: the foreground window when it belongs to
    `pid`, else 0. A caller that never opens a live session never reaches it.
    """
    hwnd = foreground_window()
    return hwnd if hwnd and window_pid(hwnd) == pid else 0


def show_no_activate(hwnd: int) -> None:
    """Restore `hwnd` from minimized without giving it the foreground."""
    user32.ShowWindow(wintypes.HWND(hwnd), SW_SHOWNOACTIVATE)


def minimize_no_activate(hwnd: int) -> None:
    """Minimize `hwnd` without activating whatever sits behind it."""
    user32.ShowWindow(wintypes.HWND(hwnd), SW_SHOWMINNOACTIVE)


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
user32.GetGUIThreadInfo.restype = wintypes.BOOL
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
GA_ROOT = 2


def thread_gui_state(hwnd: int) -> dict:
    """The active, focused and capturing windows of the thread that owns
    `hwnd`, read with GetGUIThreadInfo: no message, no activation.

    The three are per thread, not per system. Measured: a window shown
    without activation is still its thread's active window, and a second
    top-level window of the same thread need not be -- which is what a
    control that checks before acting on a click sees (D64). Read, never
    assumed.
    """
    thread = user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), None)
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    if not thread or not user32.GetGUIThreadInfo(thread, ctypes.byref(info)):
        return {"active": None, "focus": None, "capture": None}
    return {"active": info.hwndActive or None, "focus": info.hwndFocus or None,
            "capture": info.hwndCapture or None}


def root_window(hwnd: int) -> int:
    """The top-level window `hwnd` belongs to (itself, when it is one)."""
    return user32.GetAncestor(wintypes.HWND(hwnd), GA_ROOT) or hwnd


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


def window_from_point(x: int, y: int) -> int:
    """The window sitting at screen point (x, y) in the current z-order, or 0.

    This is what a real click at that pixel would hit -- so if it is not the
    window a caller means to drive (nor a descendant of it), that window is
    covered there. A read of the desktop's z-order; it moves nothing."""
    return user32.WindowFromPoint(wintypes.POINT(x, y)) or 0


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


class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD),
        ("dmPositionX", ctypes.c_long), ("dmPositionY", ctypes.c_long),
        ("dmDisplayOrientation", wintypes.DWORD), ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short), ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD), ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD), ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD), ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD), ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD), ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD), ("dmPanningHeight", wintypes.DWORD),
    ]


user32.EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                        ctypes.POINTER(DEVMODEW)]
user32.EnumDisplaySettingsW.restype = wintypes.BOOL
ENUM_CURRENT_SETTINGS = 0xFFFFFFFF
SM_CXSCREEN = 0


def display_scale() -> float:
    """Physical pixels per pixel of the frame this process sees, on the
    primary display.

    A process that is not DPI-aware sees a display scaled to 96 dpi -- at
    125% a 1920-wide screen is 1536 wide -- while a screenshot from a
    DPI-aware tool is in physical pixels. A session converted between the
    two by hand once; the number belongs in the result (D65). The display
    mode is not virtualized, so the ratio is readable from any process.
    """
    mode = DEVMODEW()
    mode.dmSize = ctypes.sizeof(DEVMODEW)
    logical = user32.GetSystemMetrics(SM_CXSCREEN)
    if not logical or not user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS,
                                                       ctypes.byref(mode)):
        return 1.0
    if not mode.dmPelsWidth:
        return 1.0
    return round(mode.dmPelsWidth / logical, 3)


#: Asked of a `#32768` window: the HMENU it is showing.
MN_GETHMENU = 0x01E1
#: Told to a `#32768` window: highlight item N, as the keyboard would. Not
#: in the SDK headers, but the menu code has answered it for decades and
#: every driver that selects a menu item by position relies on it (#135).
MN_SELECTITEM = 0x01E5
MF_BYPOSITION = 0x0400
MF_SEPARATOR = 0x0800
MF_OWNERDRAW = 0x0100
MF_POPUP = 0x0010
MF_HILITE = 0x0080
MF_DISABLED_OR_GRAYED = 0x0003
POPUP_MENU_CLASS = "#32768"

user32.GetMenuItemCount.argtypes = [wintypes.HMENU]
user32.GetMenuItemCount.restype = ctypes.c_int
user32.GetMenuStringW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.LPWSTR,
                                  ctypes.c_int, wintypes.UINT]
user32.GetMenuStringW.restype = ctypes.c_int
user32.GetMenuState.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
user32.GetMenuState.restype = wintypes.UINT
user32.GetMenuItemRect.argtypes = [wintypes.HWND, wintypes.HMENU, wintypes.UINT,
                                   ctypes.POINTER(wintypes.RECT)]
user32.GetMenuItemRect.restype = wintypes.BOOL


def popup_menu_items(hwnd: int, *, timeout_ms: int = 500) -> list[dict]:
    """The items of the popup menu window `hwnd` shows, read from the menu.

    A context menu is a `#32768` window whose items are not windows and,
    when the application draws them itself, not on the accessibility
    surface either -- a session clicked one by an offset measured off a
    screenshot (D65). The menu handle answers for all of them: count,
    rectangle on screen, and the text of any item that has one. An
    owner-drawn item has a rectangle and no text; the application keeps
    its caption to itself.
    """
    handle = send_message_timeout(hwnd, MN_GETHMENU, 0, 0, timeout_ms=timeout_ms)
    if not handle:
        return []
    hmenu = wintypes.HMENU(handle)
    count = user32.GetMenuItemCount(hmenu)
    items: list[dict] = []
    for index in range(max(count, 0)):
        state = user32.GetMenuState(hmenu, index, MF_BYPOSITION)
        rect = wintypes.RECT()
        if not user32.GetMenuItemRect(wintypes.HWND(hwnd), hmenu, index, ctypes.byref(rect)):
            continue
        buf = ctypes.create_unicode_buffer(256)
        user32.GetMenuStringW(hmenu, index, buf, 256, MF_BYPOSITION)
        items.append({
            "index": index,
            "text": buf.value.replace("&", ""),
            "rect": (rect.left, rect.top, rect.right, rect.bottom),
            "separator": bool(state & MF_SEPARATOR),
            "owner_drawn": bool(state & MF_OWNERDRAW),
            "enabled": not (state & MF_DISABLED_OR_GRAYED),
        })
    return items


def client_to_screen(hwnd: int, point: tuple[int, int]) -> tuple[int, int]:
    """A point in `hwnd`'s client coordinates, on screen."""
    pt = wintypes.POINT(int(point[0]), int(point[1]))
    user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(pt))
    return pt.x, pt.y


def screen_to_client(hwnd: int, point: tuple[int, int]) -> tuple[int, int]:
    """A screen point in `hwnd`'s client coordinates."""
    pt = wintypes.POINT(int(point[0]), int(point[1]))
    user32.ScreenToClient(wintypes.HWND(hwnd), ctypes.byref(pt))
    return pt.x, pt.y


def client_centre(hwnd: int) -> tuple[int, int]:
    rect = wintypes.RECT()
    user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect))
    return (rect.right - rect.left) // 2, (rect.bottom - rect.top) // 2


def client_size(hwnd: int) -> tuple[int, int]:
    """The width and height of `hwnd`'s client area."""
    rect = wintypes.RECT()
    user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect))
    return rect.right - rect.left, rect.bottom - rect.top


user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.IsHungAppWindow.argtypes = [wintypes.HWND]
user32.IsHungAppWindow.restype = wintypes.BOOL


def is_hung(hwnd: int) -> bool:
    """Whether the system considers the window's thread hung: no message
    pumped for five seconds. The one signal that tells a frozen application
    from a busy one (D66)."""
    return bool(user32.IsHungAppWindow(wintypes.HWND(hwnd)))


user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
kernel32_fg = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32_fg.GetCurrentThreadId.restype = wintypes.DWORD
SW_RESTORE = 9


def bring_foreground(hwnd: int) -> bool:
    """Bring `hwnd` to the front and give it the foreground, returning whether
    it took it. The opposite of everything else here, done only on request.

    A background process cannot simply call SetForegroundWindow -- Windows
    refuses, and the window only flashes in the taskbar. The documented way
    around that is to attach this thread's input queue to the current
    foreground window's thread for the duration of the call; while attached,
    SetForegroundWindow is honoured. That attach is exactly what D64 refused
    to do for a *click*, because it moves the keyboard focus the operator is
    typing into -- which is why this is never automatic and never a side
    effect. It is done here only because a caller asked to bring the window
    forward, knowing it interrupts the operator (D73). The attach is undone
    before returning.
    """
    target = wintypes.HWND(hwnd)
    if user32.IsIconic(target):
        user32.ShowWindow(target, SW_RESTORE)
    fg = user32.GetForegroundWindow()
    this_thread = kernel32_fg.GetCurrentThreadId()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = False
    if fg_thread and fg_thread != this_thread:
        attached = bool(user32.AttachThreadInput(this_thread, fg_thread, True))
    try:
        user32.BringWindowToTop(target)
        user32.SetForegroundWindow(target)
    finally:
        if attached:
            user32.AttachThreadInput(this_thread, fg_thread, False)
    now = user32.GetForegroundWindow()
    return bool(now) and root_window(now) == root_window(hwnd)


def to_physical_rect(rect: tuple[int, int, int, int]) -> dict:
    """A logical-frame rectangle in physical pixels: what a DPI-aware
    screenshot tool reports (D73). The scale is the display's, and a
    DPI-unaware process's logical origin already matches the physical one
    at the primary monitor's top-left, so the ratio is the whole
    conversion."""
    scale = display_scale()
    left, top, right, bottom = rect
    return {"left": round(left * scale), "top": round(top * scale),
            "right": round(right * scale), "bottom": round(bottom * scale),
            "scale": scale}


def popup_menu_item_state(hwnd: int, index: int, *, timeout_ms: int = 500) -> dict | None:
    """One item's state from the menu a `#32768` window shows: whether it
    is greyed, and whether it opens a submenu. None when the window no
    longer shows a menu."""
    handle = send_message_timeout(hwnd, MN_GETHMENU, 0, 0, timeout_ms=timeout_ms)
    if not handle:
        return None
    state = user32.GetMenuState(wintypes.HMENU(handle), index, MF_BYPOSITION)
    if state == 0xFFFFFFFF:
        return None
    return {"enabled": not (state & MF_DISABLED_OR_GRAYED),
            "submenu": bool(state & MF_POPUP),
            "highlighted": bool(state & MF_HILITE)}


def popup_menu_select(hwnd: int, index: int, *, timeout_ms: int = 500) -> bool:
    """Highlight item `index` of the popup menu window, the way the arrow
    keys would; the menu's own selection state, not a pointer."""
    send_message_timeout(hwnd, MN_SELECTITEM, index, 0, timeout_ms=timeout_ms)
    return True


def popup_menu_showing(hwnd: int) -> bool:
    """Whether the popup menu window is still up. A menu that has been
    answered ends, and its window goes with it."""
    target = wintypes.HWND(hwnd)
    return bool(user32.IsWindow(target)) and bool(user32.IsWindowVisible(target))
