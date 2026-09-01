"""Pure locator resolution against a WindowNode tree.

No platform calls. Everything here is testable on any OS, which is why the
backend's only job is producing the tree (spec section 3.2).
"""

import fnmatch
import re

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
    # silently matching everything.
    if loc.role is not None:
        return False
    return True


def _walk_with_ancestors(
    node: WindowNode, ancestors: tuple[WindowNode, ...] = ()
):
    yield node, ancestors
    for child in node.children:
        yield from _walk_with_ancestors(child, ancestors + (node,))


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
        if locator.within is not None and not any(
            _node_matches(a, locator.within) for a in ancestors
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
