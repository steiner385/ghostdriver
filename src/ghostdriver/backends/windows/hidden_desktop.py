"""The `hidden_desktop` isolation strategy: a structural guarantee.

`minimized` keeps the target off screen and watches for it to escape --
observational, and the watchdog exists because a single trial proves
nothing. `hidden_desktop` removes the thing being watched for: a window on a
desktop that is not the input desktop has no foreground to steal. The
guarantee stops being "we put it back fast enough" and becomes "there is
nowhere for it to go."

**The one hard rule, learned by measurement.** A desktop is bound to a
thread, not a process. Every Win32 call that touches the target -- enumerate,
read, post a message, PrintWindow -- must run on a thread that has called
`SetThreadDesktop` onto the hidden desktop first. A call from any other
thread simply does not see the target's windows. So this strategy is not a
handle you hold; it is a thread you hand work to. `run` marshals a callable
onto the desktop-bound worker and returns its result, and everything the
server does to a hidden-desktop target goes through it.

Measured against the fixture: launched onto the desktop, the worker thread
saw all ten top-level windows and fifty-eight nodes, read control text,
posted a click that registered, and captured the window -- while the Default
desktop saw zero of the target's windows and its foreground never moved.

**What this does not solve**, and says so rather than pretending. Interactive
login needs the operator to see the target, which means a `SwitchDesktop`
that replaces their whole screen -- the spec's known limitation. And the
target is launched here, which is a capability the rest of the tool has
never had: a session that attaches to an already-running process cannot
retroactively move it to another desktop, so `hidden_desktop` is
launch-only, and `attach` on a running pid raises `Unsupported`.
"""

import ctypes
import queue
import threading
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, TypeVar

from . import winapi

user32 = winapi.user32
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

T = TypeVar("T")

GENERIC_ALL = 0x10000000
STARTF_USESTDHANDLES = 0x00000100
HANDLE_FLAG_INHERIT = 0x00000001
#: Where a named desktop lives. WinSta0 is the interactive window station;
#: a desktop under it is real but only visible when it is the input desktop,
#: which this one never becomes.
WINDOW_STATION = "WinSta0"


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD),
                ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL)]


user32.CreateDesktopW.restype = wintypes.HANDLE
user32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
                                  ctypes.c_void_p, wintypes.DWORD,
                                  wintypes.DWORD, ctypes.c_void_p]
user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
user32.SetThreadDesktop.restype = wintypes.BOOL
user32.CloseDesktop.argtypes = [wintypes.HANDLE]
user32.CloseDesktop.restype = wintypes.BOOL
kernel32.CreatePipe.argtypes = [
    ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE),
    ctypes.POINTER(SECURITY_ATTRIBUTES), wintypes.DWORD]
kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                          wintypes.DWORD]
kernel32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                              ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
kernel32.CreateProcessW.argtypes = [
    wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
    wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
    ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]
kernel32.CreateProcessW.restype = wintypes.BOOL
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class Unsupported(RuntimeError):
    """Raised when a strategy cannot do what was asked of it."""


@dataclass
class _Job:
    fn: Callable[[], object]
    result: "queue.Queue"


class HiddenDesktop:
    """A named desktop, and the one thread allowed to touch what runs on it.

    Not reusable and not thread-safe by design: a strategy instance owns one
    desktop and one worker, and work reaches the target only through `run`.
    """

    def __init__(self, name: str = "ghostdriver") -> None:
        self.name = name
        self._desktop = None
        self._jobs: "queue.Queue[_Job | None]" = queue.Queue()
        self._worker: threading.Thread | None = None
        self._ready = threading.Event()
        self._bind_error: str = ""

    # -- lifecycle --------------------------------------------------------

    def prepare(self) -> None:
        """Create the desktop and start the thread bound to it.

        The worker binds *itself* to the desktop and then serves jobs,
        because SetThreadDesktop affects only the calling thread -- binding
        it from here would bind the wrong thread.
        """
        self._desktop = user32.CreateDesktopW(
            self.name, None, None, 0, GENERIC_ALL, None)
        if not self._desktop:
            raise OSError(f"CreateDesktop failed: "
                          f"{ctypes.WinError(ctypes.get_last_error())}")
        self._worker = threading.Thread(target=self._serve, daemon=True)
        self._worker.start()
        self._ready.wait(timeout=5)
        if self._bind_error:
            raise OSError(self._bind_error)

    def _serve(self) -> None:
        if not user32.SetThreadDesktop(self._desktop):
            self._bind_error = (
                "SetThreadDesktop failed: "
                f"{ctypes.WinError(ctypes.get_last_error())}")
            self._ready.set()
            return
        self._ready.set()
        while True:
            job = self._jobs.get()
            if job is None:
                return
            try:
                job.result.put(("ok", job.fn()))
            except Exception as exc:  # marshalled back, not swallowed
                job.result.put(("error", exc))

    def run(self, fn: Callable[[], T]) -> T:
        """Run `fn` on the desktop-bound thread and return its result.

        The whole point: any operation against a hidden-desktop target is
        handed here, because only this thread can see the target's windows.
        An exception inside `fn` is re-raised in the caller, so this is
        transparent to use.
        """
        if self._worker is None:
            raise RuntimeError("prepare() has not been called")
        result: "queue.Queue" = queue.Queue()
        self._jobs.put(_Job(fn=fn, result=result))
        status, payload = result.get()
        if status == "error":
            raise payload
        return payload

    def launch(self, command: list[str]) -> int:
        """Start `command` on the hidden desktop; return its announced pid.

        The child is told which desktop to start on through STARTUPINFO, and
        its stdout is piped back so the *announced* pid is read rather than
        the launcher's -- the same launcher-stub problem the read-only tests
        have (a venv shim re-execs, and CreateProcess returns the shim).
        """
        sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
        read_end, write_end = wintypes.HANDLE(), wintypes.HANDLE()
        if not kernel32.CreatePipe(ctypes.byref(read_end),
                                   ctypes.byref(write_end),
                                   ctypes.byref(sa), 0):
            raise OSError("CreatePipe failed")
        kernel32.SetHandleInformation(read_end, HANDLE_FLAG_INHERIT, 0)

        info = STARTUPINFOW()
        info.cb = ctypes.sizeof(info)
        info.lpDesktop = f"{WINDOW_STATION}\\{self.name}"
        info.dwFlags = STARTF_USESTDHANDLES
        info.hStdOutput = write_end
        info.hStdError = write_end
        pi = PROCESS_INFORMATION()
        line = " ".join(f'"{part}"' if " " in part else part
                        for part in command)
        if not kernel32.CreateProcessW(
                None, ctypes.create_unicode_buffer(line), None, None, True,
                0, None, None, ctypes.byref(info), ctypes.byref(pi)):
            kernel32.CloseHandle(write_end)
            kernel32.CloseHandle(read_end)
            raise OSError(f"CreateProcess failed: "
                          f"{ctypes.WinError(ctypes.get_last_error())}")
        kernel32.CloseHandle(write_end)
        self._process = pi.hProcess
        self._launcher_pid = pi.dwProcessId
        try:
            announced = self._read_announced_pid(read_end)
        finally:
            kernel32.CloseHandle(read_end)
        self.pid = announced
        return announced

    def _read_announced_pid(self, read_end) -> int:
        import json

        buf = ctypes.create_string_buffer(4096)
        got = wintypes.DWORD()
        data = b""
        while b"\n" not in data:
            if not kernel32.ReadFile(read_end, buf, 4095,
                                     ctypes.byref(got), None) or not got.value:
                break
            data += buf.raw[:got.value]
        try:
            return json.loads(data.split(b"\n")[0])["pid"]
        except Exception as exc:
            raise OSError(f"target did not announce a pid: {data[:120]!r}") \
                from exc

    def attach(self, pid: int) -> None:
        raise Unsupported(
            "hidden_desktop cannot adopt a running process: a window's "
            "desktop is fixed at creation, so a target already on the input "
            "desktop cannot be moved to a hidden one. Launch it instead")

    def teardown(self) -> None:
        if self._worker is not None:
            self._jobs.put(None)
            self._worker.join(timeout=5)
        proc = getattr(self, "_process", None)
        if proc:
            kernel32.TerminateProcess(proc, 0)
            kernel32.CloseHandle(proc)
        if self._desktop:
            user32.CloseDesktop(self._desktop)
            self._desktop = None
