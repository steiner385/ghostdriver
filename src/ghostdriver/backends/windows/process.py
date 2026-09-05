"""Facts about a target process.

Module listing goes through psutil's memory_maps, which reads the target's
own mappings. This matters: a 64-bit caller using the .NET Process.Modules
API against a 32-bit process gets only WOW64 stubs, which looks like a
process with six modules rather than a hundred.
"""

import ctypes
from ctypes import wintypes

import psutil

# ProcessFacts lives in the model layer so the Linux backend fills the same
# shape rather than keeping a copy that drifts. Imported (not redefined)
# here because this is where every Windows caller looks for it.
from ...model.process import ProcessFacts
from . import winapi

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

advapi32.OpenProcessToken.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)
]
advapi32.OpenProcessToken.restype = wintypes.BOOL

advapi32.GetTokenInformation.argtypes = [
    wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
advapi32.GetTokenInformation.restype = wintypes.BOOL

advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)

advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)

TOKEN_QUERY = 0x0008
TOKEN_INTEGRITY_LEVEL_CLASS = 25

INTEGRITY_RIDS = {
    0x0000: "untrusted",
    0x1000: "low",
    0x2000: "medium",
    0x3000: "high",
    0x4000: "system",
}

DPI_AWARENESS = {0: "unaware", 1: "system", 2: "per-monitor"}

MODULE_SUFFIXES = (".dll", ".bpl", ".exe", ".ocx", ".drv", ".cpl")


def list_modules(pid: int) -> list[str] | None:
    """Loaded module paths, or None when they could not be read at all.

    None and [] are different answers and must not be conflated. Toolkit
    inference treats an empty list as "no framework signature is present",
    which is a real finding about a statically linked target; if a refused
    handle or a dead process also produced [], the probe would report that
    same confident finding on no evidence whatsoever. This is the
    distinction `match_profile` already makes for the UIA assessment when
    it returns "indeterminate" rather than guessing.
    """
    try:
        maps = psutil.Process(pid).memory_maps()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return None
    seen: list[str] = []
    for entry in maps:
        path = entry.path
        if path.lower().endswith(MODULE_SUFFIXES) and path not in seen:
            seen.append(path)
    return seen


def _is_wow64(handle) -> bool | None:
    result = wintypes.BOOL()
    try:
        if not winapi.kernel32.IsWow64Process(handle, ctypes.byref(result)):
            return None
    except (AttributeError, OSError):
        return None
    return bool(result.value)


def _dpi_awareness(handle) -> str:
    try:
        shcore = ctypes.WinDLL("shcore")
        # AttributeError, not just OSError: a shcore.dll without this export
        # raises when ctypes resolves the symbol on attribute access. That is
        # an answer we do not have, not a crash to propagate.
        shcore.GetProcessDpiAwareness.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(ctypes.c_int)
        ]
        shcore.GetProcessDpiAwareness.restype = ctypes.c_long
    except (OSError, AttributeError):
        return "unknown"
    value = ctypes.c_int()
    try:
        if shcore.GetProcessDpiAwareness(handle, ctypes.byref(value)) != 0:
            return "unknown"
    except (OSError, AttributeError):
        return "unknown"
    return DPI_AWARENESS.get(value.value, "unknown")


def _integrity_level(handle) -> str | None:
    """Read the token's mandatory-label RID. Best effort."""
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(handle, TOKEN_QUERY, ctypes.byref(token)):
        return None
    try:
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(
            token, TOKEN_INTEGRITY_LEVEL_CLASS, None, 0, ctypes.byref(size)
        )
        if size.value == 0:
            return None
        buf = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
            token, TOKEN_INTEGRITY_LEVEL_CLASS, buf, size, ctypes.byref(size)
        ):
            return None
        # TOKEN_MANDATORY_LABEL begins with SID_AND_ATTRIBUTES, whose first
        # member is a PSID.
        sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
        count = advapi32.GetSidSubAuthorityCount(sid)[0]
        if count == 0:
            # A well-formed mandatory-label SID always carries at least one
            # sub-authority. Treat a degenerate one as unreadable rather than
            # indexing past the end: count - 1 would wrap to 0xFFFFFFFF under
            # the DWORD argtype and read out of bounds.
            return None
        rid = advapi32.GetSidSubAuthority(sid, count - 1)[0]
        return INTEGRITY_RIDS.get(rid, f"0x{rid:04X}")
    except OSError:
        return None
    finally:
        winapi.kernel32.CloseHandle(token)


def process_facts(pid: int) -> ProcessFacts:
    modules = list_modules(pid)
    try:
        executable = psutil.Process(pid).exe()
    except (psutil.Error, OSError):
        executable = ""

    handle = winapi.kernel32.OpenProcess(
        winapi.PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    wow64, integrity, dpi = None, None, "unknown"
    if handle:
        try:
            wow64 = _is_wow64(handle)
            integrity = _integrity_level(handle)
            dpi = _dpi_awareness(handle)
        finally:
            winapi.kernel32.CloseHandle(handle)

    if wow64 is None:
        bitness = "unknown"
    else:
        bitness = "x86" if wow64 else "x64"

    return ProcessFacts(
        pid=pid, executable=executable, bitness=bitness,
        wow64=bool(wow64), integrity_level=integrity,
        dpi_awareness=dpi, modules=modules or [],
        modules_readable=modules is not None,
    )


# --- the process tree, cheaply ------------------------------------------------

TH32CS_SNAPPROCESS = 0x00000002


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260),
    ]


def parent_map() -> dict[int, int]:
    """pid -> parent pid for every process, from one toolhelp snapshot.

    One kernel call and a walk over the entries, with no handle opened per
    process. Measured against the alternative: psutil's recursive children
    walk opens every process on the machine to read its creation time, and
    on a loaded machine that took seconds per call -- called on nearly every
    tool call, it tripled the suite's running time. A pid reused since the
    snapshot can pose as a parent here; the consent walk still asks psutil,
    which refuses a parent younger than its child, so that risk stays with
    the cheap, non-authorizing use: which windows to enumerate.
    """
    kernel32 = winapi.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == wintypes.HANDLE(-1).value or not snapshot:
        return {}
    found: dict[int, int] = {}
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                found[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)
    return found


def descendants(pid: int) -> list[int]:
    """Every process descended from `pid`, nearest first."""
    parents = parent_map()
    children: dict[int, list[int]] = {}
    for child, parent in parents.items():
        children.setdefault(parent, []).append(child)
    out: list[int] = []
    frontier = [pid]
    seen = {pid}
    while frontier:
        current = frontier.pop(0)
        for child in children.get(current, ()):
            if child not in seen:
                seen.add(child)
                out.append(child)
                frontier.append(child)
    return out
