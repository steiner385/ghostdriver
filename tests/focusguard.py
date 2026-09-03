"""A foreground watch over the whole test run.

An operator watching the suite had their typing interrupted: fixtures meant
only to be *visible* were shown the ordinary, activating way, and Windows
allowed it because the test runner descends from whatever the operator was
typing into. Nothing in the suite asserted against that, so nothing caught
it before a person did.

This watches GetForegroundWindow for the whole session and records every
change whose window belongs to a process descended from this runner. The
operator changing windows themselves is not recorded -- their windows are
not ours. `tests/test_zz_focus_guard.py`, last in the run, asserts the
record is empty. Opt-in focus tests set GHOSTDRIVER_ALLOW_FOCUS_TESTS, and
the guard stands down under that flag because those tests take the
foreground on purpose.
"""

import ctypes
import os
import sys
import threading
import time

import psutil

POLL_S = 0.01


class ForegroundWatch:
    """Records foreground changes to windows of processes descended from us.

    `foreground` and `pid_of` are injectable so the recording logic can be
    tested with a fed sequence rather than by stealing a real operator's
    focus to prove the guard would notice.
    """

    def __init__(self, foreground=None, pid_of=None, class_of=None):
        self.taken: list[dict] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._me = os.getpid()
        self._foreground = foreground
        self._pid_of = pid_of
        self._class_of = class_of

    def start(self):
        if sys.platform != "win32":
            return
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="focus-guard")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _descends_from_me(self, pid: int) -> bool:
        try:
            proc = psutil.Process(pid)
            while proc is not None:
                if proc.pid == self._me:
                    return True
                proc = proc.parent()
        except psutil.Error:
            pass
        return False

    def observe(self, hwnd, last):
        """One poll step: record `hwnd` if it is new and one of ours."""
        if hwnd and hwnd != last:
            pid = self._pid_of(hwnd)
            if self._descends_from_me(pid):
                self.taken.append({
                    "at": time.time(), "hwnd": f"0x{hwnd:08X}",
                    "class": self._class_of(hwnd), "pid": pid,
                    "test": CURRENT.get("test", "(no test running)"),
                })
        return hwnd

    def _bind_win32(self):
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

        def pid_of(hwnd):
            pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return pid.value

        def class_of(hwnd):
            buf = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd, buf, 128)
            return buf.value

        self._foreground = self._foreground or user32.GetForegroundWindow
        self._pid_of = self._pid_of or pid_of
        self._class_of = self._class_of or class_of

    def _run(self):
        self._bind_win32()
        last = self._foreground()
        while not self._stop.is_set():
            last = self.observe(self._foreground(), last)
            time.sleep(POLL_S)


#: The test running now, kept current by the conftest hook.
CURRENT: dict[str, str] = {}
