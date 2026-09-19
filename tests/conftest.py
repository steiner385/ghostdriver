import ctypes
import functools
import subprocess
import sys
import threading
import time

import psutil
import pytest

# --- keep the suite off the operator's desktop (#93) -----------------------
# Every Windows fixture is a console-subsystem python.exe spawned with Popen.
# The fixture *windows* are already created off-screen and never activated
# (see the owned-window helpers below), so they never appear -- but a plain
# Popen of a console program still pops a console window, and hundreds of them
# flashing across a run is its own disruption of whoever is at the keyboard.
# CREATE_NO_WINDOW gives the child no console; stdout=PIPE is unaffected, so
# the JSON handshake the fixtures print still arrives. Applied once here, to
# every Popen in the test process, so no spawn site (there are ~two dozen) has
# to remember -- and so a new test cannot reintroduce the flash by forgetting.
if sys.platform == "win32":
    _CREATE_NO_WINDOW = 0x08000000
    _base_popen_init = subprocess.Popen.__init__

    @functools.wraps(_base_popen_init)
    def _quiet_popen_init(self, *args, **kwargs):
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | _CREATE_NO_WINDOW
        _base_popen_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _quiet_popen_init  # type: ignore[method-assign]


def _live_watchers() -> list[str]:
    """Names of any live watch threads. A MinimizedWatch or InterferenceWatch
    names its thread `minimized-watch-<pid>` / `interference-watch-<pid>`; a
    thread that outlives its test is the mechanism issue #4 tracks."""
    return sorted(t.name for t in threading.enumerate()
                  if t.name.startswith(("minimized-watch-", "interference-watch-")))


def _leaked_watch_for(pid: int) -> str | None:
    """A live minimized-watch thread targeting `pid`, if one exists: a watch
    from a prior test still running against a pid the OS has reused (issue #4)."""
    name = f"minimized-watch-{pid}"
    return name if any(t.name == name for t in threading.enumerate()) else None


on_windows = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows backend test"
)

on_linux = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux backend test"
)


def _version_tuple(text: str) -> tuple[int, ...]:
    """The leading numeric components of a version, for comparison.

    Stops at the first component that is not a plain integer, so `2.1.1`,
    `2.1.0rc1` and `2.1` all compare the way a reader expects without
    depending on `packaging` being installed.
    """
    parts: list[int] = []
    for piece in text.split("."):
        if not piece.isdigit():
            break
        parts.append(int(piece))
    return tuple(parts)


#: 1.x is importable and then fails deep inside -- FastMCP was renamed
#: MCPServer at the 2.0 boundary, so `import mcp` succeeds and
#: `mcp.server.mcpserver` does not exist.
MCP_MINIMUM = "2.1"


def _installed_mcp_version() -> str | None:
    """The mcp *distribution's* version, or None if it is not installed.

    Distribution metadata rather than the module's `__version__`, because mcp
    2.1.1 ships without that attribute. `pytest.importorskip(..., minversion=)`
    reads the attribute, so a correct install was read as version `None`,
    judged below the minimum, and the entire protocol suite skipped with a
    reason that looked plausible and was wrong (#53).
    """
    import importlib.metadata

    try:
        return importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:
        return None


def protocol_layer_refusal(installed: str | None, minimum: str = MCP_MINIMUM) -> str | None:
    """Why the protocol layer cannot be tested, or `None` if it can.

    Takes the version rather than looking it up, so the decision can be tested
    by feeding it values instead of by breaking an install. A test that had to
    uninstall mcp to check this would only run where the bug cannot be
    reproduced, which is the mistake #39 catalogued.
    """
    if installed is None:
        return ("the protocol layer is not installed: this suite needs mcp "
                f"{minimum} or newer. Install it with: pip install -e '.[server]'")
    if _version_tuple(installed) < _version_tuple(minimum):
        return (f"mcp {installed} is installed; this suite needs {minimum} or newer "
                "(1.x renamed FastMCP to MCPServer, so 1.x imports and then fails "
                "on an inner path). Upgrade with: pip install -e '.[server]'")
    return None


def refuse_unusable_protocol_layer(installed: str | None) -> None:
    """Stop the whole run, saying why (#159).

    Deliberately not a skip. `pytest.skip` at module level *is* a collection
    error, and pytest reports it by explaining `allow_module_level` -- a
    message about pytest's own API that never names mcp, the version required,
    or the remedy. The run stopped either way; only the reader was left
    guessing which of two numbers was wrong.

    Stopping is the right outcome and stays. A suite that cannot exercise the
    protocol layer has lost that coverage, and the thesis this project is built
    on is that lost coverage must be loud rather than quietly subtracted from a
    green run (D#39, D#53, D#58).

    `UsageError` because it is reported as a plain message with no traceback,
    before collection -- so it reads as a statement about the environment,
    which is what it is.
    """
    reason = protocol_layer_refusal(installed)
    if reason is not None:
        raise pytest.UsageError(reason)


def mcp_module():
    """The `mcp` module, which `pytest_configure` has already vetted.

    No gate of its own: by the time any test module imports this, the session
    either refused to start or the distribution is good.
    """
    import importlib

    return importlib.import_module("mcp")


@functools.cache
def user32():
    """`user32`, bound on the first call rather than at import.

    The single place a test reaches Win32 from the test process itself.
    `ctypes.WinDLL` does not exist off Windows -- it raises AttributeError,
    not the OSError an older comment in test_cli.py claims -- and a module
    that binds it at import fails *collection*, which is not a skip: it
    aborts the entire run, including every test that has nothing to do with
    Windows. `pytestmark = on_windows` does not help, because it gates the
    tests and not the module.

    So the binding is deferred, and it is deferred in one place: six modules
    each held their own identical copy of this line, which is six chances
    for the next one to be written the other way. Call it inside the test.
    """
    return ctypes.WinDLL("user32", use_last_error=True)

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
import os
import sys
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
# The tool under test exists to observe a desktop without disturbing it, and
# its own test suite must hold to that: a developer running pytest is using
# the machine at the time. A plain top-level window shown with
# SW_SHOWNORMAL is activated by the system on creation, which takes
# foreground and keyboard focus away from whatever the developer is typing
# into -- once per test, across every test that uses this fixture.
#
# WS_EX_NOACTIVATE keeps the system from activating it, SW_SHOWNOACTIVATE
# keeps this script from activating it, WS_EX_TOOLWINDOW keeps it out of the
# taskbar and the alt-tab list, and parking it off-screen keeps it from
# painting over the developer's work. None of that changes what the tests
# read: the window is still genuinely visible, still enumerable, and still
# answers WM_GETTEXT.
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
SW_SHOWNOACTIVATE = 4
OFFSCREEN = -32000
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
    WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
    CLASS_NAME, "GhostdriverTestWindow", WS_OVERLAPPEDWINDOW,
    OFFSCREEN, OFFSCREEN, 360, 260, None, None, instance, None,
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

user32.ShowWindow(main, SW_SHOWNOACTIVATE)
user32.UpdateWindow(main)

# Announce the pid that actually owns these windows. It is not necessarily
# the pid Popen returned: a virtualenv's Scripts/python.exe can be a
# launcher stub that re-executes the base interpreter as a separate
# process, in which case Popen holds the stub and every window here belongs
# to a pid the parent has never seen. Reporting it from the inside is the
# only account that is right either way.
print(os.getpid(), flush=True)

message = wintypes.MSG()
while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
    user32.TranslateMessage(ctypes.byref(message))
    user32.DispatchMessageW(ctypes.byref(message))
'''


# A second target, shaped like an application that minimizes to a taskbar
# proxy: a small owner window that stands for the application, and a real
# form it owns. Minimizing hides the form and minimizes the owner, and
# restoring the owner makes the application put its own form back.
#
# That shape is the whole reason `restore` works the way it does, so it has
# to be reproduced rather than mocked. The decoy below is the point of the
# exercise: an owned window that is hidden and *stays* hidden, standing for
# the dialogs and pooled forms a real target keeps back. A restore that
# un-hides windows itself, instead of letting the application decide, would
# put the decoy on screen.
#
# Everything starts minimized and off-screen, and nothing here is ever
# activated: the suite must not disturb the desktop of whoever runs it.
_WIN32_MINIMIZED_APP = r"""
import ctypes
import os
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
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT
]
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT

WS_VISIBLE = 0x10000000
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
SW_HIDE = 0
SW_SHOWNA = 8
SW_SHOWMINNOACTIVE = 7
WM_SIZE = 0x0005
SIZE_RESTORED = 0
SIZE_MINIMIZED = 1
OFFSCREEN = -32000

OWNER_CLASS = "GhostdriverOwnerClass"
FORM_CLASS = "GhostdriverFormClass"

state = {"form": None, "decoy": None}


# Hide the form on minimize, put it back on restore. This is the
# behaviour `restore` relies on and must not duplicate: the application,
# not the driver, decides which of its windows belong on screen. The
# decoy is deliberately never shown.
def _owner_proc(hwnd, message, wparam, lparam):
    if message == WM_SIZE and state["form"]:
        if wparam == SIZE_MINIMIZED:
            user32.ShowWindow(wintypes.HWND(state["form"]), SW_HIDE)
        elif wparam == SIZE_RESTORED:
            user32.ShowWindow(wintypes.HWND(state["form"]), SW_SHOWNA)
    return user32.DefWindowProcW(hwnd, message, wparam, lparam)


OWNER_PROC = WNDPROC(_owner_proc)
FORM_PROC = WNDPROC(
    lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l)
)

instance = kernel32.GetModuleHandleW(None)

for name, proc in ((OWNER_CLASS, OWNER_PROC), (FORM_CLASS, FORM_PROC)):
    cls = WNDCLASSW()
    cls.lpfnWndProc = proc
    cls.hInstance = instance
    cls.hbrBackground = 6
    cls.lpszClassName = name
    if not user32.RegisterClassW(ctypes.byref(cls)):
        raise ctypes.WinError(ctypes.get_last_error())

owner = user32.CreateWindowExW(
    WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
    OWNER_CLASS, "GhostdriverOwner", WS_OVERLAPPEDWINDOW,
    OFFSCREEN, OFFSCREEN, 200, 120, None, None, instance, None,
)
if not owner:
    raise ctypes.WinError(ctypes.get_last_error())

# Owned, not child: a top-level window whose owner is `owner`.
form = user32.CreateWindowExW(
    WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
    FORM_CLASS, "GhostdriverForm", WS_OVERLAPPEDWINDOW,
    OFFSCREEN, OFFSCREEN, 400, 300, owner, None, instance, None,
)
if not form:
    raise ctypes.WinError(ctypes.get_last_error())
state["form"] = form

decoy = user32.CreateWindowExW(
    WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
    FORM_CLASS, "GhostdriverDecoyDialog", WS_OVERLAPPEDWINDOW,
    OFFSCREEN, OFFSCREEN, 200, 150, owner, None, instance, None,
)
if not decoy:
    raise ctypes.WinError(ctypes.get_last_error())
state["decoy"] = decoy

# Reach the target state the real application is found in: owner minimized
# and still carrying WS_VISIBLE, every owned form hidden.
user32.ShowWindow(wintypes.HWND(form), SW_HIDE)
user32.ShowWindow(wintypes.HWND(decoy), SW_HIDE)
user32.ShowWindow(wintypes.HWND(owner), SW_SHOWMINNOACTIVE)

print(f"{os.getpid()} {owner} {form} {decoy}", flush=True)

message = wintypes.MSG()
while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
    user32.TranslateMessage(ctypes.byref(message))
    user32.DispatchMessageW(ctypes.byref(message))
"""


# A target that creates a window and then never pumps messages.
#
# This exists for one branch that nothing else can reach. `read_window_text`
# distinguishes "answered with no text" ("") from "did not answer" (None),
# and every other fixture -- and every control on every real target measured
# so far -- answers. The distinction is load-bearing: an unresponsive
# control reports empty text that is *unknown*, not confirmed blank, and a
# caller that collapses the two silently asserts a field is empty when it
# simply never replied.
#
# A window whose owning thread never calls GetMessage cannot service
# WM_GETTEXT, so a cross-process send hits its timeout. The window is
# otherwise completely normal: it enumerates, and its class and rect read
# back fine, because those come from the kernel rather than from the
# window's own thread. That is exactly the shape of a hung target.
_WIN32_SILENT_APP = r"""
import ctypes
import os
import time
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
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL

WS_VISIBLE = 0x10000000
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
SW_SHOWNOACTIVATE = 4
OFFSCREEN = -32000

CLASS_NAME = "GhostdriverSilentClass"

WINDOW_PROC = WNDPROC(
    lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l)
)

instance = kernel32.GetModuleHandleW(None)
cls = WNDCLASSW()
cls.lpfnWndProc = WINDOW_PROC
cls.hInstance = instance
cls.hbrBackground = 6
cls.lpszClassName = CLASS_NAME
if not user32.RegisterClassW(ctypes.byref(cls)):
    raise ctypes.WinError(ctypes.get_last_error())

# Real window text, which a pumping target would return happily. That it
# comes back as "did not answer" rather than as this string is the whole
# point: the text exists, the thread just cannot be asked for it.
window = user32.CreateWindowExW(
    WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
    CLASS_NAME, "GhostdriverSilentWindow", WS_OVERLAPPEDWINDOW | WS_VISIBLE,
    OFFSCREEN, OFFSCREEN, 200, 120, None, None, instance, None,
)
if not window:
    raise ctypes.WinError(ctypes.get_last_error())
user32.ShowWindow(wintypes.HWND(window), SW_SHOWNOACTIVATE)

print(f"{os.getpid()} {window}", flush=True)

# No message loop, deliberately. Sleeping rather than pumping is what makes
# every cross-process WM_GETTEXT to this window time out.
time.sleep(600)
"""


# A target holding itself open with a modal dialog.
#
# Modality is not a property of the dialog's appearance; it is that the
# dialog's owner has been disabled. Every control in the owner then refuses
# input, which from outside is indistinguishable from a hung application.
# Reproducing it needs no message box and no toolkit: an owned top-level
# window plus EnableWindow(owner, FALSE) is exactly what showing a modal
# dialog does.
_WIN32_MODAL_APP = r"""
import ctypes
import os
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
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.EnableWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
user32.EnableWindow.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT
]
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT

WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
SW_SHOWNOACTIVATE = 4
OFFSCREEN = -32000

MAIN_CLASS = "GhostdriverModalMainClass"
DIALOG_CLASS = "GhostdriverModalDialogClass"

PROC = WNDPROC(lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))
instance = kernel32.GetModuleHandleW(None)

for name in (MAIN_CLASS, DIALOG_CLASS):
    cls = WNDCLASSW()
    cls.lpfnWndProc = PROC
    cls.hInstance = instance
    cls.hbrBackground = 6
    cls.lpszClassName = name
    if not user32.RegisterClassW(ctypes.byref(cls)):
        raise ctypes.WinError(ctypes.get_last_error())

main = user32.CreateWindowExW(
    WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
    MAIN_CLASS, "GhostdriverModalMain", WS_OVERLAPPEDWINDOW | WS_VISIBLE,
    OFFSCREEN, OFFSCREEN, 400, 300, None, None, instance, None,
)
if not main:
    raise ctypes.WinError(ctypes.get_last_error())

# Owned, not child: top-level, and what a dialog is.
dialog = user32.CreateWindowExW(
    WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
    DIALOG_CLASS, "Confirm Delete Record", WS_OVERLAPPEDWINDOW | WS_VISIBLE,
    OFFSCREEN, OFFSCREEN, 240, 140, main, None, instance, None,
)
if not dialog:
    raise ctypes.WinError(ctypes.get_last_error())

user32.ShowWindow(wintypes.HWND(main), SW_SHOWNOACTIVATE)
user32.ShowWindow(wintypes.HWND(dialog), SW_SHOWNOACTIVATE)

# The whole point. This, not the dialog's appearance, is modality.
user32.EnableWindow(wintypes.HWND(main), False)

print(f"{os.getpid()} {main} {dialog}", flush=True)

message = wintypes.MSG()
while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
    user32.TranslateMessage(ctypes.byref(message))
    user32.DispatchMessageW(ctypes.byref(message))
"""


def main_tree(pid: int):
    """The target's largest window tree, matching how the tool selects it.

    Indexing enumerate_process(pid)[0] takes the first window in Z-order,
    which is not necessarily the application's main window -- a process can
    own hidden top-level windows it never created deliberately. The tests
    call the same selector the tool calls, rather than reimplementing it:
    an earlier version of this helper duplicated the tool's node-count
    heuristic, so the suite agreed with a selection bug instead of catching
    it.
    """
    from ghostdriver.backends.windows.enumerate import enumerate_process
    from ghostdriver.model.window import select_main_tree

    tree = select_main_tree(enumerate_process(pid))
    if tree is None:
        raise AssertionError(f"pid {pid} has no top-level windows on this desktop")
    return tree


@pytest.fixture
def win32_target():
    """Launch a native Win32 window in a subprocess and yield its pid.

    Cross-process is the case that matters: reading text and enumerating
    windows behave differently for windows we do not own.

    The pid comes from the target itself rather than from Popen. A
    virtualenv's Scripts/python.exe may be a launcher stub that re-executes
    the base interpreter in a separate process; Popen then reports the stub,
    which owns no windows, and every test here would fail in setup against a
    backend that is working perfectly.
    """
    proc = subprocess.Popen(
        [sys.executable, "-c", _WIN32_APP],
        stdout=subprocess.PIPE,
        text=True,
    )
    pid = None
    try:
        announced = proc.stdout.readline().strip()
        if not announced:
            raise RuntimeError("target exited before announcing its pid")
        pid = int(announced)

        deadline = time.time() + 10
        from ghostdriver.backends.windows.enumerate import top_level_windows
        while time.time() < deadline:
            if top_level_windows(pid):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("target did not create a window in time")
        time.sleep(0.3)  # let child controls finish being created
        # A fresh, never-activated, off-screen window has no business being
        # minimized. Twice in hundreds of full runs one was, and the test
        # that found it could only report the symptom. Failing here, in
        # setup, says "minimized before the test began" -- and names every
        # top-level window of the process with its state, which is the
        # evidence the next diagnosis starts from.
        #
        # The leading hypothesis (issue #4) is a leaked MinimizedWatch: a
        # prior test's watch, still running against a pid the OS has since
        # reused for this fresh target, minimizes it out from under the test.
        # D73 made a watch stop once its own window is gone, which should
        # close that door -- so a `minimized-watch-<pid>` thread alive for
        # *this* pid is the smoking gun, named here rather than left to
        # inference.
        from ghostdriver.backends.windows import winapi
        leaked = _leaked_watch_for(pid)
        if leaked is not None:
            raise RuntimeError(
                f"a watch thread is alive against this fresh target's pid {pid}: "
                f"{leaked!r}. A prior test leaked it and the OS reused the pid; "
                "this is the mechanism issue #4 tracks. It should not survive "
                "D73 (a watch stops when its window is gone) -- if it did, that "
                "regressed.")
        states = [(f"0x{h:08X}", winapi.class_name(h), winapi.is_minimized(h))
                  for h in top_level_windows(pid)]
        if any(iconic for _, _, iconic in states):
            raise RuntimeError(
                "a window of the fresh target is already minimized, before "
                f"the test began: {states}. Live watch threads: {_live_watchers()} "
                "(a leaked MinimizedWatch on a reused pid is the #4 hypothesis).")
        yield pid
    finally:
        # Terminating Popen's process is not enough when it is only a stub:
        # the interpreter holding the message loop is a separate process and
        # would outlive the test.
        if pid is not None and pid != proc.pid:
            try:
                psutil.Process(pid).terminate()
            except psutil.Error:
                pass
        proc.terminate()
        proc.wait(timeout=5)


@pytest.fixture
def minimized_target():
    """A target minimized to a taskbar proxy; yields (pid, owner, form, decoy).

    Started already minimized, so the test never has to minimize it and
    never has to show anything on the developer's screen to get there.
    """
    proc = subprocess.Popen(
        [sys.executable, "-c", _WIN32_MINIMIZED_APP],
        stdout=subprocess.PIPE,
        text=True,
    )
    pid = None
    try:
        announced = proc.stdout.readline().split()
        if len(announced) != 4:
            raise RuntimeError("target exited before announcing its windows")
        pid, owner, form, decoy = (int(x) for x in announced)

        deadline = time.time() + 10
        from ghostdriver.backends.windows.enumerate import top_level_windows
        while time.time() < deadline:
            if top_level_windows(pid):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("target did not create a window in time")
        yield pid, owner, form, decoy
    finally:
        if pid is not None and pid != proc.pid:
            try:
                psutil.Process(pid).terminate()
            except psutil.Error:
                pass
        proc.terminate()
        proc.wait(timeout=5)


@pytest.fixture
def silent_target():
    """A target whose window never answers a message; yields (pid, hwnd).

    Reads against it cost their full timeout, so tests using this fixture
    are deliberately few.
    """
    proc = subprocess.Popen(
        [sys.executable, "-c", _WIN32_SILENT_APP],
        stdout=subprocess.PIPE,
        text=True,
    )
    pid = None
    try:
        announced = proc.stdout.readline().split()
        if len(announced) != 2:
            raise RuntimeError("target exited before announcing its window")
        pid, hwnd = (int(x) for x in announced)

        deadline = time.time() + 10
        from ghostdriver.backends.windows.enumerate import top_level_windows
        while time.time() < deadline:
            if hwnd in top_level_windows(pid):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("target did not create a window in time")
        yield pid, hwnd
    finally:
        if pid is not None and pid != proc.pid:
            try:
                psutil.Process(pid).terminate()
            except psutil.Error:
                pass
        proc.terminate()
        proc.wait(timeout=5)


@pytest.fixture
def modal_target():
    """A target held open by a modal dialog; yields (pid, main, dialog)."""
    proc = subprocess.Popen(
        [sys.executable, "-c", _WIN32_MODAL_APP],
        stdout=subprocess.PIPE,
        text=True,
    )
    pid = None
    try:
        announced = proc.stdout.readline().split()
        if len(announced) != 3:
            raise RuntimeError("target exited before announcing its windows")
        pid, main, dialog = (int(x) for x in announced)

        deadline = time.time() + 10
        from ghostdriver.backends.windows.enumerate import top_level_windows
        while time.time() < deadline:
            if dialog in top_level_windows(pid):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("target did not create its dialog in time")
        yield pid, main, dialog
    finally:
        if pid is not None and pid != proc.pid:
            try:
                psutil.Process(pid).terminate()
            except psutil.Error:
                pass
        proc.terminate()
        proc.wait(timeout=5)


# --- the foreground watch --------------------------------------------------
# Started here so it covers every test; asserted in test_zz_focus_guard.py.

def pytest_configure(config):
    # First, before a watch thread or anything else: an unusable protocol
    # layer stops the run here rather than as a collection error later (#159).
    refuse_unusable_protocol_layer(_installed_mcp_version())

    from tests.focusguard import ForegroundWatch

    watch = ForegroundWatch()
    watch.start()
    config._ghostdriver_focus_watch = watch


def pytest_runtest_logstart(nodeid, location):
    from tests import focusguard

    focusguard.CURRENT["test"] = nodeid


def pytest_unconfigure(config):
    watch = getattr(config, "_ghostdriver_focus_watch", None)
    if watch is not None:
        watch.stop()



@pytest.fixture
def preserved_clipboard():
    """Snapshot every clipboard format before a test that writes it, and put
    it all back after -- the person may be using the clipboard (D70)."""
    from ghostdriver.backends.windows.grid import restore_clipboard, snapshot_clipboard

    before = snapshot_clipboard()
    try:
        yield before
    finally:
        restore_clipboard(before)
