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
import time
from ctypes import wintypes

from ...model.element import AccessibleElement
from ...model.window import WindowNode
from . import input as win_input
from . import winapi
from .input import deepest_child_at, post_click, user32
from .uia import CONTROL_TYPE_NAMES, PATTERN_IDS

UIA_IS_PASSWORD_PROPERTY = 30019

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
        is_password=_is_password(element),
    )


def _is_password(element) -> bool:
    try:
        return bool(element.GetCurrentPropertyValue(UIA_IS_PASSWORD_PROPERTY))
    except Exception:
        return False


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
    if node.class_name == winapi.POPUP_MENU_CLASS:
        return _menu_elements(node)
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


def _menu_elements(node: WindowNode) -> list[tuple[AccessibleElement, tuple[AccessibleElement, ...]]]:
    """A popup menu's items, from the menu handle rather than the
    accessibility surface, which an owner-drawn menu keeps empty (D65).

    Separators are elements of their own type, so `type=MenuItem index=N`
    counts the items a person would. An owner-drawn item has no name; its
    automation id says so, and its position is its identity.
    """
    out: list[tuple[AccessibleElement, tuple[AccessibleElement, ...]]] = []
    menu_index = 0
    separator_index = 0
    for item in winapi.popup_menu_items(node.handle):
        if item["separator"]:
            separator_index += 1
            control_type, sibling = "Separator", separator_index
        else:
            menu_index += 1
            control_type, sibling = "MenuItem", menu_index
        out.append((AccessibleElement(
            runtime_id=(node.handle, item["index"]),
            control_type=control_type,
            name=item["text"],
            automation_id="owner-drawn" if item["owner_drawn"] else "",
            class_name=node.class_name,
            rect=item["rect"],
            enabled=item["enabled"],
            offscreen=False,
            patterns=(),
            host_handle=node.handle,
            host_class=node.class_name,
            sibling_index=sibling,
            pid=node.pid,
        ), ()))
    return out


def _live(element: AccessibleElement):
    """The COM element for `element`, found again by runtime id under its host.

    Re-walked rather than held: a COM pointer from an earlier walk may be
    stale, and the runtime id is the identity UIA itself uses.
    """
    if element.class_name == winapi.POPUP_MENU_CLASS:
        raise ElementError("a menu item has no accessibility surface; it is "
                           "clicked at its rectangle")
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


def click_posted(element: AccessibleElement, *, button: str = "left",
                 modifiers=(), at=None, count: int = 1, hover: bool = False) -> bool:
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
    if at is None:
        point = wintypes.POINT((left + right) // 2, (top + bottom) // 2)
    else:
        # `at` is relative to the element's own top-left corner.
        point = wintypes.POINT(left + int(at[0]), top + int(at[1]))
    if not user32.ScreenToClient(wintypes.HWND(element.host_handle), ctypes.byref(point)):
        return False
    # The window under the point, not the host as such: an element drawn on
    # a windowed child of its host is reached through that child (D66).
    target, tx, ty = deepest_child_at(element.host_handle, point.x, point.y)
    return post_click(target, tx, ty, button=button, modifiers=modifiers, count=count,
                      hover=hover)


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


# --- an embedded engine wakes on the first question -----------------------------

#: How long to give a dormant engine to publish its document after the
#: first walk asked for it. Measured on Chromium: the first walk returned
#: the browser chrome alone, the next one a second later carried the page.
WAKE_TIMEOUT_S = 3.0
CLEAR_TIMEOUT_S = 1.0
WAKE_POLL_S = 0.25


def walk_elements_awake(node: WindowNode, **kw) -> list[tuple[AccessibleElement, tuple[AccessibleElement, ...]]]:
    """`walk_elements`, giving an embedded engine time to wake.

    A Chromium-based host keeps its accessibility tree dormant until an
    assistive client asks -- the region model reports it as `web-document`
    with nothing reachable. The first walk *is* the ask: it reaches the
    engine as a WM_GETOBJECT, the engine enables accessibility, and about
    a second later the page is there. So under a web host, a walk that
    finds no Document is repeated until one appears or the wake budget is
    spent. Outside a web host the first walk is the answer.
    """
    from ...surface import is_web_host

    walked = walk_elements(node, **kw)
    if not is_web_host(node.class_name) or _has_document(walked):
        return walked
    deadline = time.monotonic() + WAKE_TIMEOUT_S
    while time.monotonic() < deadline:
        time.sleep(WAKE_POLL_S)
        walked = walk_elements(node, **kw)
        if _has_document(walked):
            break
    return walked


def _has_document(walked) -> bool:
    return any(e.control_type == "Document" for e, _ in walked)


# --- typing into an element, through its host ------------------------------------

def _current_value(element: AccessibleElement) -> str:
    """The element's value now, re-read from the surface; "" if it has none."""
    if "Value" not in element.patterns:
        return ""
    try:
        UIA, live = _live(element)
        return live.GetCurrentPattern(PATTERN_IDS["Value"]) \
            .QueryInterface(UIA.IUIAutomationValuePattern).CurrentValue or ""
    except Exception:
        return element.value or ""


def type_into(element: AccessibleElement, text: str, *, cadence) -> bool:
    """Focus the element with a posted click, then post its host the characters.

    The characters go to the *host* window: an element has no window of
    its own, and the host routes keyboard input to whatever it has
    focused. Measured on Chromium: posted characters reach the page's own
    script, one input event per character. The edit-control selection
    messages `set_text_by_typing` sends first are not used here because a
    web host ignores them; this appends at the caret.
    """
    if not click_posted(element):
        return False
    time.sleep(0.15)
    return win_input.send_keys(element.host_handle, list(text), cadence=cadence)


def replace_value(element: AccessibleElement, text: str, *, cadence) -> bool:
    """Clear what the element holds with keys it must honour, then type.

    No select-all: a posted Ctrl+A carries no modifier state (the target
    reads the real keyboard for that), so the field is cleared the only
    way posted keys can -- End, then one Backspace per character it holds
    -- and the new text typed after. Every key here is one a person's
    keyboard would send, which is the point.
    """
    if not click_posted(element):
        return False
    time.sleep(0.15)
    held = len(_current_value(element))
    if held:
        if not win_input.send_keys(element.host_handle,
                                   ["end"] + ["backspace"] * held, cadence=cadence):
            return False
        # Wait for the clearing to land before typing. Measured on Chromium
        # at machine speed: key-downs and characters travel different paths
        # to the renderer, and one backspace was applied *after* the text
        # that followed it, leaving the field one character short. Typing
        # only once the field reads empty makes the order a fact rather
        # than a race.
        deadline = time.monotonic() + CLEAR_TIMEOUT_S
        while _current_value(element) and time.monotonic() < deadline:
            time.sleep(0.05)
    return win_input.send_keys(element.host_handle, list(text), cadence=cadence)


def send_keys_into(element: AccessibleElement, keys: list[str], *, cadence) -> bool:
    if not click_posted(element):
        return False
    time.sleep(0.15)
    return win_input.send_keys(element.host_handle, list(keys), cadence=cadence)


def set_value_via_pattern(element: AccessibleElement, text: str) -> bool:
    """Tier 1: the Value pattern. Commits on Chromium (measured: one input
    event and a change event); does not on the native HWND bridge (D21).
    Which is why it is offered only under a commit expectation."""
    if "Value" not in element.patterns:
        return False
    try:
        UIA, live = _live(element)
        live.GetCurrentPattern(PATTERN_IDS["Value"]) \
            .QueryInterface(UIA.IUIAutomationValuePattern).SetValue(text)
        return True
    except Exception:
        return False


#: How long the menu is given to show the item highlighted, and then to end
#: once Return has been posted. Bounds on a wait for a condition, not
#: delays: a menu that answers at once costs one poll of each.
MENU_HIGHLIGHT_S = 1.0
MENU_END_S = 2.0
MENU_POLL_S = 0.02

#: How long to keep asking a menu window that has not answered *at all*.
#: Separate from the phases above because it bounds a different thing: not
#: "has the menu done what was asked" but "has the menu spoken yet". A
#: loaded machine takes longer to answer without any of it meaning the menu
#: has gone (#190).
MENU_ANSWER_S = 1.0


def menu_choose(element: AccessibleElement, *, sleep=time.sleep,
                now=time.monotonic) -> bool:
    """Tier 3 for a popup-menu item: the menu selects it and Enter runs it.

    A button pair posted at an item's rectangle is handled by the menu's
    modal loop, which hit-tests the *real* cursor position rather than the
    message's, so on a menu that is not under the pointer the click lands
    outside and the menu closes with nothing chosen (#135). The route the
    menu itself provides is the keyboard: highlight the item by position
    (`MN_SELECTITEM`) and post Return to the menu window. The menu then
    does exactly what it does for a person -- ends, and hands the command
    to its owner the way it was set up to, WM_COMMAND or a return value
    alike -- so nothing here needs to know how the application listens.

    A greyed item is refused by name rather than pressed; a submenu is
    declined so the posted route can open it.

    **Each phase is confirmed, and the one that fails is named (#145).**
    The route failed intermittently on CI with nothing to say which half
    had not happened. So: the item must read back as highlighted before
    Return is posted, and the menu must end after it -- a menu's answer to
    Return is to go away. Either not happening raises with how long was
    waited, which the result carries as `declined`; and because this
    returns only once the menu has ended, the caller's postcondition clock
    starts when the choice was actually made rather than when a keystroke
    was queued. Not a retry: re-selecting an item is idempotent, and Return
    is posted once.

    **A menu that has not answered is not a menu that has gone (#190).**
    Every read here goes out as `SendMessageTimeout`, so a machine under
    load can fail to answer inside the timeout -- which used to read as "no
    menu" and produced the one diagnosis a caller cannot act on: reopen a
    menu that never closed. An unanswered read is now waited out against
    `MENU_ANSWER_S` and counted, and the counts ride in what this raises,
    because a phase that expired with reads outstanding failed for a
    different reason than one that expired with the menu answering.
    """
    from . import input as win_input

    hwnd = element.host_handle
    index = element.runtime_id[1]
    unanswered = 0

    started = now()
    while True:
        state = winapi.popup_menu_item_state(hwnd, index)
        if state is not None:
            break
        if not winapi.popup_menu_showing(hwnd):
            # Silence from a window that is not up is not a late answer.
            # `IsWindow`/`IsWindowVisible` cost no message and cannot time
            # out, so they settle the ambiguity the read cannot.
            state = {"present": False}
            break
        unanswered += 1
        if now() - started >= MENU_ANSWER_S:
            raise LookupError(
                f"the menu window did not answer {unanswered} read(s) over "
                f"{int((now() - started) * 1000)} ms, so whether it is still showing is "
                "not known; nothing was sent to it")
        sleep(MENU_POLL_S)
    if not state["present"]:
        raise LookupError(
            "the menu is no longer showing. If the posted click before this closed it "
            "without acting, this menu hit-tests the real pointer: open it again and "
            "click with menu_by_keyboard=true, or set menus_by_keyboard in the profile")
    if not state["enabled"]:
        raise LookupError(f"menu item {element.sibling_index} is greyed out; the "
                          "application is not offering it right now")
    if state["submenu"]:
        return False
    started = now()
    selects = unacknowledged = 0
    while True:
        if not winapi.popup_menu_select(hwnd, index):
            unacknowledged += 1
        selects += 1
        state = winapi.popup_menu_item_state(hwnd, index)
        if state is None:
            unanswered += 1
        elif not state["present"]:
            raise LookupError(
                f"the menu stopped showing while its item was being selected, after "
                f"{selects} select(s); nothing was chosen")
        elif state["highlighted"]:
            break
        if now() - started >= MENU_HIGHLIGHT_S:
            raise LookupError(
                f"menu item {element.sibling_index} never read back as highlighted: "
                f"{selects} selects ({unacknowledged} unacknowledged, {unanswered} read(s) "
                f"unanswered) over {int((now() - started) * 1000)} ms, so Return was not "
                "posted")
        sleep(MENU_POLL_S)

    if not winapi.popup_menu_showing(hwnd):
        # The gap the phases left open: the item read as highlighted and the
        # menu went away before Return could be posted. The menu then ended
        # with nothing chosen and no keystroke of ours to account for it,
        # which is what the caller needs told apart from a Return that was
        # sent and ignored (#190).
        raise LookupError(
            f"the menu ended after item {element.sibling_index} read as highlighted and "
            "before Return was posted, so nothing was chosen")

    scan = win_input.user32.MapVirtualKeyW(win_input.VK_RETURN, win_input.MAPVK_VK_TO_VSC)
    down = 1 | (scan << 16)
    up = down | (1 << 30) | (1 << 31)
    target = wintypes.HWND(hwnd)
    ok = bool(win_input.user32.PostMessageW(target, win_input.WM_KEYDOWN, win_input.VK_RETURN, down))
    ok &= bool(win_input.user32.PostMessageW(target, win_input.WM_KEYUP, win_input.VK_RETURN, up))
    if not ok:
        raise LookupError("Return could not be posted to the menu window")

    posted_at = now()
    while winapi.popup_menu_showing(hwnd):
        if now() - posted_at >= MENU_END_S:
            raise LookupError(
                f"Return was posted to highlighted item {element.sibling_index} "
                f"(after {selects} select(s), {unanswered} read(s) unanswered) "
                f"and the menu is still showing "
                f"{int((now() - posted_at) * 1000)} ms later: its loop has not "
                "consumed the key")
        sleep(MENU_POLL_S)
    return True
