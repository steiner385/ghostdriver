"""Evidence a window tree cannot supply: what lies beneath a leaf window.

When the window tree stops at a node that still occupies real screen area,
one question decides how that region can be driven: does anything else
expose structure inside it? An embedded document does. A control that draws
its own contents does not. Both look identical from the window tree, so this
asks the accessibility surface instead.

Kept apart from uia.py because the question is different. That module
assesses a whole target to classify it; this one asks a narrow question
about a single region and has to be cheap enough to ask repeatedly.
"""

from ...surface import RegionEvidence
from ...model.window import WindowNode

#: Depth to walk beneath a region. An embedded document announces itself
#: within a couple of levels, and the point here is presence of structure,
#: not an inventory of it.
PROBE_DEPTH = 4

#: Stop after this many. Enough to clear the scrollbar budget the classifier
#: uses by a wide margin, cheap enough to run per region.
PROBE_ELEMENTS = 40


def region_evidence(node: WindowNode, *, view: str = "raw") -> RegionEvidence:
    """Look beneath `node` on the accessibility surface.

    Returns tree-only evidence when UIA is unavailable. That is the honest
    degradation: without this surface the classifier sees a childless,
    textless region and reports it opaque, which is what a caller with no
    accessibility surface would in fact be facing.
    """
    base = RegionEvidence(
        child_windows=len(node.children),
        answers_text=node.responsive,
        has_own_text=bool(node.text),
    )

    try:
        import comtypes
        import comtypes.client

        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA
    except Exception:
        return base

    try:
        comtypes.CoInitialize()
        iuia = comtypes.client.CreateObject(
            UIA.CUIAutomation, interface=UIA.IUIAutomation
        )
        root = iuia.ElementFromHandle(node.handle)
        if not root:
            return base
        walker = iuia.RawViewWalker if view == "raw" else iuia.ControlViewWalker
    except Exception:
        return base

    state = {"count": 0, "named": 0, "depth": 0}

    def visit(element, depth: int) -> None:
        if state["count"] >= PROBE_ELEMENTS or depth > PROBE_DEPTH:
            return
        if depth:
            # Depth 0 is the element standing for the region itself. Counting
            # it would give every region one element of "content" and make
            # the classifier's budget meaningless.
            state["count"] += 1
            state["depth"] = max(state["depth"], depth)
            try:
                if (element.CurrentName or "").strip():
                    state["named"] += 1
            except Exception:
                pass
        try:
            child = walker.GetFirstChildElement(element)
        except Exception:
            return
        while child and state["count"] < PROBE_ELEMENTS:
            visit(child, depth + 1)
            try:
                child = walker.GetNextSiblingElement(child)
            except Exception:
                break

    try:
        visit(root, 0)
    except Exception:
        # Keep what the walk collected. A partial answer still distinguishes
        # "something is under here" from "nothing is".
        pass

    return RegionEvidence(
        child_windows=base.child_windows,
        answers_text=base.answers_text,
        has_own_text=base.has_own_text,
        accessible_elements=state["count"],
        # Scrollbar parts carry chrome names ("Page down", "Position"), so a
        # named count is only meaningful once the element count has already
        # cleared the chrome budget. The classifier applies that rule; this
        # only reports what was seen.
        accessible_named=state["named"] if state["count"] > 0 else 0,
        accessible_max_depth=state["depth"],
    )
