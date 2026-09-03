"""Elements that are not windows, on the Windows accessibility surface.

The walk produces `AccessibleElement`s under a window; the actions drive
one through the pattern it publishes, or -- when it publishes none that
fits, which on a Profile L1 target is every element -- through a posted
click on its host window at the element's own rectangle. Nothing here
activates a window: patterns are in-process calls the provider handles on
its own thread, and the posted click is the same pair `input.click` sends
to a window, aimed inside it.

Every entry point creates its own UIA client: COM is apartment-bound, and
a hidden-desktop session runs these on a worker thread. A client made on
one thread and used on another is the kind of failure that reports as
"no element" rather than as an error.
"""

import ctypes
from ctypes import wintypes

from ...model.element import AccessibleElement
from ...model.window import WindowNode
from . import winapi
from .input import WM_LBUTTONDOWN, WM_LBUTTONUP, _lparam_for_point, user32
from .uia import CONTROL_TYPE_NAMES, PATTERN_IDS

#: Enough for a busy window; a walk that hits this reports it.
MAX_ELEMENTS = 2000
MAX_DEPTH = 24

_ACTION_PATTERNS = ("SelectionItem", "Invoke", "Toggle", "ExpandCollapse")


class ElementError(RuntimeError):
    """The accessibility surface could not do what was asked."""


def _uia():
    import comtypes
    import comtypes.client

    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as UIA

    comtypes.CoInitialize()
    iuia = comtypes.client.CreateObject(UIA.CUIAutomation, interface=UIA.IUIAutomation)
    return UIA, iuia


def _patterns_of(element) -> tuple[str, ...]:
    found = []
    for name, pattern_id in PATTERN_IDS.items():
        try:
            if element.GetCurrentPattern(pattern_id):
                found.append(name)
        except Exception:
            continue
    return tuple(found)


def _describe(element, UIA, *, host_handle: int, host_class: str,
              sibling_index: int, pid: int, patterns: tuple[str, ...]) -> AccessibleElement:
    rect = element.CurrentBoundingRectangle
    selected = None
    if "SelectionItem" in patterns:
        try:
            selected = bool(element.GetCurrentPattern(PATTERN_IDS["SelectionItem"])
                            .QueryInterface(UIA.IUIAutomationSelectionItemPattern)
                            .CurrentIsSelected)
        except Exception:
            selected = None
    value = None
    if "Value" in patterns:
        try:
            value = element.GetCurrentPattern(PATTERN_IDS["Value"]) \
                .QueryInterface(UIA.IUIAutomationValuePattern).CurrentValue
        except Exception:
            value = None
    return AccessibleElement(
        runtime_id=tuple(int(x) for x in element.GetRuntimeId()),
        control_type=CONTROL_TYPE_NAMES.get(
            element.CurrentControlType, f"ControlType({element.CurrentControlType})"),
        name=element.CurrentName or "",
        automation_id=element.CurrentAutomationId or "",
        class_name=element.CurrentClassName or "",
        rect=(int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)),
        enabled=bool(element.CurrentIsEnabled),
        offscreen=bool(element.CurrentIsOffscreen),
        patterns=patterns,
        host_handle=host_handle,
        host_class=host_class,
        sibling_index=sibling_index,
        selected=selected,
        value=value,
        pid=pid,
    )


def walk_elements(
    node: WindowNode, *, view: str = "control",
    max_elements: int = MAX_ELEMENTS, max_depth: int = MAX_DEPTH,
) -> list[tuple[AccessibleElement, tuple[AccessibleElement, ...]]]:
    """Every element under `node`'s window, each with its ancestors (root-first).

    The window's own element is the root and is not returned: it is the
    window, and the window tree already names it. An element that is
    itself a window is returned -- a Button with a handle is as much an
    element as a TabItem without one -- with that handle as its host.
    """
    try:
        UIA, iuia = _uia()
        root = iuia.ElementFromHandle(wintypes.HWND(node.handle))
    except Exception as exc:
        raise ElementError(f"the accessibility surface is unavailable: {exc}") from exc
    if not root:
        return []
    walker = iuia.RawViewWalker if view == "raw" else iuia.ControlViewWalker

    out: list[tuple[AccessibleElement, tuple[AccessibleElement, ...]]] = []
    state = {"count": 0}

    def visit(element, ancestors, host_handle, host_class, depth):
        if state["count"] >= max_elements or depth > max_depth:
            return
        try:
            child = walker.GetFirstChildElement(element)
        except Exception:
            return
        counts: dict[str, int] = {}
        while child and state["count"] < max_elements:
            state["count"] += 1
            try:
                patterns = _patterns_of(child)
                own = int(child.CurrentNativeWindowHandle or 0)
                this_host, this_class = (
                    (own, winapi.class_name(own)) if own else (host_handle, host_class))
                type_name = CONTROL_TYPE_NAMES.get(child.CurrentControlType, "")
                counts[type_name] = counts.get(type_name, 0) + 1
                described = _describe(
                    child, UIA, host_handle=this_host, host_class=this_class,
                    sibling_index=counts[type_name], pid=node.pid, patterns=patterns)
            except Exception:
                described = None
            if described is not None:
                out.append((described, ancestors))
                visit(child, ancestors + (described,), described.host_handle,
                      described.host_class, depth + 1)
            try:
                child = walker.GetNextSiblingElement(child)
            except Exception:
                break

    try:
        visit(root, (), node.handle, node.class_name, 0)
    except Exception:
        pass  # keep what the walk collected; a partial answer beats none
    return out


def _live(element: AccessibleElement):
    """The COM element for `element`, found again by runtime id under its host.

    Re-walked rather than held: a COM pointer from an earlier walk may be
    stale, and the runtime id is the identity UIA itself uses.
    """
    UIA, iuia = _uia()
    root = iuia.ElementFromHandle(wintypes.HWND(element.host_handle))
    if not root:
        raise ElementError("the element's host window is gone")
    walker = iuia.ControlViewWalker
    wanted = element.runtime_id
    stack = [root]
    seen = 0
    while stack and seen < MAX_ELEMENTS:
        current = stack.pop()
        seen += 1
        try:
            if tuple(int(x) for x in current.GetRuntimeId()) == wanted:
                return UIA, current
            child = walker.GetFirstChildElement(current)
            while child:
                stack.append(child)
                child = walker.GetNextSiblingElement(child)
        except Exception:
            continue
    raise ElementError("the element is no longer on the accessibility surface")


def act_via_pattern(element: AccessibleElement) -> bool:
    """Tier 1: the first fitting pattern the element publishes.

    SelectionItem before Invoke: a tab item that has both is selected by a
    click, not invoked. Returns False when the element publishes none of
    them, so the ladder falls through rather than pretending.
    """
    fitting = [p for p in _ACTION_PATTERNS if p in element.patterns]
    if not fitting:
        return False
    try:
        UIA, live = _live(element)
        pattern_name = fitting[0]
        pattern = live.GetCurrentPattern(PATTERN_IDS[pattern_name])
        if not pattern:
            return False
        if pattern_name == "SelectionItem":
            pattern.QueryInterface(UIA.IUIAutomationSelectionItemPattern).Select()
        elif pattern_name == "Invoke":
            pattern.QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
        elif pattern_name == "Toggle":
            pattern.QueryInterface(UIA.IUIAutomationTogglePattern).Toggle()
        else:
            expand = pattern.QueryInterface(UIA.IUIAutomationExpandCollapsePattern)
            if expand.CurrentExpandCollapseState == 0:  # collapsed
                expand.Expand()
            else:
                expand.Collapse()
        return True
    except Exception:
        return False


def click_posted(element: AccessibleElement) -> bool:
    """Tier 3: the button pair, posted to the host window at the element.

    The element's rectangle is in screen coordinates; the host wants
    client coordinates, so the centre is converted through the host's own
    origin. That is what makes this work on a target whose elements
    publish no pattern at all: the host window handles the click exactly
    as it would one from a person, at the place the element is drawn.
    """
    left, top, right, bottom = element.rect
    if right <= left or bottom <= top:
        return False
    point = wintypes.POINT((left + right) // 2, (top + bottom) // 2)
    if not user32.ScreenToClient(wintypes.HWND(element.host_handle), ctypes.byref(point)):
        return False
    packed = _lparam_for_point(point.x, point.y)
    down = user32.PostMessageW(wintypes.HWND(element.host_handle), WM_LBUTTONDOWN,
                               0x0001, packed)
    up = user32.PostMessageW(wintypes.HWND(element.host_handle), WM_LBUTTONUP, 0, packed)
    return bool(down and up)


def is_selected(element: AccessibleElement) -> bool | None:
    """The element's current selection state, re-read; None if it has none."""
    if "SelectionItem" not in element.patterns:
        return None
    try:
        UIA, live = _live(element)
        return bool(live.GetCurrentPattern(PATTERN_IDS["SelectionItem"])
                    .QueryInterface(UIA.IUIAutomationSelectionItemPattern)
                    .CurrentIsSelected)
    except Exception:
        return None
