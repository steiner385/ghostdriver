"""Platform-neutral representation of a window tree.

Backends produce these; everything above the backend boundary consumes them.
No Win32 types appear here by design (spec section 3.2).
"""

from dataclasses import dataclass
from typing import Iterator, Sequence


@dataclass(frozen=True, slots=True)
class WindowNode:
    """One window in a target's tree.

    `handle` is an opaque integer supplied by the backend. It is valid only
    for the lifetime of the enumeration that produced it: the OS recycles
    handles, so it must never be persisted or returned to a caller.

    `responsive` is False when the control did not answer a text query
    within the timeout, in which case `text` is empty but its true value is
    unknown rather than genuinely absent.
    """

    handle: int
    class_name: str
    text: str
    rect: tuple[int, int, int, int]  # left, top, right, bottom, screen coords
    visible: bool
    enabled: bool
    pid: int
    children: tuple["WindowNode", ...] = ()
    responsive: bool = True

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


def select_main_tree(trees: Sequence[WindowNode]) -> WindowNode | None:
    """Pick the tree that holds the application's actual UI.

    Ranking by total node count is wrong, and wrong in a way that hides
    itself. A toolkit that minimizes to a taskbar proxy keeps a top-level
    proxy window that owns every pooled, never-shown form in the process;
    on a real target that proxy carried 119 nodes of which exactly one was
    visible, while the window the user was looking at carried 62 nodes of
    which 33 were visible. Choosing by total picks the proxy, and every
    command downstream then reads a tree containing none of the UI --
    `find ... visible=true` answers "no matches" against a fully visible
    application.

    Worse, which window wins depends on how much the process happens to
    have pooled, so the same heuristic can be right on one instance of an
    application and wrong on another. That is why this ranks by *visible*
    nodes: the question being asked is which window shows the UI.

    The total-node fallback is not a tiebreak but a different question:
    when nothing is visible anywhere the target is minimized or hidden, no
    window shows the UI, and returning the largest tree preserves the
    caller's ability to inspect a target it cannot see. `restore` exists to
    get out of that state.
    """
    if not trees:
        return None

    def visible_nodes(tree: WindowNode) -> int:
        return sum(1 for n in tree.walk() if n.visible)

    visible_best = max(trees, key=visible_nodes)
    # More than one, not merely non-zero. A minimized target leaves the
    # proxy carrying WS_VISIBLE on its own frame while the real window is
    # hidden outright, so "has any visible node" scores the proxy 1 against
    # the real window's 0 and picks exactly the wrong one -- the bug this
    # function exists to fix, reintroduced one state later. A window that is
    # showing UI has visible content beneath it, not just a frame.
    if visible_nodes(visible_best) > 1:
        return visible_best
    return max(trees, key=lambda t: sum(1 for _ in t.walk()))
