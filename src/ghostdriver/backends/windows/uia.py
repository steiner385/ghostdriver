"""Assess how much a target exposes through UI Automation.

The question this answers is not "what is in the tree" but "is the tree
worth using". A provider-less application still produces a UIA tree via the
generic HWND fallback: every element reports as Pane and supports no
patterns. Counting pattern support is what separates that from a real
provider.

Both the control view and the raw view are walkable. Comparing them is how
an empty result is shown to be the provider's doing rather than the
walker's.
"""

from dataclasses import dataclass, field

#: Pattern IDs occupy a contiguous block starting at 10000.
PATTERN_IDS: dict[str, int] = {
    "Invoke": 10000,
    "Selection": 10001,
    "Value": 10002,
    "RangeValue": 10003,
    "Scroll": 10004,
    "ExpandCollapse": 10005,
    "Grid": 10006,
    "GridItem": 10007,
    "Window": 10009,
    "SelectionItem": 10010,
    "Table": 10012,
    "TableItem": 10013,
    "Text": 10014,
    "Toggle": 10015,
}

CONTROL_TYPE_NAMES = {
    50000: "Button",
    50004: "Edit",
    50020: "Text",
    50032: "Window",
    50033: "Pane",
}


@dataclass
class UiaAssessment:
    available: bool
    element_count: int = 0
    with_patterns: int = 0
    richness: float = 0.0
    control_type_histogram: dict[str, int] = field(default_factory=dict)
    pattern_histogram: dict[str, int] = field(default_factory=dict)
    max_depth_reached: int = 0
    verdict: str = "unknown"
    sample: list[str] = field(default_factory=list)
    error: str | None = None


def verdict_for(assessment: "UiaAssessment") -> str:
    """Classify a tree by how many of its elements are actionable.

    Zero pattern support means the tree carries structure and no semantics,
    which is worse than useless: it looks like data while supporting no
    action. That case is called out explicitly rather than folded into a
    low score.
    """
    if not assessment.available:
        return "unavailable"
    if assessment.element_count == 0:
        return "empty"
    if assessment.with_patterns == 0:
        return "unusable"
    if assessment.richness >= 0.5:
        return "rich"
    return "partial"


def _control_type_name(type_id: int) -> str:
    return CONTROL_TYPE_NAMES.get(type_id, f"ControlType({type_id})")


def assess_uia(
    hwnd: int, *, view: str = "control", max_depth: int = 12,
    max_elements: int = 500,
) -> UiaAssessment:
    try:
        import comtypes
        import comtypes.client

        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA
    except Exception as exc:  # pragma: no cover - environment dependent
        return UiaAssessment(available=False, error=f"UIA unavailable: {exc}")

    try:
        comtypes.CoInitialize()
        iuia = comtypes.client.CreateObject(
            UIA.CUIAutomation, interface=UIA.IUIAutomation
        )
        root = iuia.ElementFromHandle(hwnd)
        if not root:
            return UiaAssessment(available=False, error="no element for handle")
        walker = iuia.RawViewWalker if view == "raw" else iuia.ControlViewWalker
    except Exception as exc:
        return UiaAssessment(available=False, error=str(exc))

    control_types: dict[str, int] = {}
    patterns: dict[str, int] = {}
    sample: list[str] = []
    state = {"count": 0, "with_patterns": 0, "depth": 0}

    def supported_patterns(element) -> list[str]:
        found = []
        for name, pattern_id in PATTERN_IDS.items():
            try:
                if element.GetCurrentPattern(pattern_id):
                    found.append(name)
            except Exception:
                continue
        return found

    def visit(element, depth: int) -> None:
        if state["count"] >= max_elements or depth > max_depth:
            return
        state["count"] += 1
        state["depth"] = max(state["depth"], depth)

        try:
            type_name = _control_type_name(element.CurrentControlType)
            name = element.CurrentName or ""
            class_name = element.CurrentClassName or ""
        except Exception:
            type_name, name, class_name = "unreadable", "", ""

        control_types[type_name] = control_types.get(type_name, 0) + 1
        found = supported_patterns(element)
        if found:
            state["with_patterns"] += 1
            for pattern_name in found:
                patterns[pattern_name] = patterns.get(pattern_name, 0) + 1

        if len(sample) < 25:
            sample.append(
                f"{'  ' * depth}{type_name} name={name!r} "
                f"cls={class_name!r} patterns={found}"
            )

        try:
            child = walker.GetFirstChildElement(element)
        except Exception:
            return
        while child and state["count"] < max_elements:
            visit(child, depth + 1)
            try:
                child = walker.GetNextSiblingElement(child)
            except Exception:
                break

    try:
        visit(root, 0)
    except Exception as exc:
        return UiaAssessment(available=False, error=str(exc))

    count = state["count"]
    assessment = UiaAssessment(
        available=True,
        element_count=count,
        with_patterns=state["with_patterns"],
        richness=(state["with_patterns"] / count) if count else 0.0,
        control_type_histogram=control_types,
        pattern_histogram=patterns,
        max_depth_reached=state["depth"],
        sample=sample,
    )
    assessment.verdict = verdict_for(assessment)
    return assessment
