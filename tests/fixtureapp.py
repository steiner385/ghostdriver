"""A Profile L1 target, built to be broken on purpose.

Actuation cannot be developed against production business software: the
iteration loop is slow, the application state is precious, and the failure
cases that most need handling cannot be induced on demand. This reproduces
the profile instead (spec section 10).

The spec calls for Lazarus/Free Pascal. No Pascal toolchain exists on the
development machine, so this is built directly on the Win32 API through
ctypes. Every characteristic section 10 lists is reproduced; what is not
reproduced is the *emergent* behaviour of a real toolkit, which is a real
difference and the reason the deviation is recorded rather than assumed
harmless. The driver develops against this fixture's behaviour rather than
its language, so an LCL build can replace it later without invalidating the
actuation work.

    python -m tests.fixtureapp --help

Defaults are deliberately quiet: the window is off-screen and never
activated, and both disruptive behaviours are off. A test suite has to be
runnable on a machine somebody is working at -- a lesson this project
learned the hard way -- so focus theft and mid-run modals are opt-in, which
is also what makes them useful as *induced* failures rather than ambient
ones.

On startup it prints one JSON line to stdout naming its pid and the handles
a test needs, then runs a normal message loop.
"""

import argparse
import ctypes
import json
import os
import sys
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

WM_DESTROY = 0x0002
WM_PAINT = 0x000F
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_ERASEBKGND = 0x0014
WM_GETDLGCODE = 0x0087
WM_KEYDOWN = 0x0100
WM_CHAR = 0x0102
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_TIMER = 0x0113
WM_COMMAND = 0x0111
WM_COPY = 0x0301
WM_USER = 0x0400

WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_BORDER = 0x00800000
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_CLIENTEDGE = 0x00000200
ES_PASSWORD = 0x0020

#: How many characters the superclassed edits accept before they stop.
#:
#: Enforced here rather than through EM_LIMITTEXT, for two reasons. The
#: control keeps answering EM_GETLIMITTEXT with its default of thirty
#: thousand, which is the point of the finding this reproduces: the limit a
#: field declares does not predict where it actually stops. And rejecting
#: the character *before* the EDIT sees it keeps the control from sounding
#: the system beep on every one -- a real field does beep, but that is not
#: something a driver can observe, and a test run that fires sixty beeps at
#: whoever is at the machine is a bad neighbour.
FIELD_CAPACITY = 20

SW_SHOWNOACTIVATE = 4
SW_SHOWNORMAL = 1
GWL_WNDPROC = -4
GWL_STYLE = -16
COLOR_BTNFACE = 15
GA_PARENT = 1
OFFSCREEN = -32000

#: Sent to the main window to ask which page is showing. Exists so a test
#: can assert on the application's own idea of its state rather than on
#: what the screen happens to look like.
WM_FIXTURE_CURRENT_PAGE = WM_USER + 11

for fn, argtypes, restype in (
    ("DefWindowProcW", [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                        wintypes.LPARAM], LRESULT),
    ("CallWindowProcW", [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                         wintypes.WPARAM, wintypes.LPARAM], LRESULT),
    ("CreateWindowExW", [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                         wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, ctypes.c_int, wintypes.HWND,
                         wintypes.HMENU, wintypes.HINSTANCE,
                         wintypes.LPVOID], wintypes.HWND),
    ("ShowWindow", [wintypes.HWND, ctypes.c_int], wintypes.BOOL),
    ("SetForegroundWindow", [wintypes.HWND], wintypes.BOOL),
    ("EnableWindow", [wintypes.HWND, wintypes.BOOL], wintypes.BOOL),
    ("SetTimer", [wintypes.HWND, ctypes.c_void_p, wintypes.UINT,
                  ctypes.c_void_p], ctypes.c_void_p),
    ("KillTimer", [wintypes.HWND, ctypes.c_void_p], wintypes.BOOL),
    ("SetWindowTextW", [wintypes.HWND, wintypes.LPCWSTR], wintypes.BOOL),
    ("GetWindowTextW", [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int],
     ctypes.c_int),
    ("InvalidateRect", [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL],
     wintypes.BOOL),
    ("GetClientRect", [wintypes.HWND, ctypes.POINTER(wintypes.RECT)],
     wintypes.BOOL),
    ("FillRect", [wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                  wintypes.HBRUSH], ctypes.c_int),
    ("GetSysColorBrush", [ctypes.c_int], wintypes.HBRUSH),
    ("IsWindowEnabled", [wintypes.HWND], wintypes.BOOL),
    ("GetAncestor", [wintypes.HWND, wintypes.UINT], wintypes.HWND),
    ("GetWindowTextLengthW", [wintypes.HWND], ctypes.c_int),
    ("OpenClipboard", [wintypes.HWND], wintypes.BOOL),
    ("CloseClipboard", [], wintypes.BOOL),
    ("EmptyClipboard", [], wintypes.BOOL),
    ("SetClipboardData", [wintypes.UINT, wintypes.HANDLE], wintypes.HANDLE),
):
    f = getattr(user32, fn)
    f.argtypes, f.restype = argtypes, restype

user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int,
                                     ctypes.c_void_p]
user32.SetWindowLongPtrW.restype = ctypes.c_void_p
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_void_p

kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL

gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.TextOutW.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int,
                           wintypes.LPCWSTR, ctypes.c_int]
gdi32.MoveToEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int,
                           ctypes.c_void_p]
gdi32.LineTo.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", wintypes.HDC), ("fErase", wintypes.BOOL),
                ("rcPaint", wintypes.RECT), ("fRestore", wintypes.BOOL),
                ("fIncUpdate", wintypes.BOOL),
                ("rgbReserved", ctypes.c_byte * 32)]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HANDLE), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
                ("hIconSm", wintypes.HANDLE)]


user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.BeginPaint.restype = wintypes.HDC
user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = wintypes.ATOM
user32.GetClassInfoExW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                   ctypes.POINTER(WNDCLASSEXW)]
user32.GetClassInfoExW.restype = wintypes.BOOL

INSTANCE = kernel32.GetModuleHandleW(None)

# Class names are vendor-shaped on purpose: nothing in the driver may key on
# them, and names like "Button" would let a generic implementation pass by
# accident.
MAIN_CLASS = "GhostFixtureShell"
PAGE_CLASS = "GhostFixturePage"
BUTTON_CLASS = "GhostFixtureCommandButton"
GRID_CLASS = "GhostFixtureDataGrid"
BOUND_EDIT_CLASS = "GhostFixtureBoundEdit"
PLAIN_EDIT_CLASS = "GhostFixturePlainEdit"
MODAL_CLASS = "GhostFixtureModal"
CAPTION_CLASS = "GhostFixtureFieldCaption"
VALUE_CLASS = "GhostFixtureFieldValue"

#: Caption/value pairs on the detail panel.
#:
#: Not padding. "One window per control" is the defining characteristic of
#: Profile L1 -- the measured target carried 105 windows in its main tree and
#: exposed 29 UIA elements between them, because almost every control is a
#: vendor class the HWND bridge can only describe as a bare pane. A fixture
#: with a handful of native EDIT and STATIC controls inverts that ratio and
#: classifies as M1, which is the wrong profile to develop a driver against.
#: A real business form looks like this: rows of captions and values, each
#: its own window.
DETAIL_FIELDS = [
    ("Part Number", "0000118"), ("Revision", "C"), ("Unit of Measure", "EA"),
    ("Quantity", "12"), ("Classification", "Subassembly"),
    ("Authority", "MFG_AUTH"), ("Status", "Released"), ("Lot", "KT-27DEC"),
    ("Serial", "N/A"), ("Effectivity", "2026-01-01"),
    ("Work Center", "WC-14"), ("Operation", "0030"),
    ("Planner", "T. Stein"), ("Inspector", "N/A"),
    ("Material", "AL-6061"), ("Finish", "Anodize"),
    ("Drawing", "DWG-88213"), ("Sheet", "2 of 5"),
    ("Program", "Line 4"), ("Contract", "N/A"),
]

#: Kept alive at module scope: a collected WNDPROC is a freed trampoline the
#: system will still call.
_PROCS: list = []
_STATE: dict = {}


def _text_of(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buf, 512)
    return buf.value


# --- section 10 items 1 and 2: a button that is not a BUTTON -------------

def _button_proc(hwnd, msg, wparam, lparam):
    """Responds to the input-shaped pair, and to nothing semantic.

    A real Profile L1 button is a vendor class that never registered as a
    BUTTON, so `BM_CLICK` reaches a window procedure that has no idea what
    it means and discards it. Returning 0 from WM_GETDLGCODE completes the
    picture: nothing about this window says "button" to anything that asks.
    """
    if msg == WM_GETDLGCODE:
        return 0
    if msg == WM_ERASEBKGND:
        return 1
    if msg == WM_PAINT:
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(wintypes.HWND(hwnd), ctypes.byref(ps))
        rect = wintypes.RECT()
        user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect))
        pressed = _STATE.get(("pressed", hwnd), False)
        user32.FillRect(hdc, ctypes.byref(rect),
                        user32.GetSysColorBrush(COLOR_BTNFACE))
        gdi32.SetBkMode(hdc, 1)
        caption = _text_of(hwnd)
        gdi32.TextOutW(hdc, 6, 5 + (1 if pressed else 0), caption,
                       len(caption))
        user32.EndPaint(wintypes.HWND(hwnd), ctypes.byref(ps))
        return 0
    if msg in (WM_LBUTTONDOWN, WM_LBUTTONUP) and _blocked(hwnd):
        # A modal disables the top-level, and the system then drops real
        # input before a control sees it. A *posted* message arrives anyway,
        # so a control that acted on it would let a driver operate an
        # application the user cannot touch. Standard controls check; this
        # one checks, because a fixture that did not would quietly bless a
        # driver that skips the check too.
        return 0
    if msg == WM_LBUTTONDOWN:
        _STATE[("pressed", hwnd)] = True
        user32.InvalidateRect(wintypes.HWND(hwnd), None, True)
        return 0
    if msg == WM_LBUTTONUP:
        if _STATE.get(("pressed", hwnd)):
            _STATE[("pressed", hwnd)] = False
            user32.InvalidateRect(wintypes.HWND(hwnd), None, True)
            _on_click(hwnd)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _blocked(hwnd: int) -> bool:
    """Is any window between this one and the desktop disabled?

    `IsWindowEnabled` answers for one window: with the modal up, the shell
    reports disabled and its buttons report enabled. The chain is what
    carries the answer.
    """
    seen = set()
    current = hwnd
    while current and current not in seen:
        seen.add(current)
        if not user32.IsWindowEnabled(wintypes.HWND(current)):
            return True
        parent = user32.GetAncestor(wintypes.HWND(current), GA_PARENT)
        current = int(parent) if parent else 0
    return False


def _on_click(hwnd: int) -> None:
    """What a click does: bump a counter the test can read back.

    A counter rather than a visible effect, because an action that cannot be
    distinguished from a no-op manufactures false passes -- which is the
    reason pre- and post-conditions exist in the first place.
    """
    caption = _text_of(hwnd)
    _STATE["clicks"] = _STATE.get("clicks", 0) + 1
    _STATE["last_clicked"] = caption
    status = _STATE.get("status")
    if status:
        user32.SetWindowTextW(
            wintypes.HWND(status),
            f"clicks={_STATE['clicks']} last={caption}",
        )
    if _STATE.get("grab_after_ms"):
        # Section 10 item 5: an application that pulls itself to the
        # foreground after acting, on a delay, which is what makes it a
        # problem worth handling rather than one you notice immediately.
        user32.SetTimer(wintypes.HWND(_STATE["main"]), ctypes.c_void_p(2),
                        _STATE["grab_after_ms"], None)


# --- section 10 item 3: a grid with nothing inside it --------------------

GRID_ROWS = [
    ("PART-0001", "Bracket, upper", "EA", "12"),
    ("PART-0002", "Bracket, lower", "EA", "12"),
    ("PART-0003", "Fastener kit", "KIT", "3"),
]


CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _put_text_on_clipboard(text: str) -> None:
    """Own the clipboard briefly and leave `text` on it, as a grid would."""
    if not user32.OpenClipboard(None):
        return
    try:
        user32.EmptyClipboard()
        size = (len(text) + 1) * 2
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            return
        locked = kernel32.GlobalLock(handle)
        ctypes.memmove(locked, ctypes.create_unicode_buffer(text), size)
        kernel32.GlobalUnlock(handle)
        user32.SetClipboardData(CF_UNICODETEXT, handle)
    finally:
        user32.CloseClipboard()


def _grid_proc(hwnd, msg, wparam, lparam):
    """Owner-drawn: real content, zero child windows, no text anywhere.

    Everything visible here is painted. There are no per-cell windows, the
    window answers a text query with nothing, and no accessible surface
    exposes a row -- which is exactly why a driver needs pixels for this
    shape of control and needs to be able to *tell* that it does.
    """
    if msg == WM_GETTEXTLENGTH:
        return 0
    if msg == WM_GETTEXT:
        if wparam:
            ctypes.cast(lparam, wintypes.LPWSTR).contents.value = "\0"
        return 0
    if msg == WM_COPY and _STATE.get("grid_copies", True):
        # Section 10 item 3, the other half: an owner-drawn grid that will
        # not answer a text query but *will* copy its rows on request. Many
        # real grids do exactly this, and it is the cheapest exact-text
        # route a driver has. Tab across, newline down.
        _put_text_on_clipboard(
            "\r\n".join("\t".join(row) for row in GRID_ROWS) + "\r\n"
        )
        return 0
    if msg == WM_ERASEBKGND:
        return 1
    if msg == WM_PAINT:
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(wintypes.HWND(hwnd), ctypes.byref(ps))
        rect = wintypes.RECT()
        user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect))
        user32.FillRect(hdc, ctypes.byref(rect), user32.GetSysColorBrush(5))
        gdi32.SetBkMode(hdc, 1)
        for row, values in enumerate(GRID_ROWS):
            y = 4 + row * 20
            for col, value in enumerate(values):
                gdi32.TextOutW(hdc, 6 + col * 110, y, value, len(value))
            gdi32.MoveToEx(hdc, 0, y + 17, None)
            gdi32.LineTo(hdc, rect.right, y + 17)
        user32.EndPaint(wintypes.HWND(hwnd), ctypes.byref(ps))
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


# --- section 10 item 4: superclassed EDIT, plain and data-bound ----------

_EDIT_PROC = ctypes.c_void_p(0)


def _superclass_edit(new_name: str, proc) -> None:
    """Register `new_name` as EDIT with our procedure in front of its own.

    This is what a toolkit does to a native control, and it is why these
    fields behave like an EDIT for every message we do not intercept.
    """
    global _EDIT_PROC
    info = WNDCLASSEXW()
    info.cbSize = ctypes.sizeof(WNDCLASSEXW)
    if not user32.GetClassInfoExW(None, "EDIT", ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not _EDIT_PROC:
        _EDIT_PROC = ctypes.cast(info.lpfnWndProc, ctypes.c_void_p)
    info.cbSize = ctypes.sizeof(WNDCLASSEXW)
    info.lpfnWndProc = proc
    info.hInstance = INSTANCE
    info.lpszClassName = new_name
    if not user32.RegisterClassExW(ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())


def _swallow(hwnd, msg, wparam) -> bool:
    """Whether to drop this keystroke before the EDIT can complain about it.

    Two cases, both of which a real single-line EDIT answers with the system
    beep: a character arriving at a full field, and Return or Escape, which
    a single-line edit has nothing to do with. The truncation is real
    behaviour worth reproducing -- the beep is not observable to a driver,
    and a suite that sounds it dozens of times is unusable next to a person
    trying to work.
    """
    if msg != WM_CHAR:
        return False
    if wparam in (0x0D, 0x1B):  # Return, Escape
        return True
    return _text_length(hwnd) >= FIELD_CAPACITY


def _text_length(hwnd: int) -> int:
    return user32.GetWindowTextLengthW(wintypes.HWND(hwnd))


def _plain_edit_proc(hwnd, msg, wparam, lparam):
    """Superclassed, but with no binding behind it."""
    if _swallow(hwnd, msg, wparam):
        return 0
    return user32.CallWindowProcW(_EDIT_PROC, hwnd, msg, wparam, lparam)


def _bound_edit_proc(hwnd, msg, wparam, lparam):
    """A field whose *bound value* only commits through the keyboard path.

    This is the whole `set_text` question, made observable. The control's
    displayed text and the value the application has actually accepted are
    two different things, and a caller who reads the display back has no
    idea which one they are looking at.

    A character arriving as WM_CHAR is a keystroke, so the binding commits.
    WM_SETTEXT replaces the display without the toolkit's keyboard path ever
    running, so the binding does not -- the field shows the new text while
    the application still holds the old value. Whether a real toolkit
    behaves this way is exactly what was unverified; this reproduces the
    hazardous case so a driver can be built that survives it.
    """
    if _swallow(hwnd, msg, wparam):
        return 0
    result = user32.CallWindowProcW(_EDIT_PROC, hwnd, msg, wparam, lparam)
    if msg == WM_CHAR:
        _commit_bound_value(hwnd)
    return result


def _commit_bound_value(hwnd: int) -> None:
    value = _text_of(hwnd)
    _STATE["bound_value"] = value
    mirror = _STATE.get("bound_mirror")
    if mirror:
        user32.SetWindowTextW(wintypes.HWND(mirror), f"committed:{value}")


# --- the shell: pages, modal, foreground grab ---------------------------

def _main_proc(hwnd, msg, wparam, lparam):
    if msg == WM_FIXTURE_CURRENT_PAGE:
        return _STATE.get("page_index", 0)
    if msg == WM_TIMER:
        if wparam == 1:
            # Section 10 item 7: a modal that appears mid-run.
            user32.KillTimer(wintypes.HWND(hwnd), ctypes.c_void_p(1))
            _show_modal()
            return 0
        if wparam == 2:
            user32.KillTimer(wintypes.HWND(hwnd), ctypes.c_void_p(2))
            user32.SetForegroundWindow(wintypes.HWND(hwnd))
            return 0
    if msg == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _modal_proc(hwnd, msg, wparam, lparam):
    if msg == WM_LBUTTONUP:
        # Dismissing it re-enables the owner, which is what makes the
        # watchdog's job finite.
        user32.EnableWindow(wintypes.HWND(_STATE["main"]), True)
        user32.ShowWindow(wintypes.HWND(hwnd), 0)
        _STATE["modal_visible"] = False
        return 0
    if msg == WM_PAINT:
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(wintypes.HWND(hwnd), ctypes.byref(ps))
        rect = wintypes.RECT()
        user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect))
        user32.FillRect(hdc, ctypes.byref(rect), user32.GetSysColorBrush(5))
        gdi32.SetBkMode(hdc, 1)
        text = "Click anywhere to dismiss"
        gdi32.TextOutW(hdc, 10, 40, text, len(text))
        user32.EndPaint(wintypes.HWND(hwnd), ctypes.byref(ps))
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _show_modal() -> None:
    modal = _STATE["modal"]
    user32.EnableWindow(wintypes.HWND(_STATE["main"]), False)
    user32.ShowWindow(wintypes.HWND(modal), SW_SHOWNOACTIVATE)
    _STATE["modal_visible"] = True


def _label_proc(hwnd, msg, wparam, lparam):
    """A vendor-class label: paints its own caption, exposes no pattern.

    Deliberately not a STATIC. The HWND-to-UIA bridge understands a STATIC
    and gives it a pattern; it can say nothing about a class it has never
    heard of, which is the whole reason a Profile L1 tree reads as a field
    of bare panes.
    """
    if msg == WM_ERASEBKGND:
        return 1
    if msg == WM_PAINT:
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(wintypes.HWND(hwnd), ctypes.byref(ps))
        rect = wintypes.RECT()
        user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect))
        user32.FillRect(hdc, ctypes.byref(rect),
                        user32.GetSysColorBrush(COLOR_BTNFACE))
        gdi32.SetBkMode(hdc, 1)
        caption = _text_of(hwnd)
        gdi32.TextOutW(hdc, 2, 3, caption, len(caption))
        user32.EndPaint(wintypes.HWND(hwnd), ctypes.byref(ps))
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _register(name: str, proc) -> None:
    cls = WNDCLASSEXW()
    cls.cbSize = ctypes.sizeof(WNDCLASSEXW)
    cls.lpfnWndProc = proc
    cls.hInstance = INSTANCE
    cls.hbrBackground = user32.GetSysColorBrush(COLOR_BTNFACE)
    cls.lpszClassName = name
    if not user32.RegisterClassExW(ctypes.byref(cls)):
        raise ctypes.WinError(ctypes.get_last_error())


def build(options) -> dict:
    procs = [WNDPROC(_main_proc), WNDPROC(_button_proc), WNDPROC(_grid_proc),
             WNDPROC(_modal_proc), WNDPROC(_plain_edit_proc),
             WNDPROC(_bound_edit_proc)]
    _PROCS.extend(procs)
    main_p, button_p, grid_p, modal_p, plain_p, bound_p = procs

    label_p = WNDPROC(_label_proc)
    _PROCS.append(label_p)
    for name, proc in ((MAIN_CLASS, main_p), (PAGE_CLASS, main_p),
                       (BUTTON_CLASS, button_p), (GRID_CLASS, grid_p),
                       (MODAL_CLASS, modal_p), (CAPTION_CLASS, label_p),
                       (VALUE_CLASS, label_p)):
        _register(name, proc)
    _superclass_edit(PLAIN_EDIT_CLASS, plain_p)
    _superclass_edit(BOUND_EDIT_CLASS, bound_p)

    x = OFFSCREEN if options.offscreen else 140
    style = WS_OVERLAPPEDWINDOW | WS_VISIBLE
    ex = (WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW) if options.offscreen else 0
    main = user32.CreateWindowExW(ex, MAIN_CLASS, "Ghostdriver Fixture",
                                  style, x, x, 640, 460, None, None,
                                  INSTANCE, None)
    if not main:
        raise ctypes.WinError(ctypes.get_last_error())
    _STATE["main"] = main
    _STATE["grab_after_ms"] = options.grab_foreground_after
    _STATE["grid_copies"] = options.grid_copies

    def child(cls, text, sx, sy, w, h, parent=main, extra=0, exstyle=0):
        hwnd = user32.CreateWindowExW(
            exstyle, cls, text, WS_CHILD | WS_VISIBLE | extra,
            sx, sy, w, h, parent, None, INSTANCE, None)
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        return hwnd

    # Section 10 item 6: two pages, stacked, with buttons carrying identical
    # captions at identical rectangles. Only an ancestor tells them apart --
    # coordinates cannot, and neither can a caption.
    pages, page_buttons = [], []
    for index, label in enumerate(("Operations", "Components")):
        page = child(PAGE_CLASS, label, 10, 40, 610, 200)
        if index:
            user32.ShowWindow(wintypes.HWND(page), 0)
        pages.append(page)
        page_buttons.append([
            child(BUTTON_CLASS, "Apply", 12, 12, 110, 26, parent=page),
            child(BUTTON_CLASS, "Reset", 132, 12, 110, 26, parent=page),
        ])
        child(GRID_CLASS, "", 12, 50, 580, 130, parent=page)

    toolbar = [child(BUTTON_CLASS, cap, 12 + i * 130, 8, 120, 26)
               for i, cap in enumerate(("Expand All", "Collapse All",
                                        "Complete Task"))]

    # The detail panel: rows of caption/value pairs, each its own window,
    # which is what makes this tree shaped like the profile it reproduces.
    detail = child(PAGE_CLASS, "Detail", 10, 250, 610, 70)
    for row, (caption, value) in enumerate(DETAIL_FIELDS):
        column, line = divmod(row, 10)
        child(CAPTION_CLASS, caption, 8 + column * 300, 4 + line * 6, 130, 6,
              parent=detail)
        child(VALUE_CLASS, value, 142 + column * 300, 4 + line * 6, 150, 6,
              parent=detail)

    plain = child(PLAIN_EDIT_CLASS, "plain text", 90, 256, 220, 22,
                  extra=WS_BORDER, exstyle=WS_EX_CLIENTEDGE)
    bound = child(BOUND_EDIT_CLASS, "PART-0001", 90, 288, 220, 22,
                  extra=WS_BORDER, exstyle=WS_EX_CLIENTEDGE)
    mirror = child("STATIC", "committed:PART-0001", 330, 288, 280, 22)
    # A password field, because a sign-in screen is part of what this class
    # of target looks like and it behaves unlike every other control here:
    # the system refuses to hand its contents to another process at all.
    secret = child("EDIT", "hunter2", 330, 256, 200, 22,
                   extra=WS_BORDER | ES_PASSWORD, exstyle=WS_EX_CLIENTEDGE)
    status = child("STATIC", "clicks=0 last=", 12, 330, 600, 22)
    _STATE.update(bound_mirror=mirror, status=status,
                  bound_value="PART-0001", page_index=0)

    modal = user32.CreateWindowExW(
        WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW, MODAL_CLASS,
        "Confirm Delete Record", WS_OVERLAPPEDWINDOW,
        x + 80, x + 80, 300, 140, main, None, INSTANCE, None)
    _STATE["modal"] = modal

    user32.ShowWindow(wintypes.HWND(main),
                      SW_SHOWNOACTIVATE if options.offscreen
                      else SW_SHOWNORMAL)
    if options.modal_after:
        user32.SetTimer(wintypes.HWND(main), ctypes.c_void_p(1),
                        options.modal_after, None)

    return {
        "pid": os.getpid(),
        "main": main,
        "pages": pages,
        "page_buttons": page_buttons,
        "toolbar": toolbar,
        "grid_class": GRID_CLASS,
        "button_class": BUTTON_CLASS,
        "plain_edit": plain,
        "password": secret,
        "bound_edit": bound,
        "bound_mirror": mirror,
        "status": status,
        "modal": modal,
    }


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onscreen", dest="offscreen", action="store_false",
                        help="Show the window normally. Off by default so a "
                             "test run does not disturb the desktop.")
    parser.add_argument("--grab-foreground-after", type=int, default=0,
                        metavar="MS",
                        help="Pull the window to the foreground this long "
                             "after a click. 0 disables it.")
    parser.add_argument("--grid-no-copy", dest="grid_copies",
                        action="store_false",
                        help="Make the grid ignore WM_COPY, so the probe's "
                             "honest 'no route works' verdict can be tested.")
    parser.add_argument("--modal-after", type=int, default=0, metavar="MS",
                        help="Raise a modal dialog this long after start. "
                             "0 disables it.")
    parser.set_defaults(offscreen=True, grid_copies=True)
    options = parser.parse_args(argv)

    handles = build(options)
    print(json.dumps(handles), flush=True)

    message = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))


if __name__ == "__main__":
    main()
