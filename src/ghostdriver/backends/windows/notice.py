"""A notice on the operator's screen, for the one tool that needs a person.

`await_human` asks the operator to do something and waits for the target
to show it done. In a chat client the ask can end up folded inside a tool
call the person has to expand to read, and while the call blocks nobody
is told anything. So the ask is also put where a person is looking: a
small window in the corner of their screen, always on top, that says
what is being waited for and goes away when the wait ends.

It obeys the rule everything else here obeys: it never takes focus. It is
created with WS_EX_NOACTIVATE, shown with SW_SHOWNOACTIVATE, and lives on
its own thread with its own message loop so the waiting tool is not the
one pumping it. It is a tool window, so it does not appear in the taskbar,
and it is topmost, so a full-screen application does not hide it.
"""

import ctypes
import threading
from ctypes import wintypes

from . import winapi

user32 = winapi.user32
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

CLASS_NAME = "GhostdriverOperatorNotice"
TITLE = "ghostdriver is waiting for you"

WS_POPUP = 0x80000000
WS_BORDER = 0x00800000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
SW_SHOWNOACTIVATE = 4
WM_DESTROY = 0x0002
WM_PAINT = 0x000F
WM_CLOSE = 0x0010
WM_MOUSEACTIVATE = 0x0021
MA_NOACTIVATE = 3
SPI_GETWORKAREA = 0x0030
DT_WORDBREAK = 0x0010
DT_CALCRECT = 0x0400
COLOR_INFOBK = 24
COLOR_INFOTEXT = 23
WIDTH, MARGIN, PAD = 420, 16, 14

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HANDLE),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HANDLE),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", wintypes.HDC), ("fErase", wintypes.BOOL), ("rcPaint", wintypes.RECT),
                ("fRestore", wintypes.BOOL), ("fIncUpdate", wintypes.BOOL),
                ("rgbReserved", ctypes.c_byte * 32)]


user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int,
                             ctypes.POINTER(wintypes.RECT), wintypes.UINT]
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

_registered = False
_proc_ref = None  # keeps the callback alive for the class's lifetime


def _wndproc_factory(text_holder: dict):
    def proc(hwnd, msg, wparam, lparam):
        if msg == WM_MOUSEACTIVATE:
            # A click on the notice must not activate it either.
            return MA_NOACTIVATE
        if msg == WM_PAINT:
            ps = PAINTSTRUCT()
            hdc = user32.BeginPaint(wintypes.HWND(hwnd), ctypes.byref(ps))
            rect = wintypes.RECT()
            user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect))
            user32.FillRect(hdc, ctypes.byref(rect), user32.GetSysColorBrush(COLOR_INFOBK))
            gdi32.SetBkMode(hdc, 1)
            gdi32.SetTextColor(hdc, user32.GetSysColor(COLOR_INFOTEXT))
            inner = wintypes.RECT(rect.left + PAD, rect.top + PAD, rect.right - PAD, rect.bottom - PAD)
            body = text_holder["text"]
            user32.DrawTextW(hdc, body, -1, ctypes.byref(inner), DT_WORDBREAK)
            user32.EndPaint(wintypes.HWND(hwnd), ctypes.byref(ps))
            return 0
        if msg == WM_CLOSE:
            user32.DestroyWindow(wintypes.HWND(hwnd))
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
    return proc


def _register(text_holder: dict) -> None:
    global _registered, _proc_ref
    if _registered:
        return
    _proc_ref = WNDPROC(_wndproc_factory(text_holder))
    wc = WNDCLASSW()
    wc.lpfnWndProc = _proc_ref
    wc.hInstance = kernel32.GetModuleHandleW(None)
    wc.hCursor = user32.LoadCursorW(None, wintypes.LPCWSTR(32512))  # IDC_ARROW
    wc.lpszClassName = CLASS_NAME
    if not user32.RegisterClassW(ctypes.byref(wc)):
        raise ctypes.WinError(ctypes.get_last_error())
    _registered = True


#: Shared by every notice: the class is registered once per process, and
#: its window procedure reads the text from here.
_TEXT: dict = {"text": ""}


class OperatorNotice:
    """Show `ask` in the corner of the operator's screen until stopped."""

    def __init__(self, ask: str, *, heading: str = TITLE):
        self.ask = ask
        self.heading = heading
        self.hwnd: int = 0
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._thread_id: int = 0

    @property
    def text(self) -> str:
        return (f"{self.heading}\n\n{self.ask}\n\n"
                "It continues on its own once the application shows this done.")

    def show(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="operator-notice")
        self._thread.start()
        self._ready.wait(timeout=3)

    def _run(self) -> None:
        _TEXT["text"] = self.text
        _register(_TEXT)
        self._thread_id = kernel32.GetCurrentThreadId()
        work = wintypes.RECT()
        user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(work), 0)
        # Size to the wrapped text, then sit in the bottom-right of the work area.
        hdc = user32.GetDC(None)
        measure = wintypes.RECT(0, 0, WIDTH - 2 * PAD, 0)
        user32.DrawTextW(hdc, self.text, -1, ctypes.byref(measure), DT_WORDBREAK | DT_CALCRECT)
        user32.ReleaseDC(None, hdc)
        height = (measure.bottom - measure.top) + 2 * PAD + 2
        x = work.right - WIDTH - MARGIN
        y = work.bottom - height - MARGIN
        hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, CLASS_NAME, TITLE,
            WS_POPUP | WS_BORDER, x, y, WIDTH, height, None, None,
            kernel32.GetModuleHandleW(None), None)
        if not hwnd:
            self._ready.set()
            return
        self.hwnd = int(hwnd)
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self.hwnd = 0

    def close(self) -> None:
        if self.hwnd:
            user32.PostMessageW(wintypes.HWND(self.hwnd), WM_CLOSE, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=2)

    def __enter__(self) -> "OperatorNotice":
        self.show()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
