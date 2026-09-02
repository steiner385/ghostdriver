"""Which process is actually showing its UI in this window.

The window tree cannot answer this. A hosted application and the frame
showing it are separate top-level windows with no parent or owner
relationship between them, so there is nothing to follow.

The accessibility tree can. UIA elements carry the process id of whatever
provided them, and a UIA tree spans processes -- so walking down from a
frame window and counting process ids finds the application inside it.
Measured against a live UWP frame: 211 elements, of which 203 belonged to
the application and 8 to the frame host's own chrome. A majority that
lopsided is not a coincidence to be hedged around.

The one condition is that the application must be **running**. A suspended
one provides nothing, and an earlier version of this measurement returned a
single element and looked like proof that UIA could not cross the boundary
at all. It could; the application was asleep. So "nothing found" is reported
as "suspended or not resolvable", never as "there is nothing there".
"""

from dataclasses import dataclass

#: Elements to walk before deciding. The answer is a majority, not a census,
#: and the frame's own chrome sits at the top of the tree -- so a few hundred
#: is far more than enough to separate a host from its guest, while keeping
#: this cheap enough to run during an attach.
MAX_ELEMENTS = 250

#: Depth to descend. Content appears within a few levels of a frame; going
#: deeper buys precision this does not need.
MAX_DEPTH = 8

#: The share of elements a process must own to be called the application.
#: Set high because the cost of being wrong is pointing someone at an
#: unrelated process, which is worse than admitting the answer is unclear.
MAJORITY = 0.6


@dataclass(frozen=True, slots=True)
class HostedApp:
    """The application found inside a hosted frame."""

    pid: int
    elements: int
    total: int
    #: Every process seen, with its element count. Kept so a caller can
    #: judge a marginal answer instead of taking the verdict on trust.
    census: tuple[tuple[int, int], ...] = ()

    @property
    def share(self) -> float:
        return self.elements / self.total if self.total else 0.0

    def describe(self) -> str:
        return (
            f"pid {self.pid} provides {self.elements} of {self.total} "
            f"elements in this window ({self.share:.0%})"
        )


def process_census(hwnd: int) -> dict[int, int]:
    """Count UIA elements beneath `hwnd` by the process that provided them.

    Returns an empty mapping when UIA is unavailable or the walk yields
    nothing -- both of which mean "no answer", never "no application".
    """
    try:
        import comtypes
        import comtypes.client

        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA
    except Exception:
        return {}

    try:
        comtypes.CoInitialize()
        iuia = comtypes.client.CreateObject(
            UIA.CUIAutomation, interface=UIA.IUIAutomation
        )
        root = iuia.ElementFromHandle(hwnd)
        if not root:
            return {}
        walker = iuia.RawViewWalker
    except Exception:
        return {}

    counts: dict[int, int] = {}
    state = {"seen": 0}

    def visit(element, depth: int) -> None:
        if state["seen"] >= MAX_ELEMENTS or depth > MAX_DEPTH:
            return
        state["seen"] += 1
        try:
            pid = element.CurrentProcessId
            counts[pid] = counts.get(pid, 0) + 1
        except Exception:
            return
        try:
            child = walker.GetFirstChildElement(element)
        except Exception:
            return
        while child and state["seen"] < MAX_ELEMENTS:
            visit(child, depth + 1)
            try:
                child = walker.GetNextSiblingElement(child)
            except Exception:
                break

    try:
        visit(root, 0)
    except Exception:
        # Keep what was counted. A partial census still distinguishes a host
        # from its guest, which is the only question being asked.
        pass
    return counts


def resolve_hosted_app(hwnd: int, owner_pid: int) -> HostedApp | None:
    """The process whose UI this window is showing, when it is not `owner_pid`.

    None means no other process owns a clear majority of the content --
    because the window really does belong to its owner, because the
    application inside it is suspended and providing nothing, or because UIA
    is unavailable. Those are different situations and none of them is
    "resolved to the owner", so none of them returns an answer.
    """
    counts = process_census(hwnd)
    total = sum(counts.values())
    if not total:
        return None

    others = {pid: n for pid, n in counts.items() if pid != owner_pid}
    if not others:
        return None

    pid, elements = max(others.items(), key=lambda kv: kv[1])
    if elements / total < MAJORITY:
        return None

    return HostedApp(
        pid=pid,
        elements=elements,
        total=total,
        census=tuple(sorted(counts.items(), key=lambda kv: -kv[1])),
    )
