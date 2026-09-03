"""Capturing a window without bringing it forward.

The fixture windows are deliberately off-screen and never activated, which
makes them the right subject: anything that only works by putting the
window in front of the operator fails here.
"""

import struct
import zlib

import pytest

from tests.conftest import on_windows

pytestmark = on_windows


def _decode(png: bytes):
    """Parse our own PNG with the stdlib, to prove it round-trips."""
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, ihdr = 8, b"", None
    while pos < len(png):
        length = struct.unpack(">I", png[pos:pos + 4])[0]
        tag = png[pos + 4:pos + 8]
        data = png[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", data)
        elif tag == b"IDAT":
            idat += data
        pos += 12 + length
    return ihdr, zlib.decompress(idat)


def test_an_offscreen_window_can_still_be_captured(win32_target):
    """PrintWindow renders the window itself, not the screen in front of
    it, which is why a window nobody can see is capturable at all."""
    from ghostdriver.backends.windows.capture import capture_window
    from ghostdriver.backends.windows.enumerate import top_level_windows

    hwnd = top_level_windows(win32_target)[0]
    png, width, height = capture_window(hwnd)

    assert width > 0 and height > 0
    ihdr, raw = _decode(png)
    assert (ihdr[0], ihdr[1]) == (width, height)
    assert ihdr[2] == 8 and ihdr[3] == 2, "8-bit truecolour"
    assert len(raw) == (width * 3 + 1) * height, "one filter byte per row"


def test_capture_does_not_activate_the_window(win32_target):
    """The whole point. If capturing took the foreground it would be
    unusable on a machine someone is working at."""
    import ctypes

    from ghostdriver.backends.windows.capture import capture_window
    from ghostdriver.backends.windows.enumerate import top_level_windows

    user32 = ctypes.WinDLL("user32")
    before = user32.GetForegroundWindow()

    hwnd = top_level_windows(win32_target)[0]
    capture_window(hwnd)

    assert user32.GetForegroundWindow() == before


def test_a_region_is_cropped_from_the_window(win32_target):
    """Regions are given in screen coordinates because that is the form
    every rect in this tool already takes -- an element's, or a surface
    region's -- so a caller can capture exactly what a map named."""
    from ghostdriver.backends.windows import winapi
    from ghostdriver.backends.windows.capture import capture_window
    from ghostdriver.backends.windows.enumerate import top_level_windows

    hwnd = top_level_windows(win32_target)[0]
    left, top, _, _ = winapi.window_rect(hwnd)
    region = (left + 10, top + 10, left + 60, top + 40)

    _, width, height = capture_window(hwnd, region=region)

    assert (width, height) == (50, 30)


def test_a_region_outside_the_window_is_refused(win32_target):
    """Returning an empty image would look like a capture that worked."""
    from ghostdriver.backends.windows.capture import CaptureError, capture_window
    from ghostdriver.backends.windows.enumerate import top_level_windows

    hwnd = top_level_windows(win32_target)[0]
    with pytest.raises(CaptureError, match="does not overlap"):
        capture_window(hwnd, region=(30000, 30000, 30100, 30100))


def test_a_minimized_window_is_refused_rather_than_returned_blank(
    minimized_target,
):
    """PrintWindow reports success on a minimized window and produces an
    empty bitmap, so without this the caller gets a blank image and no
    reason for it."""
    from ghostdriver.backends.windows.capture import CaptureError, capture_window

    _, owner, _, _ = minimized_target
    with pytest.raises(CaptureError, match="minimized"):
        capture_window(owner)


def test_a_dead_handle_is_refused(win32_target):
    from ghostdriver.backends.windows.capture import CaptureError, capture_window

    with pytest.raises(CaptureError, match="not a window"):
        capture_window(0xDEADBEEF)
