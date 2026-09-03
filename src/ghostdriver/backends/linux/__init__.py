"""The Linux backend: specified, not yet built.

docs/LINUX.md says what it will be -- AT-SPI for the tree and actuation, a
nested X server for the structural isolation guarantee -- and, more
importantly, what has to be *measured* first, because every corner of the
Windows backend that mattered was a measurement contradicting a model.
None of that can be measured on the machine this was written on, so this
package answers every contract name with the same refusal rather than
with code nobody has run.
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
