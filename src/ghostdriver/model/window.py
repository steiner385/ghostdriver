"""Platform-neutral representation of a window tree.

Backends produce these; everything above the backend boundary consumes them.
No Win32 types appear here by design (spec section 3.2).
"""

from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True, slots=True)
class WindowNode:
    """One window in a target's tree.

    `handle` is an opaque integer supplied by the backend. It is valid only
    for the lifetime of the enumeration that produced it: the OS recycles
    handles, so it must never be persisted or returned to a caller.
    """

    handle: int
    class_name: str
    text: str
    rect: tuple[int, int, int, int]  # left, top, right, bottom, screen coords
    visible: bool
    enabled: bool
    pid: int
    children: tuple["WindowNode", ...] = ()

    def walk(self) -> Iterator["WindowNode"]:
        """Yield this node then all descendants, in pre-order."""
        yield self
        for child in self.children:
            yield from child.walk()

    def depth(self) -> int:
        """Number of levels in this subtree, counting this node as 1."""
        if not self.children:
            return 1
        return 1 + max(child.depth() for child in self.children)
