"""The window tree, over AT-SPI. Slice 1 of wiring the contract (#40).

The shape the rest of the tool reads is `WindowNode`, and it was designed
against Win32, where every control is a window with a handle, a class and a
rectangle. AT-SPI gives none of those three directly, so each is mapped, and
the mapping is the part worth arguing with:

* **`handle`** has no counterpart. Only toplevels carry an X id; a control is
  an accessible with no stable integer identity at all (D#8). So handles are
  minted here and kept in a registry. **A handle names a path** -- the chain
  of child indices from the application down -- and the same path gets the
  same handle on every enumeration (D#104). That is what lets a caller keep a
  handle across the re-enumeration an `expect` performs while it polls; the
  price is Win32's own hazard, stated rather than hidden: a control that moves
  answers as whatever now sits at its old path, which is exactly why the
  contract forbids persisting one.

* **`class_name`** becomes the AT-SPI **role name** (`push button`, `text`,
  `table`). It is the nearest thing to a window class: the toolkit's own name
  for what a control *is*, and what a locator will match on. It is coarser
  than a Win32 class -- every button is `push button`, where Win32 would name
  a vendor subclass -- and that costs the toolkit evidence D47 leaned on.

* **`text`** is the accessible name, not the Text interface. The Text
  interface is the *contents*, and reading contents here is governed by the
  disclosure policy (D#34b), not by tree enumeration. A tree walk that
  quietly returned every password on screen would be the exact bug that
  policy exists to prevent.

* **`enabled`** is `SENSITIVE`. `visible` is `SHOWING`, not `VISIBLE`:
  `VISIBLE` is set on a widget whose window is minimised, and D#13 measured
  that a hidden window's contents survive, so `SHOWING` is the one that
  answers "on screen".

The registry also keeps, per node, the state set and interface list the walk
already fetched, so the elements view (`elements.py`) is built from it
without a second pass over the bus -- on Studio that is 2,300 nodes.

Every AT-SPI call goes through the deadline (D#9), because a hung
application stops answering the bus rather than one control, and a tree walk
makes hundreds of calls.

`gi` is imported inside the functions: this module is loaded on Windows by
`tests/test_backends.py`, which checks that the Linux backend refuses.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from ...model.process import ProcessFacts
from ...model.window import WindowNode
from .. import AccessibilityUnavailable
from . import display
from .deadline import call_with_deadline

#: How long to wait for the accessibility bus to say it exists. Short on
#: purpose: this runs before every enumeration, and a bus that is there
#: answers immediately. A bus that is not there is what the wait is for, and
#: waiting longer does not make it appear.
BUS_TIMEOUT_MS = 2000

#: The states the registry keeps per node. Everything the tree, the elements
#: view and the disclosure policy ask about, fetched once.
STATE_NAMES = ("SHOWING", "VISIBLE", "SENSITIVE", "ENABLED", "EDITABLE",
               "FOCUSABLE", "FOCUSED", "CHECKED", "SELECTED", "SELECTABLE")

#: Minted handles start above any X resource id (29 bits, max 0x1FFFFFFF),
#: so a caller cannot hand one identifier space's number to the other by
#: accident and have it resolve (D#40d, D#101).
_FIRST_HANDLE = 0x40000000


@dataclass
class _Entry:
    accessible: Any
    path: tuple[int, ...]
    pid: int
    role: str
    name: str
    states: frozenset[str]
    interfaces: tuple[str, ...]
    children: list[int] = field(default_factory=list)
    #: For a frame: the X window the tree correlated it with, or 0.
    xid: int = 0


_HANDLES: dict[int, _Entry] = {}
_BY_PATH: dict[tuple[int, ...], int] = {}
_NEXT = [_FIRST_HANDLE]


def _mint(path: tuple[int, ...], entry: _Entry) -> int:
    handle = _BY_PATH.get(path)
    if handle is None:
        handle = _NEXT[0]
        _NEXT[0] += 1
        _BY_PATH[path] = handle
    _HANDLES[handle] = entry
    return handle


def _reset() -> None:
    """Forget every handle. Tests use it; enumeration does not, because a
    handle is stable for the path it names (D#104)."""
    _HANDLES.clear()
    _BY_PATH.clear()


def _forget_pid(pid: int, keep: set[int]) -> None:
    """Drop the entries of `pid` that this enumeration did not see, so a
    control that is gone raises rather than answering as a dead object."""
    for handle in [h for h, e in _HANDLES.items() if e.pid == pid and h not in keep]:
        entry = _HANDLES.pop(handle)
        _BY_PATH.pop(entry.path, None)


def _entry(handle: int) -> _Entry:
    entry = _HANDLES.get(handle)
    if entry is None:
        raise KeyError(
            f"handle {handle} is not from the current enumeration. Handles are "
            "valid only for the enumeration that produced them; re-enumerate."
        )
    return entry


def _accessible(handle: int) -> Any:
    return _entry(handle).accessible


def _require_accessibility_bus() -> None:
    """Fail with an exception before AT-SPI can fail with an abort.

    `Atspi.init()` reports a bus it cannot reach through GLib's `g_error()`,
    and `g_error()` is **fatal by contract** -- it aborts the process with
    SIGTRAP. There is no Python exception to catch and no result to return:
    the server simply dies, taking every open session with it (#58).

    So the bus is checked first, through `Gio`, which raises a catchable
    `GLib.Error` for exactly the same conditions. `org.a11y.Bus.GetAddress`
    is the question AT-SPI itself asks, so a success here means the call
    that follows has a bus to talk to.

    The deadline matters as much as the check. A D-Bus activation can block
    while it waits for a service that is never going to start, and a driver
    that hangs is barely better than one that aborts (D#9), so this is
    bounded and reports the timeout as the unavailability it is.
    """
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    remedy = (
        "start one with `at-spi-bus-launcher --launch-immediately`, and make "
        "sure the process has a DISPLAY and a D-Bus session bus. On a "
        "headless box both have to be arranged deliberately."
    )
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error as exc:
        raise AccessibilityUnavailable(
            f"no D-Bus session bus, so there is no accessibility bus to "
            f"reach: {exc.message}. {remedy}"
        ) from exc
    try:
        bus.call_sync(
            "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus", "GetAddress",
            None, GLib.VariantType("(s)"), Gio.DBusCallFlags.NONE,
            BUS_TIMEOUT_MS, None,
        )
    except GLib.Error as exc:
        raise AccessibilityUnavailable(
            f"the accessibility bus did not answer: {exc.message}. {remedy}"
        ) from exc


def _applications() -> list[Any]:
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    _require_accessibility_bus()
    Atspi.init()
    desktop = Atspi.get_desktop(0)
    out = []
    for index in range(desktop.get_child_count()):
        child = call_with_deadline(partial(desktop.get_child_at_index, index))
        if child is not None:
            out.append(child)
    return out


def _for_pid(pid: int) -> list[Any]:
    return [app for app in _applications()
            if call_with_deadline(app.get_process_id) == pid]


def _rect(node: Any) -> tuple[int, int, int, int]:
    """Screen coordinates, left/top/right/bottom, as WindowNode expects."""
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    def extents():
        return Atspi.Component.get_extents(node, Atspi.CoordType.SCREEN)

    try:
        got = call_with_deadline(extents)
    except Exception:
        # Not every accessible implements Component; an application node
        # does not, and asking raises rather than answering.
        return (0, 0, 0, 0)
    if got is None:
        return (0, 0, 0, 0)
    return (got.x, got.y, got.x + got.width, got.y + got.height)


def _states(node: Any) -> frozenset[str]:
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    got = call_with_deadline(node.get_state_set)
    if got is None:
        return frozenset()
    return frozenset(name for name in STATE_NAMES
                     if got.contains(getattr(Atspi.StateType, name)))


def _interfaces(node: Any) -> tuple[str, ...]:
    got = call_with_deadline(node.get_interfaces)
    return tuple(got) if got else ()


def _node(accessible: Any, pid: int, path: tuple[int, ...]) -> WindowNode:
    states = _states(accessible)
    role = call_with_deadline(accessible.get_role_name) or ""
    name = call_with_deadline(accessible.get_name)
    count = call_with_deadline(accessible.get_child_count)
    entry = _Entry(accessible=accessible, path=path, pid=pid, role=role,
                   name=name or "", states=states,
                   interfaces=_interfaces(accessible))
    handle = _mint(path, entry)

    children: list[WindowNode] = []
    for index in range(count or 0):
        child = call_with_deadline(partial(accessible.get_child_at_index, index))
        if child is not None:
            children.append(_node(child, pid, path + (index,)))
    entry.children = [child.handle for child in children]

    return WindowNode(
        handle=handle,
        class_name=role,
        # None from the deadline is "did not answer", and the caller is told
        # so through `responsive` rather than by an empty string that reads
        # as a confirmed blank (D4, D#9).
        text=name or "",
        rect=_rect(accessible),
        visible="SHOWING" in states,
        enabled="SENSITIVE" in states,
        pid=pid,
        children=tuple(children),
        responsive=name is not None,
    )


def _correlate_frame(frame: WindowNode, pid: int) -> None:
    """Find the X window behind a frame, and tell `display` about it.

    By accessible name against `_NET_WM_NAME` and, when the name alone is
    ambiguous, by size (D#40d measured both matching exactly; D#101 needs
    it because a sandboxed target's windows carry no pid at all). A frame
    that cannot be identified uniquely is left uncorrelated rather than
    guessed at (D33).
    """
    entry = _entry(frame.handle)
    width = frame.rect[2] - frame.rect[0]
    height = frame.rect[3] - frame.rect[1]
    by_name = [xid for xid in display.client_windows()
               if display.window_name(xid) == entry.name]
    if len(by_name) > 1:
        by_name = [xid for xid in by_name
                   if display.geometry(xid)[2:] == (width, height)]
    if len(by_name) == 1:
        entry.xid = by_name[0]
        display.attribute(pid, by_name[0])


def frame_xid_of(handle: int) -> int | None:
    """The X window the tree correlated with the frame holding `handle`, if
    it could -- the cheap route across the two identifier spaces."""
    entry = _HANDLES.get(handle)
    if entry is None:
        return None
    frame_path = entry.path[:2]
    frame_handle = _BY_PATH.get(frame_path)
    if frame_handle is None:
        return None
    xid = _HANDLES[frame_handle].xid
    return xid or None


# --- the contract ------------------------------------------------------------

def enumerate_process(pid: int) -> list[WindowNode]:
    """Every top-level tree this process owns, as WindowNodes."""
    trees = []
    seen: set[int] = set()
    for app in _for_pid(pid):
        count = call_with_deadline(app.get_child_count) or 0
        for index in range(count):
            frame = call_with_deadline(partial(app.get_child_at_index, index))
            if frame is not None:
                tree = _node(frame, pid, (pid, index))
                seen.update(n.handle for n in tree.walk())
                _correlate_frame(tree, pid)
                trees.append(tree)
    _forget_pid(pid, seen)
    return trees


def top_level_windows(pid: int) -> list[int]:
    """The handles of this process's top-level windows."""
    return [tree.handle for tree in enumerate_process(pid)]


def direct_children(handle: int) -> list[int]:
    """The handles of one node's immediate children, in tree order (D71)."""
    return list(_entry(handle).children)


def application_name(pid: int) -> str | None:
    """What the accessibility bus calls the application behind `pid`, when
    that is a better name than the process's own.

    A sandboxed application's a11y pid is its D-Bus proxy's, so `psutil`
    names it `xdg-dbus-proxy` while the bus names it `bambu-studio`
    (D#101). None when the bus has no application for this pid, or agrees
    with the process name -- so a caller shows it only when it adds something.
    """
    import psutil

    try:
        process_name = psutil.Process(pid).name()
    except psutil.Error:
        process_name = ""
    for app in _for_pid(pid):
        name = call_with_deadline(app.get_name) or ""
        if name and name != process_name:
            return name
    return None


def process_facts(pid: int) -> ProcessFacts:
    """What can honestly be said about the process behind a target.

    The Windows-flavoured fields say so rather than guessing: there is no
    WOW64, no integrity level, and X11 scaling is a different model from
    per-process DPI awareness, so mapping it would be a guess dressed as a
    measurement.
    """
    import psutil

    proc = psutil.Process(pid)
    try:
        executable = proc.exe()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        executable = ""

    modules, readable = _loaded_objects(proc)
    return ProcessFacts(
        pid=pid,
        executable=executable,
        bitness=_bitness(executable),
        wow64=False,
        integrity_level=None,
        dpi_awareness="unknown",
        modules=modules,
        modules_readable=readable,
    )


def _loaded_objects(proc: Any) -> tuple[list[str], bool]:
    """The shared objects the process has mapped -- the toolkit evidence
    `infer_toolkit` reads (libgtk, libQt, libwx). `/proc/<pid>/maps` is the
    Linux counterpart of the module list, and it is unreadable for a process
    owned by someone else, which is a different fact from "nothing matched"."""
    try:
        with open(f"/proc/{proc.pid}/maps", encoding="utf-8", errors="replace") as maps:
            paths = {line.split()[-1] for line in maps if line.rstrip().endswith(".so")
                     or ".so." in line}
        return sorted(p for p in paths if p.startswith("/")), True
    except (OSError, PermissionError):
        return [], False


def _bitness(executable: str) -> str:
    """From the ELF header's class byte. "unknown" when it cannot be read,
    never a default that reads like a measurement."""
    if not executable or not os.path.exists(executable):
        return "unknown"
    try:
        with open(executable, "rb") as binary:
            header = binary.read(5)
    except OSError:
        return "unknown"
    if header[:4] != b"\x7fELF":
        return "unknown"
    return {1: "x86", 2: "x64"}.get(header[4], "unknown")


def descendants(pid: int) -> list[int]:
    """Every pid in this process's tree, itself included (R5, D71) -- and,
    for a sandboxed target, the real process the X server attributes its
    windows to, which is a sibling of the a11y pid rather than a child
    (D#101). Without it the interference watch would see Studio's window
    take the front and not recognise it as the target."""
    import psutil

    out = [pid]
    for root in (pid, *display.aliases(pid)):
        try:
            proc = psutil.Process(root)
        except psutil.NoSuchProcess:
            continue
        if root not in out:
            out.append(root)
        try:
            out.extend(c.pid for c in proc.children(recursive=True) if c.pid not in out)
        except psutil.Error:
            pass
    return out if len(out) > 1 or _alive(pid) else []


def _alive(pid: int) -> bool:
    import psutil

    return psutil.pid_exists(pid)


def parent_map() -> dict[int, int]:
    """Every process's parent, for following a target that spawns (D71)."""
    import psutil

    out = {}
    for proc in psutil.process_iter(["pid", "ppid"]):
        try:
            out[proc.info["pid"]] = proc.info["ppid"]
        except (KeyError, psutil.Error):
            continue
    return out
