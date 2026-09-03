"""The routes to exact grid text, against a real window.

`ghostdriver.gridstrategy` decides the order and the verdict; this supplies
the two routes it can be handed. Each is a callable that tries one thing
and reports a `RouteResult`, and each is honest about what it cost.

**The focus route** posts `WM_SETFOCUS` to the region and re-scans the
accessibility surface beneath it, then posts `WM_KILLFOCUS` to undo the
notification. Posted, not `SetFocus`: focus is thread-bound and cannot be
set cross-process without `AttachThreadInput`, which is the kind of thing
that makes a driver visible. The control is told it has focus; whether it
believes that enough to populate its tree is the measurement.

**The clipboard route** is the one with a side effect, and the module is
built around not hiding that. The Windows clipboard is one shared resource
for the whole interactive session -- not per process, not per tool. So:

- the prior *text* is snapshotted and put back afterwards. Only text. A
  clipboard holding an image or files cannot be re-created from here, and
  the caveat says so rather than pretending the restore was total;
- the restore is not atomic. Anything that copies in the gap between
  snapshot and restore loses to the restore. Clipboard history and clipboard
  managers see the grid text regardless;
- nothing is read speculatively: the clipboard is read once, only after
  `WM_COPY` was posted, and only the *shape* of what came back (line count)
  leaves this module unless the caller asked for the text itself.

`WM_COPY` is posted, not sent -- it carries no pointer, so cross-process
posting is fine (contrast D19).
"""

import ctypes
import time
from ctypes import wintypes

from ...gridstrategy import RouteResult, Strategy, looks_like_a_grid
from ...model.window import WindowNode
from . import winapi
from .region import region_evidence

user32 = winapi.user32
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_SETFOCUS = 0x0007
WM_KILLFOCUS = 0x0008
WM_COPY = 0x0301
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL

#: How long to keep trying to open a clipboard another process holds. The
#: clipboard is opened for milliseconds at a time by whoever is using it;
#: a single failed OpenClipboard is contention, not absence.
OPEN_RETRIES = 20
OPEN_RETRY_S = 0.01

#: How long to wait for the control to answer WM_COPY. It is posted, so the
#: control handles it on its own thread when it gets to it.
COPY_TIMEOUT_S = 1.5

SHARED_CLIPBOARD_CAVEAT = (
    "the clipboard is shared by the whole session: its prior text was "
    "restored afterwards, but non-text content (images, files) cannot be "
    "restored from here, the restore is not atomic against anything else "
    "copying in the gap, and clipboard history saw the grid text"
)


class _Clipboard:
    """Open the clipboard with retries, and always close it."""

    def __enter__(self):
        for _ in range(OPEN_RETRIES):
            if user32.OpenClipboard(None):
                return self
            time.sleep(OPEN_RETRY_S)
        raise OSError("the clipboard is held by another process")

    def __exit__(self, *_):
        user32.CloseClipboard()


def read_clipboard_text() -> str | None:
    """The clipboard's text, or None if it holds none (or nothing at all)."""
    with _Clipboard():
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        locked = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(locked)
        finally:
            kernel32.GlobalUnlock(handle)


def write_clipboard_text(text: str | None) -> None:
    """Replace the clipboard with `text`, or empty it when `text` is None."""
    with _Clipboard():
        user32.EmptyClipboard()
        if text is None:
            return
        size = (len(text) + 1) * 2
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            raise OSError("could not allocate clipboard memory")
        locked = kernel32.GlobalLock(handle)
        ctypes.memmove(locked, ctypes.create_unicode_buffer(text), size)
        kernel32.GlobalUnlock(handle)
        # Ownership of the handle passes to the system on success.
        user32.SetClipboardData(CF_UNICODETEXT, handle)


def clipboard_holds_non_text() -> bool:
    """Whether restoring text alone would lose something.

    Checked before the copy so the caveat can say what was lost rather than
    guess. Any format that is not plain/unicode text counts.
    """
    with _Clipboard():
        # Formats: CF_TEXT=1, CF_UNICODETEXT=13, CF_OEMTEXT=7, CF_LOCALE=16
        # are all text-ish and re-derived from unicode text on set.
        fmt = 0
        text_like = {1, 7, 13, 16}
        user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
        user32.EnumClipboardFormats.restype = wintypes.UINT
        while True:
            fmt = user32.EnumClipboardFormats(fmt)
            if not fmt:
                return False
            if fmt not in text_like:
                return True


def focus_route(node: WindowNode) -> RouteResult:
    """Tell the region it has focus and see whether its tree fills in."""
    before = region_evidence(node).accessible_elements
    user32.PostMessageW(wintypes.HWND(node.handle), WM_SETFOCUS, 0, 0)
    time.sleep(0.3)
    try:
        after = region_evidence(node).accessible_elements
    finally:
        user32.PostMessageW(wintypes.HWND(node.handle), WM_KILLFOCUS, 0, 0)
    revealed = after - before
    return RouteResult(
        strategy=Strategy.ACCESSIBLE_ON_FOCUS,
        worked=revealed > 0,
        lines=after if revealed > 0 else 0,
        detail=(f"{before} accessible elements before focus, {after} after"),
    )


def copy_route(node: WindowNode, *, want_text: bool = False) -> RouteResult:
    """Ask the region to copy itself, read what it produced, put things back.

    `want_text` returns the copied rows in `detail` for a caller that is
    actually reading the grid. The probe leaves it False: a profile records
    that the route works and how many lines it gave, never the cells.
    """
    try:
        prior = read_clipboard_text()
        lossy = clipboard_holds_non_text()
        before_seq = user32.GetClipboardSequenceNumber()
    except OSError as exc:
        return RouteResult(strategy=Strategy.CLIPBOARD_COPY, worked=False,
                           detail=f"could not read the clipboard: {exc}")

    user32.PostMessageW(wintypes.HWND(node.handle), WM_COPY, 0, 0)

    text = None
    deadline = time.monotonic() + COPY_TIMEOUT_S
    while time.monotonic() < deadline:
        if user32.GetClipboardSequenceNumber() != before_seq:
            try:
                text = read_clipboard_text()
            except OSError:
                text = None
            break
        time.sleep(0.03)

    restored = True
    try:
        write_clipboard_text(prior)
    except OSError:
        restored = False

    caveat = SHARED_CLIPBOARD_CAVEAT
    if lossy:
        caveat += "; the clipboard held non-text content before, which is gone"
    if not restored:
        caveat += "; and the prior text could NOT be put back"

    ok, lines = looks_like_a_grid(text or "")
    return RouteResult(
        strategy=Strategy.CLIPBOARD_COPY,
        worked=ok,
        lines=lines,
        caveat=caveat,
        detail=(
            ((text or "") if want_text else f"{lines} line(s) of tab-delimited text")
            if ok else
            ("the control did not change the clipboard" if text is None
             else "the control copied something, but not grid-shaped text")
        ),
    )
