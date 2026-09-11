"""Elements that are not windows, on the AT-SPI surface (#104, D#104).

On Windows an element is a UIA node under a window, driven through a pattern
or a posted click at its rectangle. On Linux the whole tree is accessibles
already -- a `WindowNode` and an `AccessibleElement` are two views of the
same AT-SPI node -- so an element here carries the node's own handle, and
`verbs.click_element(e)` drives that accessible directly through its Action
interface. There is no host window to post to and no coordinate to convert.

**Built from the registry, not a second walk.** `tree` already fetched every
node's role, name, states and interfaces during enumeration and kept them on
the `_Entry` behind each handle. So the element view is assembled from the
`WindowNode` tree the caller already holds (its rects) plus those cached
entries -- on Studio that is 2,300 nodes not walked twice over the bus.

Why the element view exists at all, given the tree has these nodes: the tool
layer's element locators (`type=`, `name=`) resolve here, and the identity
an unnamed control has -- Studio's setting fields are unnamed `text` nodes --
is **position plus value** (D#101). So an element carries its screen extents
and, for a field, is matchable by what it shows, which the disclosure policy
(D#34b) makes a comparison, never a disclosure: `value` is left None and the
resolver confirms it instead.

`gi` is imported inside the functions: this module is loaded on Windows by
`tests/test_backends.py`, which checks that the Linux backend refuses.
"""

from __future__ import annotations

from ...model.element import AccessibleElement
from ...model.window import WindowNode
from . import tree
from .deadline import call_with_deadline
from .protection import Disclosure, classify

#: AT-SPI interfaces that map onto the pattern names the neutral layer reads.
#: An editable text entry carries `EditableText`, which is the writable
#: surface here, so it is reported as `Value` -- what `set_value` and
#: `_current_value` look for -- even though AT-SPI keeps them distinct.
_WRITABLE = frozenset({"EditableText", "Value"})

#: Roles a person selects one of, reported as the neutral `SelectionItem`
#: even when AT-SPI carries the state rather than a pattern.
_SELECTABLE_ROLES = frozenset({
    "radio button", "page tab", "list item", "table cell", "toggle button",
    "check box", "menu item",
})


def _patterns(role: str, interfaces: frozenset[str], states: frozenset[str]) -> tuple[str, ...]:
    out: list[str] = []
    if interfaces & _WRITABLE:
        out.append("Value")
    if role in _SELECTABLE_ROLES or "SELECTED" in states or "CHECKED" in states:
        out.append("SelectionItem")
    return tuple(out)


def _element_of(node: WindowNode, sibling_index: int) -> AccessibleElement:
    """Build an element from a `WindowNode` and its cached registry entry."""
    entry = tree._entry(node.handle)
    interfaces = frozenset(entry.interfaces)
    states = entry.states
    patterns = _patterns(entry.role, interfaces, states)
    selected: bool | None = None
    if "SelectionItem" in patterns:
        selected = ("SELECTED" in states) or ("CHECKED" in states)
    return AccessibleElement(
        runtime_id=(node.handle,),
        control_type=entry.role,
        name=entry.name,
        automation_id="",
        class_name=entry.role,
        rect=node.rect,
        enabled="SENSITIVE" in states,
        offscreen="SHOWING" not in states,
        patterns=patterns,
        # An element here *is* its own window: its handle is the accessible
        # `verbs.click_element(e)` drives directly (D#104).
        host_handle=node.handle,
        host_class=entry.role,
        sibling_index=sibling_index,
        selected=selected,
        # Withheld by class (D#34b): the resolver confirms it without
        # disclosing, so the element leaves it None. An allowed control's
        # text is its name.
        value=None,
        pid=node.pid,
        is_password=entry.role == "password text",
    )


def walk_elements_awake(node: WindowNode, **_kw) -> list[
        tuple[AccessibleElement, tuple[AccessibleElement, ...]]]:
    """Every accessible under `node`'s window, each with its ancestors.

    The window's own node is the root and is not returned -- it is the
    window, which the window tree already names. No wake step: the
    embedded-document case (L8, #15) is unmeasured on Linux, so there is no
    dormant engine to nudge; the name keeps the contract's shape for when
    one is measured, as on Windows.
    """
    out: list[tuple[AccessibleElement, tuple[AccessibleElement, ...]]] = []

    def visit(wn: WindowNode, ancestors: tuple[AccessibleElement, ...]) -> None:
        by_role: dict[str, int] = {}
        for child in wn.children:
            role = child.class_name
            by_role[role] = by_role.get(role, 0) + 1
            try:
                described = _element_of(child, by_role[role])
            except KeyError:
                # The registry dropped this handle between the walk and here
                # (a control that vanished); skip it rather than raise.
                continue
            out.append((described, ancestors))
            visit(child, ancestors + (described,))

    visit(node, ())
    return out


def is_selected(element: AccessibleElement) -> bool | None:
    """The element's selection state now, re-read; None if it carries none.

    Re-read from the live accessible rather than the enumeration's cached
    states, because the state that proves a radio or tab click worked is the
    one *after* the click.
    """
    if element.selected is None:
        return None
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    node = tree._accessible(element.host_handle)
    got = call_with_deadline(node.get_state_set)
    if got is None:
        return None
    return (got.contains(Atspi.StateType.SELECTED)
            or got.contains(Atspi.StateType.CHECKED))


def _current_value(element: AccessibleElement) -> str:
    """The element's shown text now, re-read; "" when it has none or is
    withheld.

    A field whose contents are withheld by class (D#34b) is not read here:
    returning its text would disclose exactly the value the policy declines
    to. `set_value` already knows what it wrote and checks by confirmation,
    so the "" this returns for such a field is not a lost comparison.
    """
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    entry = tree._entry(element.host_handle)
    if classify(entry.role, entry.states) is not Disclosure.ALLOWED:
        return ""
    node = entry.accessible
    if "Text" not in entry.interfaces:
        return call_with_deadline(node.get_name) or ""

    def read() -> str:
        n = Atspi.Text.get_character_count(node)
        return Atspi.Text.get_text(node, 0, n)

    return call_with_deadline(read) or ""
