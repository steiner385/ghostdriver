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

#: Depth to walk beneath a region.
#:
#: This was 4, and 4 was wrong. An embedded browser engine wraps its
#: document in its own view hierarchy -- root view, non-client view, frame
#: view, browser view -- before any page content appears. Measured against a
#: live embedded engine rendering a real page:
#:
#:     depth 1-5    10 elements cumulative   engine chrome
#:     depth 6      25 cumulative            content begins
#:     depth 7      40 cumulative
#:     depth 11    159 cumulative
#:
#: At depth 4 the probe saw 7 elements, *below* the classifier's scrollbar
#: budget, so a region full of readable, actuatable content looked as
#: opaque as an owner-drawn grid. The class signature happened to catch it
#: anyway, which is precisely why the shallow probe went unnoticed.
#:
#: 8 clears the chrome of a real engine with margin. The cost is bounded:
#: a genuinely opaque region has nothing to walk and terminates immediately
#: whatever this is set to, and PROBE_ELEMENTS caps the rest.
PROBE_DEPTH = 8

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
