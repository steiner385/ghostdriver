"""Screenshots of a window, without bringing it to the front.

The obvious implementation -- read the screen where the window is -- is
wrong here twice over. It captures whatever is on top of the window rather
than the window, and getting the window on top means taking the foreground,
which is the one thing this tool exists not to do.

`PrintWindow` asks the window to render itself into a bitmap we supply. It
works on a window that is behind others, and on one that is not on screen at
all, and it involves no activation. What it cannot do is render a *minimized*
window, whose client area has no valid contents -- that case is reported
rather than returned as a blank image.

Output is PNG, encoded here rather than by a dependency: the only thing
needed is a single RGB image, and zlib plus a CRC is the whole of it.
"""

import ctypes
import struct
import zlib
from ctypes import wintypes

from . import winapi

gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

#: Renders the whole window including parts an ordinary PrintWindow skips.
#: Needed for controls that draw through a compositor rather than in
#: response to WM_PRINT.
PW_RENDERFULLCONTENT = 0x00000002

SRCCOPY = 0x00CC0020
BI_RGB = 0
DIB_RGB_COLORS = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


user32 = winapi.user32
user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.GetWindowDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.GetDIBits.argtypes = [
    wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
    ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.BitBlt.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
]
gdi32.BitBlt.restype = wintypes.BOOL


def _why() -> str:
    """The OS's own account of the last failure, if it has one.

    Added after a capture failed once in a full suite run and could not be
    reproduced -- roughly fourteen hundred attempts across both the backend
    and the tool, under the same concurrent load, all of them fine. When a
    fault will not come back, the next best thing is to make sure the next
    occurrence explains itself rather than costing another search.

    These three calls can fail for reasons entirely outside this process:
    desktop resource pressure, a target rendering on another thread, a
    window torn down between the check and the call. "could not obtain a
    device context" says none of that; error 8 (not enough memory) or 1400
    (invalid window handle) says most of it.
    """
    code = ctypes.get_last_error()
    if not code:
        return ""
    try:
        return f" (win32 error {code}: {ctypes.WinError(code).strerror})"
    except Exception:
        return f" (win32 error {code})"


class CaptureError(RuntimeError):
    """A capture that could not be taken, with the reason it could not."""


def _png(width: int, height: int, rgb: bytes) -> bytes:
    """Encode raw RGB rows as a PNG.

    Hand-rolled rather than pulled in as a dependency: this needs one colour
    type, no interlacing and no palette, which is a few lines of zlib and
    CRC. A capture path that drags in an imaging library is a capture path
    that fails to install.
    """
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)  # filter type 0 (None) for every scanline
        raw += rgb[y * stride:(y + 1) * stride]

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )


def capture_window(
    hwnd: int, *, region: tuple[int, int, int, int] | None = None
) -> tuple[bytes, int, int]:
    rgb, out_w, out_h = render_pixels(hwnd, region=region)
    return _png(out_w, out_h, rgb), out_w, out_h


def render_pixels(
    hwnd: int, *, region: tuple[int, int, int, int] | None = None
) -> tuple[bytes, int, int]:
    """PNG bytes for `hwnd`, plus its width and height.

    `region` is a (left, top, right, bottom) rectangle in *screen*
    coordinates, cropped to the window. It is expressed that way because
    that is the form every rect in this tool already takes -- an element's
    rect, or a surface region's -- so a caller can capture exactly the
    region a map named without converting anything.

    Coordinates are whatever the target's DPI mode reports. A DPI-unaware
    target is virtualized by Windows, so its rects and its captures are in
    the same virtualized space and agree with each other; they will not
    agree with a physical-pixel screenshot taken by something else.
    """
    if not user32.IsWindow(wintypes.HWND(hwnd)):
        raise CaptureError(f"0x{hwnd:08X} is not a window")
    if user32.IsIconic(wintypes.HWND(hwnd)):
        # A minimized window has no valid client area. PrintWindow returns
        # success and an empty bitmap, so this has to be caught here or the
        # caller gets a blank image and no reason for it.
        # Named, because a full-suite run has twice found a fresh fixture
        # window minimized that nothing in the suite minimized; the class
        # is the first half of the answer to "which window, and whose".
        raise CaptureError(
            f"0x{hwnd:08X} ({winapi.class_name(hwnd)}) is minimized and has "
            "nothing to render; restore it first"
        )

    left, top, right, bottom = winapi.window_rect(hwnd)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        raise CaptureError(f"0x{hwnd:08X} has an empty rectangle")

    crop = (0, 0, width, height)
    if region is not None:
        r_left, r_top, r_right, r_bottom = region
        crop = (
            max(0, r_left - left),
            max(0, r_top - top),
            min(width, r_right - left),
            min(height, r_bottom - top),
        )
        if crop[2] <= crop[0] or crop[3] <= crop[1]:
            raise CaptureError(
                f"region {region} does not overlap the window at "
                f"{(left, top, right, bottom)}"
            )

    window_dc = user32.GetWindowDC(wintypes.HWND(hwnd))
    if not window_dc:
        raise CaptureError(
            "could not obtain a device context for the window" + _why()
        )

    memory_dc = bitmap = previous = None
    try:
        memory_dc = gdi32.CreateCompatibleDC(window_dc)
        bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
        if not memory_dc or not bitmap:
            raise CaptureError(
                "could not allocate a bitmap for the capture"
                f" ({width}x{height})" + _why()
            )
        previous = gdi32.SelectObject(memory_dc, bitmap)

        if not user32.PrintWindow(  # noqa: SIM102 -- the comment between the two tests is the point
            wintypes.HWND(hwnd), memory_dc, PW_RENDERFULLCONTENT
        ):
            # Some windows refuse PrintWindow. Copying their own DC is the
            # fallback; it still never activates, and still reads the
            # window rather than the screen in front of it.
            if not gdi32.BitBlt(
                memory_dc, 0, 0, width, height, window_dc, 0, 0, SRCCOPY
            ):
                raise CaptureError(
                    "the window rendered neither through PrintWindow nor a "
                    "device-context copy" + _why()
                )

        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        # Negative height requests a top-down bitmap, so rows arrive in the
        # order PNG wants and nothing has to be reversed afterwards.
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = BI_RGB

        buffer = ctypes.create_string_buffer(width * height * 4)
        if not gdi32.GetDIBits(
            memory_dc, bitmap, 0, height, buffer,
            ctypes.byref(info), DIB_RGB_COLORS,
        ):
            raise CaptureError(
                "could not read the captured bitmap's pixels" + _why()
            )

        pixels = buffer.raw
        c_left, c_top, c_right, c_bottom = crop
        out_w, out_h = c_right - c_left, c_bottom - c_top
        rgb = bytearray(out_w * out_h * 3)
        at = 0
        for y in range(c_top, c_bottom):
            row = y * width * 4
            for x in range(c_left, c_right):
                # GetDIBits hands back BGRA; PNG truecolour wants RGB.
                blue, green, red = pixels[row + x * 4: row + x * 4 + 3]
                rgb[at] = red
                rgb[at + 1] = green
                rgb[at + 2] = blue
                at += 3
        return bytes(rgb), out_w, out_h
    finally:
        if previous:
            gdi32.SelectObject(memory_dc, previous)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(wintypes.HWND(hwnd), window_dc)


def ink_fraction(hwnd: int, *, region: tuple[int, int, int, int] | None = None,
                 stride: int = 2) -> float:
    """How much of the window's rendering is not its background colour.

    A control that answers "" to a text query and paints rows is one whose
    read path does not work, not one that is empty; a session reported a
    success as a failure that way (D66). The most common colour is taken
    as the background; every pixel of another colour is ink. Sampled every
    `stride` pixels, since the question is "blank or not", not "what".
    """
    rgb, width, height = render_pixels(hwnd, region=region)
    counts: dict[bytes, int] = {}
    total = 0
    for y in range(0, height, stride):
        row = y * width * 3
        for x in range(0, width, stride):
            pixel = rgb[row + x * 3: row + x * 3 + 3]
            counts[pixel] = counts.get(pixel, 0) + 1
            total += 1
    if not total:
        return 0.0
    return round(1.0 - max(counts.values()) / total, 3)
