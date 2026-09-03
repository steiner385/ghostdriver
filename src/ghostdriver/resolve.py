"""Pure locator resolution against a WindowNode tree.

No platform calls. Everything here is testable on any OS, which is why the
backend's only job is producing the tree (spec section 3.2).
"""

import fnmatch
import re

from .model.element import AccessibleElement
from .model.locator import Locator
from .model.result import ErrorKind, GhostdriverError
from .model.window import WindowNode


def _text_matches(pattern: str, value: str) -> bool:
    """Exact match, unless the pattern is /slash-delimited/, then regex."""
    if len(pattern) >= 2 and pattern.startswith("/") and pattern.endswith("/"):
        return re.search(pattern[1:-1], value) is not None
    return pattern == value


def _node_matches(node: WindowNode, loc: Locator) -> bool:
    if loc.visible is not None and node.visible != loc.visible:
        return False
    if loc.class_name is not None and not fnmatch.fnmatchcase(
        node.class_name, loc.class_name
    ):
        return False
    if loc.text is not None and not _text_matches(loc.text, node.text):
        return False
    # `role` is a normalized label supplied by a profile; Iteration 1 has no
    # role mapping, so a role predicate matches nothing rather than
    # silently matching everything. Locator.parse refuses `role=` outright
    # for the same reason, so this branch is reachable only from a locator
    # built in code or loaded from a profile.
    return loc.role is None


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


def resolve(tree: WindowNode, locator: Locator) -> list[WindowNode]:
    """Return every node matching `locator`, in pre-order.

    `index`, when set, selects one match from that ordered list and is
    applied last. An out-of-range index yields no matches rather than an
    error, so callers distinguish "not there" from "ambiguous" uniformly.
    """
    matches: list[WindowNode] = []
    for node, ancestors in _walk_with_ancestors(tree):
        if not _node_matches(node, locator):
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


def resolve_one(tree: WindowNode, locator: Locator) -> WindowNode:
    """Resolve to exactly one node, or raise.

    Ambiguity is an error rather than a silent first-match, because on a
    target with ~1,100 windows a silent first-match is how a test starts
    asserting against the wrong control.
    """
    matches = resolve(tree, locator)
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

def _element_matches(element: AccessibleElement, loc: Locator) -> bool:
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
    return loc.role is None


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
) -> list[AccessibleElement]:
    """Every element in `walked` matching `locator`, in walk order.

    `walked` pairs each element with its ancestors on the accessibility
    surface (root-first); `host_chain` is the window the walk was rooted
    at and its ancestors (root-first), shared by every element in it.
    `index` picks one match from the ordered list, applied last, as for
    windows.
    """
    matches: list[AccessibleElement] = []
    for element, ancestors in walked:
        if not _element_matches(element, locator):
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
