import subprocess
import sys
import time

import pytest

on_windows = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows backend test"
)

# A native Win32 window built directly through ctypes, run in a subprocess.
#
# This has to be native rather than a cross-platform GUI toolkit. Several
# tests assert that control captions come back from a cross-process
# WM_GETTEXT, and a toolkit that creates child HWNDs with a NULL window name
# and paints its own labels answers those reads with "" -- the tests would
# fail in Setup, before any validation gate ran, against a tool that is
# working correctly. Standard system control classes store real window text,
# so this fixture exercises the read path the backend actually depends on.
#
# Kept as a string, executed only in the Windows subprocess, so this module
# stays importable on any host: ctypes.WinDLL and ctypes.WINFUNCTYPE do not
# exist off Windows.
#
# The window procedure defers everything to DefWindowProcW, which is what
# answers WM_GETTEXTLENGTH and WM_GETTEXT out of the window text supplied at
# creation. It handles no message itself, so this script names no message
# constant at all.
_WIN32_APP = r'''
import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HANDLE),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

user32.DefWindowProcW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]
user32.DefWindowProcW.restype = LRESULT

user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM

user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,     # dwExStyle
    wintypes.LPCWSTR,   # lpClassName
    wintypes.LPCWSTR,   # lpWindowName
    wintypes.DWORD,     # dwStyle
    ctypes.c_int,       # X
    ctypes.c_int,       # Y
    ctypes.c_int,       # nWidth
    ctypes.c_int,       # nHeight
    wintypes.HWND,      # hWndParent
    wintypes.HMENU,     # hMenu
    wintypes.HINSTANCE, # hInstance
    wintypes.LPVOID,    # lpParam
]
user32.CreateWindowExW.restype = wintypes.HWND

user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL

user32.UpdateWindow.argtypes = [wintypes.HWND]
user32.UpdateWindow.restype = wintypes.BOOL

# GetMessageW returns -1 on error, which BOOL (c_long) would still carry but
# c_int states the contract: this is a tri-state, not a boolean.
user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT
]
user32.GetMessageW.restype = ctypes.c_int

user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.restype = wintypes.BOOL

user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT

CS_VREDRAW = 0x0001
CS_HREDRAW = 0x0002
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_BORDER = 0x00800000
WS_OVERLAPPEDWINDOW = 0x00CF0000
SW_SHOWNORMAL = 1
COLOR_WINDOW = 5

CLASS_NAME = "GhostdriverTestClass"


def _window_proc(hwnd, message, wparam, lparam):
    """Handle nothing; let the system default answer every message.

    DefWindowProcW is what serves WM_GETTEXTLENGTH and WM_GETTEXT from the
    window text passed to CreateWindowExW, which is exactly the surface the
    backend reads.
    """
    return user32.DefWindowProcW(hwnd, message, wparam, lparam)


# Held in a module-level name: if the WNDPROC object is collected, the
# system calls a freed trampoline.
WINDOW_PROC = WNDPROC(_window_proc)

instance = kernel32.GetModuleHandleW(None)

wndclass = WNDCLASSW()
wndclass.style = CS_HREDRAW | CS_VREDRAW
wndclass.lpfnWndProc = WINDOW_PROC
wndclass.cbClsExtra = 0
wndclass.cbWndExtra = 0
wndclass.hInstance = instance
wndclass.hIcon = None
wndclass.hCursor = None
wndclass.hbrBackground = COLOR_WINDOW + 1
wndclass.lpszMenuName = None
wndclass.lpszClassName = CLASS_NAME

if not user32.RegisterClassW(ctypes.byref(wndclass)):
    raise ctypes.WinError(ctypes.get_last_error())

main = user32.CreateWindowExW(
    0, CLASS_NAME, "GhostdriverTestWindow", WS_OVERLAPPEDWINDOW,
    120, 120, 360, 260, None, None, instance, None,
)
if not main:
    raise ctypes.WinError(ctypes.get_last_error())

# Real system controls, each carrying real window text. Level 2 of the tree.
for caption, top in (("Expand All", 10), ("Collapse All", 45)):
    if not user32.CreateWindowExW(
        0, "BUTTON", caption, WS_CHILD | WS_VISIBLE,
        10, top, 140, 28, main, None, instance, None,
    ):
        raise ctypes.WinError(ctypes.get_last_error())

if not user32.CreateWindowExW(
    0, "EDIT", "", WS_CHILD | WS_VISIBLE | WS_BORDER,
    10, 80, 200, 24, main, None, instance, None,
):
    raise ctypes.WinError(ctypes.get_last_error())

# A second instance of our own class, used as a container so the tree is
# genuinely three levels deep. The flattening test needs a real grandchild:
# under an EnumChildWindows-based walk the nested button would surface as a
# direct child of the top-level window, and nothing shallower can catch that.
container = user32.CreateWindowExW(
    0, CLASS_NAME, "", WS_CHILD | WS_VISIBLE,
    10, 120, 300, 90, main, None, instance, None,
)
if not container:
    raise ctypes.WinError(ctypes.get_last_error())

# Level 3.
if not user32.CreateWindowExW(
    0, "BUTTON", "Nested Action", WS_CHILD | WS_VISIBLE,
    10, 20, 160, 28, container, None, instance, None,
):
    raise ctypes.WinError(ctypes.get_last_error())

user32.ShowWindow(main, SW_SHOWNORMAL)
user32.UpdateWindow(main)

message = wintypes.MSG()
while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
    user32.TranslateMessage(ctypes.byref(message))
    user32.DispatchMessageW(ctypes.byref(message))
'''


def main_tree(pid: int):
    """The target's largest window tree, matching how the tool selects it.

    Indexing enumerate_process(pid)[0] takes the first window in Z-order,
    which is not necessarily the application's main window -- a process can
    own hidden top-level windows it never created deliberately. runner.py and
    cli.py both select by node count, so the tests must too, or they verify a
    different window than the tool reports on.
    """
    from ghostdriver.backends.windows.enumerate import enumerate_process

    trees = enumerate_process(pid)
    if not trees:
        raise AssertionError(f"pid {pid} has no top-level windows on this desktop")
    return max(trees, key=lambda t: sum(1 for _ in t.walk()))


@pytest.fixture
def win32_target():
    """Launch a native Win32 window in a subprocess and yield its pid.

    Cross-process is the case that matters: reading text and enumerating
    windows behave differently for windows we do not own.
    """
    proc = subprocess.Popen([sys.executable, "-c", _WIN32_APP])
    try:
        deadline = time.time() + 10
        from ghostdriver.backends.windows.enumerate import top_level_windows
        while time.time() < deadline:
            if top_level_windows(proc.pid):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("target did not create a window in time")
        time.sleep(0.3)  # let child controls finish being created
        yield proc.pid
    finally:
        proc.terminate()
        proc.wait(timeout=5)
