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


class _LinuxBackend:
    platform = "linux"

    def __getattr__(self, name: str) -> Any:
        if name not in CONTRACT:
            raise AttributeError(f"the backend contract has no {name!r}")
        raise UnsupportedPlatform(
            f"{name} is not implemented on Linux yet. The backend is specified "
            "in docs/LINUX.md; building it needs a Linux desktop to measure "
            "against (a nested X server and an AT-SPI bus are enough)."
        )


BACKEND = _LinuxBackend()
