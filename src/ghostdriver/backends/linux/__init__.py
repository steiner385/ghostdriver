"""The Linux backend: specified, being measured, not yet built.

docs/LINUX.md says what it will be -- AT-SPI for the tree and actuation, a
nested X server for the structural isolation guarantee -- and, more
importantly, what has to be *measured* first, because every corner of the
Windows backend that mattered was a measurement contradicting a model.

That measuring has started, and has already contradicted the plan twice: a
bare Xvfb has no EWMH, and the nested display needs a D-Bus session bus of
its own before it isolates anything (D#8). `deadline` is the first piece
that survived it -- AT-SPI will not bound a call against a hung application,
so the caller has to (D#9).

Every *contract* name still answers with the same refusal, because none of
them has been built.
"""

from typing import Any

from .. import CONTRACT, UnsupportedPlatform
from . import isolate, reading, tree

#: What is wired, and where it lives. Everything else still refuses. The map
#: is explicit rather than "try the import and see", so a name that is not
#: here refuses with an explanation instead of an AttributeError from three
#: modules down.
#: `tree` is safe to import here even on Windows -- it keeps `gi` inside its
#: functions -- and importing it plainly rather than by name keeps it visible
#: to the reachability guard, which reads imports and cannot follow a string.
_WIRED: dict[str, Any] = {
    # slice 1, the window tree (#40)
    **dict.fromkeys(
        ("enumerate_process", "top_level_windows", "direct_children",
         "process_facts", "descendants", "parent_map"),
        tree,
    ),
    # slice 2, reading -- under the deadline (D#9) and the disclosure
    # policy (D#34b)
    **dict.fromkeys(
        ("read_window_text", "is_protected", "capture_window", "CaptureError"),
        reading,
    ),
    # slice 5a, the minimized watch -- sampling for the neutral policy in
    # ghostdriver.isolation, which decides (D#13, D#14)
    **dict.fromkeys(("MinimizedWatch", "WatchError"), isolate),
}


class _LinuxBackend:
    platform = "linux"

    def __getattr__(self, name: str) -> Any:
        if name not in CONTRACT:
            raise AttributeError(f"the backend contract has no {name!r}")
        wired = _WIRED.get(name)
        if wired is not None:
            return getattr(wired, name)
        raise UnsupportedPlatform(
            f"{name} is not implemented on Linux yet. The window tree and "
            "reading and the minimized watch are wired (#40 slices 1, 2, 5a); "
            "this is not part of them. The backend is specified "
            "in docs/LINUX.md, and is being built by measurement: the nested "
            "display, its AT-SPI bus, reading, the read deadline, the "
            "disclosure policy and the foreground guarantee are done and "
            "recorded. What is missing is the contract functions themselves. "
            "docs/LINUX.md tracks what has been measured and what has not."
        )


BACKEND = _LinuxBackend()
