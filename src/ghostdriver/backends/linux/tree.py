"""The window tree, over AT-SPI. Slice 1 of wiring the contract (#40).

The shape the rest of the tool reads is `WindowNode`, and it was designed
against Win32, where every control is a window with a handle, a class and a
rectangle. AT-SPI gives none of those three directly, so each is mapped, and
the mapping is the part worth arguing with:

* **`handle`** has no counterpart. Only toplevels carry an X id; a control is
  an accessible with no stable integer identity at all (D#8). So handles are
  minted here and kept in a registry, which is exactly what `WindowNode`
  already documents them as -- "opaque, supplied by the backend, valid only
  for the lifetime of the enumeration that produced it". Win32 recycles
  handles and this invents them; both are unsafe to persist, which is why the
  contract already forbids it.

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

Every AT-SPI call goes through the deadline (D#9), because a hung
application stops answering the bus rather than one control, and a tree walk
makes hundreds of calls.

`gi` is imported inside the functions: this module is loaded on Windows by
`tests/test_backends.py`, which checks that the Linux backend refuses.
"""

from __future__ import annotations

import os
from functools import partial
from typing import Any

from ...model.process import ProcessFacts
from ...model.window import WindowNode
from .deadline import call_with_deadline

#: Minted handles, and what they point at. Rebuilt by every enumeration, so a
#: handle from a previous one resolves to nothing rather than to whatever has
#: since taken its number.
_HANDLES: dict[int, Any] = {}
_NEXT = [1]


def _mint(node: Any) -> int:
    handle = _NEXT[0]
    _NEXT[0] += 1
    _HANDLES[handle] = node
    return handle


def _reset() -> None:
    _HANDLES.clear()


def _accessible(handle: int) -> Any:
    node = _HANDLES.get(handle)
    if node is None:
        raise KeyError(
            f"handle {handle} is not from the current enumeration. Handles are "
            "valid only for the enumeration that produced them; re-enumerate."
        )
    return node


def _applications() -> list[Any]:
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

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

    got = call_with_deadline(extents)
    if got is None:
        return (0, 0, 0, 0)
    return (got.x, got.y, got.x + got.width, got.y + got.height)


def _states(node: Any) -> set[str]:
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    got = call_with_deadline(node.get_state_set)
    if got is None:
        return set()
    return {name for name in ("SHOWING", "VISIBLE", "SENSITIVE", "ENABLED")
            if got.contains(getattr(Atspi.StateType, name))}


def _node(accessible: Any, pid: int) -> WindowNode:
    states = _states(accessible)
    role = call_with_deadline(accessible.get_role_name) or ""
    name = call_with_deadline(accessible.get_name)
    count = call_with_deadline(accessible.get_child_count)

    children: list[WindowNode] = []
    for index in range(count or 0):
        child = call_with_deadline(partial(accessible.get_child_at_index, index))
        if child is not None:
            children.append(_node(child, pid))

    return WindowNode(
        handle=_mint(accessible),
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


# --- the contract ------------------------------------------------------------

def enumerate_process(pid: int) -> list[WindowNode]:
    """Every top-level tree this process owns, as WindowNodes."""
    _reset()
    trees = []
    for app in _for_pid(pid):
        count = call_with_deadline(app.get_child_count) or 0
        for index in range(count):
            frame = call_with_deadline(partial(app.get_child_at_index, index))
            if frame is not None:
                trees.append(_node(frame, pid))
    return trees


def top_level_windows(pid: int) -> list[int]:
    """The handles of this process's top-level windows."""
    return [tree.handle for tree in enumerate_process(pid)]


def direct_children(handle: int) -> list[int]:
    """The handles of one node's immediate children, in tree order (D71)."""
    accessible = _accessible(handle)
    count = call_with_deadline(accessible.get_child_count) or 0
    out = []
    for index in range(count):
        child = call_with_deadline(partial(accessible.get_child_at_index, index))
        if child is not None:
            out.append(_mint(child))
    return out


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
    """Every pid in this process's tree, itself included (R5, D71)."""
    import psutil

    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return []
    out = [pid]
    try:
        out.extend(child.pid for child in proc.children(recursive=True))
    except psutil.Error:
        pass
    return out


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
