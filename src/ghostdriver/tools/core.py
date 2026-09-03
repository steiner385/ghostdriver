"""The plumbing every tool family shares.

The dataclass here owns the session manager and the hidden desktops;
the helpers resolve locators, gate actuation and shape results. Tool
families subclass it, and `Toolbox` in the package root composes them.
The rules every result follows are stated in the package docstring.
"""

from dataclasses import dataclass, field, replace
from typing import Any

from ..disturbance import INPUT_SENSITIVE_HINT
from ..model.element import AccessibleElement
from ..model.locator import Locator
from ..model.result import ErrorKind
from ..model.window import WindowNode, select_main_tree
from ..resolve import resolve, resolve_elements
from ..session import SessionManager

#: How long a session's descendant list is trusted before it is re-read.
TREE_CACHE_S = 0.5

#: Most elements any single result will enumerate. A locator matching more
#: than this is almost always a locator that needs narrowing, and returning
#: nine hundred rows to prove it helps nobody.
MAX_ELEMENTS = 50


#: Appended to an actuation failure that has disturbances alongside it.
#: A suggestion, not a conclusion: the tool cannot tell a target refusing
#: machine-speed input from one refusing the value, and the differential is
#: the caller\'s to run -- a second attempt on a target that just flagged the
#: first is a judgement call, and for a non-idempotent action a silent retry
#: is a double click.
SENSITIVE_HINT = INPUT_SENSITIVE_HINT


def _error(kind: ErrorKind, message: str, **extra: Any) -> dict:
    return {"ok": False, "error": {"kind": kind.value, "message": message, **extra}}


@dataclass(frozen=True)
class _Prepared:
    """What every actuation resolved before it ran."""

    session: object
    node: WindowNode
    cadence: object


def _accessible(element: AccessibleElement) -> dict:
    """One element that is not a window, described so a caller can find it again."""
    left, top, right, bottom = element.rect
    described = {
        "type": element.control_type,
        "name": element.name,
        "automation_id": element.automation_id,
        "class": element.class_name,
        "enabled": element.enabled,
        "visible": element.visible,
        "patterns": list(element.patterns),
        "rect": {"left": left, "top": top, "right": right, "bottom": bottom},
        "host": {"class": element.host_class,
                 "handle_ephemeral": f"0x{element.host_handle:08X}"},
        "identities": element.identities(),
        "locator": element.suggested_locator(),
    }
    if element.selected is not None:
        described["selected"] = element.selected
    if element.value is not None:
        described["value"] = element.value
    return described


def _element(node) -> dict:
    """One element, described so a caller can find it again."""
    if isinstance(node, AccessibleElement):
        return _accessible(node)
    left, top, right, bottom = node.rect
    described = {
        "class": node.class_name,
        "text": node.text if node.responsive else None,
        "responsive": node.responsive,
        "visible": node.visible,
        "enabled": node.enabled,
        "rect": {"left": left, "top": top, "right": right, "bottom": bottom},
        # Valid only for this call. Present because it is the only thing that
        # tells two identically-captioned controls apart within one result.
        "handle_ephemeral": f"0x{node.handle:08X}",
        # Which process owns it: a session sees its target's whole process
        # tree, and a dialog in a helper process is worth telling apart.
        "pid": node.pid,
    }
    if node.actionable is False:
        # Only when False, and only then. A control whose own flag is
        # enabled but which sits under a disabled ancestor looks perfectly
        # actionable in a listing, and a caller has no way to tell from the
        # element itself -- so it is worth the bytes. On the ordinary case
        # it says nothing, because every element carrying "actionable": true
        # would cost the result budget for no information.
        described["actionable"] = False
    if node.text:
        described["locator"] = f'class={node.class_name} text="{node.text}"'
    return described


@dataclass
class _ToolboxCore:
    """Every tool, over one session manager."""

    sessions: SessionManager
    #: Hidden desktops this toolbox launched, by session id. Held here
    #: rather than on the platform-neutral Session so that layer stays free
    #: of Windows objects. Torn down when the session is released.
    _desktops: dict = field(default_factory=dict)
    #: Minimized-strategy watches, by session id. Same reasoning: a
    #: thread and a window handle are the backend's, not the Session's.
    _watches: dict = field(default_factory=dict)
    #: (when, pids) per session: the descendant list is asked for on nearly
    #: every call, and a snapshot half a second old is still the truth.
    _tree_cache: dict = field(default_factory=dict)

    def _tree_pids(self, session) -> list[int]:
        """The target and every process descended from it, target first.

        A window the application opens in a helper process -- a browser's
        file dialog, a print dialog -- is the application's window, and a
        session should see it without a second attach. The consent that
        covers the target covers its descendants (session.grant_for), so
        seeing them is consistent with what was approved.
        """
        import time

        cached = self._tree_cache.get(session.session_id)
        if cached is not None and time.monotonic() - cached[0] < TREE_CACHE_S:
            return cached[1]
        from ..backends import current
        try:
            pids = [session.pid] + list(current().descendants(session.pid))
        except Exception:
            pids = [session.pid]
        self._tree_cache[session.session_id] = (time.monotonic(), pids)
        return pids

    def _trees(self, session, all_windows: bool) -> list[WindowNode]:
        from ..backends import current
        enumerate_process = current().enumerate_process

        # session.run so a hidden-desktop target is enumerated on its own
        # desktop thread; a plain call otherwise.
        trees = session.run(lambda: enumerate_process(session.pid))
        if all_windows:
            # Every top-level window of the target and of its descendants,
            # largest first. The main window stays the target's own.
            for pid in self._tree_pids(session)[1:]:
                trees = trees + session.run(lambda p=pid: enumerate_process(p))
            return sorted(trees, key=lambda t: -sum(1 for _ in t.walk()))
        if not trees:
            return []
        # A session under the minimized strategy reads the window it locked
        # at attach. Selecting by visible nodes is the right question for a
        # target a person can see; for one kept minimized it can flip to a
        # proxy window holding none of the UI, and every read would answer
        # about the wrong window forever.
        watch = self._watches.get(session.session_id)
        if watch is not None and watch.main_hwnd is not None:
            locked = [t for t in trees if t.handle == watch.main_hwnd]
            if locked:
                return locked
        main = select_main_tree(trees)
        return [main] if main else []

    def _blocking(self, session) -> list[str]:
        from ..backends import current
        top_level_state = current().top_level_state
        from ..modality import find_modal_blocks

        # Across the process tree: a dialog a helper process owns disables
        # the target's window from outside its pid, and reading the target
        # alone would report a block nothing accounts for.
        state: list = []
        for pid in self._tree_pids(session):
            state = state + session.run(lambda p=pid: top_level_state(p))
        blocks, unexplained = find_modal_blocks(state)
        return (
            [b.describe() for b in blocks]
            + [
                f"{u.blocked.text or u.blocked.class_name} is disabled with "
                "no visible dialog to account for it"
                for u in unexplained
            ]
        )

    def _resolve(self, session, expression: str, all_windows: bool) -> list:
        """Every window or element `expression` names.

        A window locator resolves against the window tree. An element
        locator resolves on the accessibility surface, walked under the
        window its scope names -- or under the main window when it names
        none. A window scope narrows the walk itself, not just the matches:
        `within=(class=SysTabControl32)` walks that control alone, which on
        a target with a thousand windows is the difference between a query
        and a survey.
        """
        locator = Locator.parse(expression)
        trees = self._trees(session, all_windows)
        # `index` picks from the matches across *every* tree searched, so it
        # is applied here, after the trees are combined. Applied inside each
        # tree it could never name a match in the second window -- which,
        # with a session that sees a whole process tree, is exactly where a
        # dialog's controls are.
        index = locator.index
        unindexed = replace(locator, index=None)
        if not locator.is_element:
            found: list = [node for tree in trees for node in resolve(tree, unindexed)]
            return _pick(found, index)

        from ..backends import current
        walk_elements_awake = current().walk_elements_awake

        # Which windows to walk: the outermost *window* scope, if any.
        scope = locator.within
        while scope is not None and scope.is_element:
            scope = scope.within
        roots: list[tuple[WindowNode, tuple[WindowNode, ...]]] = []
        for tree in trees:
            chains = _chains(tree)
            if scope is None:
                roots.append((tree, chains[tree.handle]))
                continue
            for node in resolve(tree, scope):
                roots.append((node, chains[node.handle]))
        found = []
        for root, chain in roots:
            walked = session.run(lambda r=root: walk_elements_awake(r))
            found.extend(resolve_elements(walked, chain, unindexed))
        return _pick(found, index)

def _chains(tree: WindowNode) -> dict[int, tuple[WindowNode, ...]]:
    """For every window in `tree`, the chain from the root down to it."""
    chains: dict[int, tuple[WindowNode, ...]] = {}

    def walk(node: WindowNode, above: tuple[WindowNode, ...]) -> None:
        chain = above + (node,)
        chains[node.handle] = chain
        for child in node.children:
            walk(child, chain)

    walk(tree, ())
    return chains


def _pick(matches: list, index: int | None) -> list:
    """`index` over the combined matches; out of range is no match, not an error."""
    if index is None:
        return matches
    return [matches[index]] if 0 <= index < len(matches) else []
