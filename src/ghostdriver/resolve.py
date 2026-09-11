"""Pure locator resolution against a WindowNode tree.

No platform calls. Everything here is testable on any OS, which is why the
backend's only job is producing the tree (spec section 3.2).

One predicate cannot be decided from the tree alone: `value=`. A node's
current contents are a read, and on Linux a read of an editable field is
withheld by class (D#34b). So a locator carrying `value` is resolved with a
`confirm` callback the caller supplies -- "does this node show this
string", yes or no -- and the contents never pass through here. A locator
with `value` and no `confirm` is refused rather than matched loosely: a
place-plus-value locator exists to make a wrong-field write impossible, and
silently dropping the value half would make it merely unlikely (D#105).
"""

import fnmatch
import re
from collections.abc import Callable

from .model.element import AccessibleElement
from .model.locator import Locator
from .model.result import ErrorKind, GhostdriverError
from .model.window import WindowNode

#: Answers whether a node currently shows `expected`; None when it did not
#: answer, which is not a match either way.
Confirm = Callable[[object, str], bool | None]


def _text_matches(pattern: str, value: str) -> bool:
    """Exact match, unless the pattern is /slash-delimited/, then regex."""
    if len(pattern) >= 2 and pattern.startswith("/") and pattern.endswith("/"):
        return re.search(pattern[1:-1], value) is not None
    return pattern == value


def _in_region(rect: tuple[int, int, int, int], region: tuple[int, int, int, int],
               origin: tuple[int, int]) -> bool:
    """Whether the rect's centre lies in `region`, given in the coordinates
    of the window whose top-left is `origin` (screen coordinates)."""
    cx = (rect[0] + rect[2]) // 2 - origin[0]
    cy = (rect[1] + rect[3]) // 2 - origin[1]
    left, top, right, bottom = region
    return left <= cx < right and top <= cy < bottom


def _value_matches(node: object, loc: Locator, confirm: Confirm | None,
                   shown: str | None = None) -> bool:
    """The `value=` half. A published value is compared directly; otherwise
    the caller's `confirm` decides, and no `confirm` is a refusal."""
    if loc.value is None:
        return True
    if shown is not None:
        return shown == loc.value
    if confirm is None:
        raise GhostdriverError(
            ErrorKind.NOT_ACTIONABLE,
            "value= needs a reader: this resolution was given no way to "
            "confirm what a control shows, so a place-plus-value locator "
            "cannot be honoured here",
        )
    return confirm(node, loc.value) is True


def _node_matches(node: WindowNode, loc: Locator, *,
                  origin: tuple[int, int] = (0, 0),
                  confirm: Confirm | None = None) -> bool:
    if loc.handle is not None and node.handle != loc.handle:
        return False
    if loc.enabled is not None and node.enabled != loc.enabled:
        return False
    if loc.visible is not None and node.visible != loc.visible:
        return False
    if loc.class_name is not None and not fnmatch.fnmatchcase(
        node.class_name, loc.class_name
    ):
        return False
    if loc.text is not None and not _text_matches(loc.text, node.text):
        return False
    if loc.region is not None and not _in_region(node.rect, loc.region, origin):
        return False
    # `role` is a normalized label supplied by a profile; Iteration 1 has no
    # role mapping, so a role predicate matches nothing rather than
    # silently matching everything. Locator.parse refuses `role=` outright
    # for the same reason, so this branch is reachable only from a locator
    # built in code or loaded from a profile.
    if loc.role is not None:
        return False
    # Last, because it is the only predicate that costs a read.
    return _value_matches(node, loc, confirm)


def _walk_with_ancestors(
    node: WindowNode, ancestors: tuple[WindowNode, ...] = ()
):
    yield node, ancestors
    for child in node.children:
        yield from _walk_with_ancestors(child, ancestors + (node,))


def _ancestor_matches(
    ancestors: tuple[WindowNode, ...], loc: Locator
) -> bool:
    """True when some ancestor matches `loc`, including `loc`'s own nested within.

    `ancestors` is ordered root-first, so the ancestors of the element at
    index i are exactly ancestors[:i]. Scoping is therefore checked against
    a strictly shorter chain at each level and always terminates.
    """
    for i, ancestor in enumerate(ancestors):
        if not _node_matches(ancestor, loc):
            continue
        if loc.within is None:
            return True
        if _ancestor_matches(ancestors[:i], loc.within):
            return True
    return False


def resolve(tree: WindowNode, locator: Locator, *,
            confirm: Confirm | None = None) -> list[WindowNode]:
    """Return every node matching `locator`, in pre-order.

    `index`, when set, selects one match from that ordered list and is
    applied last. An out-of-range index yields no matches rather than an
    error, so callers distinguish "not there" from "ambiguous" uniformly.

    A `region` is read in `tree`'s own coordinates -- its rect origin --
    and a `value` is decided by `confirm`.
    """
    origin = (tree.rect[0], tree.rect[1])
    matches: list[WindowNode] = []
    for node, ancestors in _walk_with_ancestors(tree):
        if not _node_matches(node, locator, origin=origin, confirm=confirm):
            continue
        if locator.within is not None and not _ancestor_matches(
            ancestors, locator.within
        ):
            continue
        matches.append(node)

    if locator.index is not None:
        if 0 <= locator.index < len(matches):
            return [matches[locator.index]]
        return []
    return matches


def resolve_one(tree: WindowNode, locator: Locator, *,
                confirm: Confirm | None = None) -> WindowNode:
    """Resolve to exactly one node, or raise.

    Ambiguity is an error rather than a silent first-match, because on a
    target with ~1,100 windows a silent first-match is how a test starts
    asserting against the wrong control.
    """
    matches = resolve(tree, locator, confirm=confirm)
    if not matches:
        raise GhostdriverError(
            ErrorKind.NOT_FOUND,
            f"no element matched {locator.describe()}",
            locator.describe(),
        )
    if len(matches) > 1:
        raise GhostdriverError(
            ErrorKind.AMBIGUOUS,
            f"{len(matches)} elements matched {locator.describe()}; "
            f"add within=... or index=N",
            locator.describe(),
        )
    return matches[0]


# --- elements that are not windows ------------------------------------------

def _element_matches(element: AccessibleElement, loc: Locator, *,
                     origin: tuple[int, int] = (0, 0),
                     confirm: Confirm | None = None) -> bool:
    if loc.handle is not None and element.host_handle != loc.handle:
        return False
    if loc.enabled is not None and element.enabled != loc.enabled:
        return False
    if loc.visible is not None and element.visible != loc.visible:
        return False
    if loc.control_type is not None and not fnmatch.fnmatchcase(
        element.control_type.lower(), loc.control_type.lower()
    ):
        return False
    # `name=` and `text=` are the same question of an element.
    for wanted in (loc.name, loc.text):
        if wanted is not None and not _text_matches(wanted, element.name):
            return False
    if loc.class_name is not None and not fnmatch.fnmatchcase(
        element.class_name, loc.class_name
    ):
        return False
    if loc.region is not None and not _in_region(element.rect, loc.region, origin):
        return False
    if loc.role is not None:
        return False
    # An element that publishes its value is compared on it; one that does
    # not (withheld, D#34b) is asked through `confirm`.
    return _value_matches(element, loc, confirm, shown=element.value)


def _element_scope_matches(
    ancestors: tuple[AccessibleElement, ...],
    host_chain: tuple[WindowNode, ...],
    loc: Locator,
) -> bool:
    """Whether a `within=` scope holds for an element.

    An element scope (`within=(type=Tab)`) is asked of the element's
    ancestors on the accessibility surface. A window scope
    (`within=(class=SysTabControl32)`) is asked of the host window and its
    ancestors -- the window the element lives in, and everything above it.
    Both nest: each level is checked against a strictly shorter chain.
    """
    if loc.is_element:
        for i, ancestor in enumerate(ancestors):
            if not _element_matches(ancestor, loc):
                continue
            if loc.within is None:
                return True
            if _element_scope_matches(ancestors[:i], host_chain, loc.within):
                return True
        return False
    # A window scope: the host chain is root-first, host last, and the
    # host itself counts -- `within=(class=ToolbarWindow32)` names the
    # window the buttons are *in*, not one above it.
    for i, window in enumerate(host_chain):
        if not _node_matches(window, loc):
            continue
        if loc.within is None:
            return True
        if _ancestor_matches(host_chain[:i], loc.within):
            return True
    return False


def resolve_elements(
    walked: list[tuple[AccessibleElement, tuple[AccessibleElement, ...]]],
    host_chain: tuple[WindowNode, ...],
    locator: Locator,
    *,
    confirm: Confirm | None = None,
) -> list[AccessibleElement]:
    """Every element in `walked` matching `locator`, in walk order.

    `walked` pairs each element with its ancestors on the accessibility
    surface (root-first); `host_chain` is the window the walk was rooted
    at and its ancestors (root-first), shared by every element in it.
    `index` picks one match from the ordered list, applied last, as for
    windows. A `region` is read in the top-level window's coordinates --
    the first of `host_chain` -- so it means the same thing for an element
    as for a window.
    """
    origin = (host_chain[0].rect[0], host_chain[0].rect[1]) if host_chain else (0, 0)
    matches: list[AccessibleElement] = []
    for element, ancestors in walked:
        if not _element_matches(element, locator, origin=origin, confirm=confirm):
            continue
        if locator.within is not None and not _element_scope_matches(
            ancestors, host_chain, locator.within
        ):
            continue
        matches.append(element)
    if locator.index is not None:
        if 0 <= locator.index < len(matches):
            return [matches[locator.index]]
        return []
    return matches
