"""The plumbing every tool family shares.

The dataclass here owns the session manager and the hidden desktops;
the helpers resolve locators, gate actuation and shape results. Tool
families subclass it, and `Toolbox` in the package root composes them.
The rules every result follows are stated in the package docstring.
"""

from dataclasses import dataclass, field
from typing import Any

from ..disturbance import INPUT_SENSITIVE_HINT
from ..model.element import AccessibleElement
from ..model.locator import Locator
from ..model.result import ErrorKind, GhostdriverError
from ..model.window import WindowNode, select_main_tree
from ..resolve import resolve, resolve_elements
from ..session import SessionManager

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

    def _trees(self, session, all_windows: bool) -> list[WindowNode]:
        from ..backends import current
        enumerate_process = current().enumerate_process

        # session.run so a hidden-desktop target is enumerated on its own
        # desktop thread; a plain call otherwise.
        trees = session.run(lambda: enumerate_process(session.pid))
        if not trees:
            return []
        if all_windows:
            return sorted(trees, key=lambda t: -sum(1 for _ in t.walk()))
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

        state = session.run(lambda: top_level_state(session.pid))
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
        if not locator.is_element:
            return [node for tree in trees for node in resolve(tree, locator)]

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
        found: list = []
        for root, chain in roots:
            walked = session.run(lambda r=root: walk_elements_awake(r))
            found.extend(resolve_elements(walked, chain, locator))
        return found

    #
    # Every tool here runs the same four steps before it touches anything:
    # resolve to exactly one element, refuse a denylisted caption, refuse a
    # held application, and pick a cadence. They are in that order because
    # each one makes the next meaningful -- there is no point asking whether
    # a caption is denied until it is known which element is being named.

    def _one(self, session, locator: str, all_windows: bool):
        """The single element `locator` names, or an error explaining why not.

        Actuation refuses ambiguity outright, where a read merely caps it.
        A read of eight matching fields returns eight values and the caller
        sees what happened; a click on eight matching buttons picks one at
        random and the caller finds out afterwards.
        """
        try:
            matches = self._resolve(session, locator, all_windows)
        except ValueError as exc:
            return None, _error(ErrorKind.NOT_FOUND, str(exc), locator=locator)
        if not matches:
            return None, _error(
                ErrorKind.NOT_FOUND,
                f"no element matches {locator!r}"
                + ("" if all_windows else
                   "; menus, dropdowns and dialogs are separate top-level "
                   "windows, so try all_windows=true"),
                locator=locator,
            )
        if len(matches) > 1:
            return None, _error(
                ErrorKind.AMBIGUOUS,
                f"{len(matches)} elements match {locator!r}; actuation needs "
                "exactly one. Add within=... to scope it, or index=N to pick",
                locator=locator,
                candidates=[_element(n) for n in matches[:MAX_ELEMENTS]],
            )
        return matches[0], None

    def _prepared(self, session_id: str, tool: str, locator: str,
                  all_windows: bool, cadence: str | None):
        """Everything an actuation needs, or the first reason it cannot run."""
        try:
            session = self.sessions.authorize(session_id, tool)
        except GhostdriverError as exc:
            return None, _error(exc.kind, exc.message)

        node, failure = self._one(session, locator, all_windows)
        if failure is not None:
            return None, failure

        identities = (node.identities() if isinstance(node, AccessibleElement)
                      else [node.text])
        try:
            self.sessions.check_identity(session_id, identities)
        except GhostdriverError as exc:
            return None, _error(exc.kind, exc.message, locator=locator)

        try:
            pace = self._cadence(session, node.handle, cadence)
        except ValueError as exc:
            return None, _error(ErrorKind.DENIED_BY_POLICY, str(exc))

        return _Prepared(session=session, node=node, cadence=pace), None

    def _refuse_if_protected(self, node, what: str) -> dict | None:
        """Never put characters into a field that hides its contents.

        A password box is the one control where the right answer is always
        a person. The value would have to pass through this process to be
        typed, and there is no version of that worth the convenience --
        so the boundary is here, in code, rather than in a caller\'s
        judgement.

        Named keys are a different question and are allowed: `tab` out of a
        field a person has filled in, or `enter` to submit it, carries
        nothing.
        """
        from ..backends import current
        is_protected = current().is_protected

        if isinstance(node, AccessibleElement):
            if not node.is_password:
                return None
        elif not is_protected(node.handle):
            return None
        return _error(
            ErrorKind.DENIED_BY_POLICY,
            f"refusing to {what} a field that hides its contents. Passwords "
            "and the like are for a person to type: use await_human to ask "
            "them, then carry on once they have",
        )

    def _cadence(self, session, handle: int, requested: str | None):
        """What to type at: the caller\'s choice, else what is known.

        A caller who names one gets it. Otherwise the profile decides, and
        the surface is only worked out when some note actually distinguishes
        surfaces -- the cheap answer costs a walk up the ancestor chain, and
        there is no reason to pay it on a target nobody has annotated.
        """
        from ..cadence import ROBOT, by_name

        if requested is not None:
            return by_name(requested)
        notes = session.profile.sensitivity
        if not notes.notes:
            return ROBOT
        if all(n.surface == "*" for n in notes.notes):
            return notes.cadence_for()

        from ..backends import current
        surface_of = current().surface_of

        return notes.cadence_for(surface_of(handle))

    def _actuator(self, session):
        from ..actuate import Actuator
        from ..backends import current
        snapshot = current().snapshot

        return Actuator(observe=lambda: session.run(
            lambda: snapshot(session.pid)))

    def _perform(self, session, attempts, **kw):
        """Run an actuation where the target can be seen.

        The whole perform is marshalled, not each message: verb posts, the
        settle, the observe snapshot and any postcondition all have to run
        on the target's desktop thread, and running perform there once puts
        every part of it in the right place. session.run is re-entrant, so
        the snapshot and conditions inside -- which call back through the
        session -- execute inline rather than deadlocking.
        """
        return session.run(lambda: self._actuator(session).perform(attempts, **kw))

    def _remember(self, session_id: str, tool: str, locator: str,
                  prepared, result) -> None:
        """Record the outcome, so a later claim about it can be checked.

        Every actuation, not only failures: a differential needs both
        halves, and the successful paced attempt is the half that makes the
        failure mean something.
        """
        from ..backends import current
        surface_of = current().surface_of
        from ..ledger import Outcome

        try:
            surface = surface_of(prepared.node.handle)
        except Exception:
            surface = "native"
        self.sessions.ledger.record(session_id, Outcome(
            locator=locator, tool=tool, cadence=prepared.cadence.name,
            ok=bool(result.ok), surface=surface,
        ))

    def _reported(self, result, prepared, locator: str, **extra) -> dict:
        """One shape for every actuation outcome, successful or not.

        `disturbances` is present either way. A dialog that appeared next to
        a *successful* action is the case that motivated collecting them at
        all, so hiding it behind failure would defeat the point.
        """
        reported = {
            "ok": result.ok,
            "locator": locator,
            "element": _element(prepared.node),
            "tier_used": result.tier_used,
            "tiers_attempted": result.tiers_attempted,
            "cadence": prepared.cadence.name,
            "elapsed_ms": result.elapsed_ms,
            "disturbances": result.disturbances,
            **extra,
        }
        if result.error is not None:
            error = dict(result.error)
            if result.disturbances:
                error["message"] += (
                    f"; {len(result.disturbances)} other change(s) happened "
                    "around this action -- see disturbances. " + SENSITIVE_HINT
                )
            reported["error"] = error
        return reported

    def _expectation(self, session, expect: dict | None):
        """Turn a caller\'s `expect` into a condition, re-resolved each time.

        Re-resolving rather than holding a handle is the point: the element
        that proves an action worked may not exist until the action has
        worked. A handle captured beforehand would be stale or absent
        exactly when the check matters.

        The locator is parsed *here*, before anything is sent, and a bad one
        is an error rather than an unmet condition. Those look identical from
        the outside and mean opposite things: one says the application did
        not do what you expected, the other says you mistyped. Reporting the
        second as the first sends a caller looking at their target when the
        problem is their query -- and since a malformed locator can never
        hold, the action would fail every time and look like a target that
        never responds.
        """
        if not expect:
            return None, None

        from ..actuate import Condition
        from ..backends import current
        read_window_text = current().read_window_text

        where = expect.get("locator")
        wanted = expect.get("text")
        selected = expect.get("selected")
        if not where:
            return None, None
        Locator.parse(where)  # raises ValueError, caught by the caller

        def text_of(found) -> str:
            # An element's text is its name, or its value when it has one;
            # a window's is what it answers to a text query.
            if isinstance(found, AccessibleElement):
                return found.value if found.value is not None else found.name
            return read_window_text(found.handle) or ""

        def holds() -> bool:
            found = self._resolve(session, where,
                                  expect.get("all_windows", False))
            if not found:
                return False
            if selected is not None:
                # Re-read from the surface, not from the walk that found
                # it: the state that proves a tab click worked is the one
                # after the click.
                from ..backends import current
                is_selected = current().is_selected

                if not all(isinstance(n, AccessibleElement)
                           and is_selected(n) == bool(selected) for n in found):
                    return False
            if wanted is None:
                return True
            return any(text_of(n) == wanted for n in found)

        described = f"{where} exists"
        if selected is not None:
            described = f"{where} is {'selected' if selected else 'not selected'}"
        if wanted is not None:
            described = f"{where} reads {wanted!r}"
        return Condition(holds, described), described


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
