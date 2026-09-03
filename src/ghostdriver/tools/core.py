"""The plumbing every tool family shares.

The dataclass here owns the session manager and the hidden desktops;
the helpers resolve locators, gate actuation and shape results. Tool
families subclass it, and `Toolbox` in the package root composes them.
The rules every result follows are stated in the package docstring.
"""

from dataclasses import dataclass, field
from typing import Any

from ..disturbance import INPUT_SENSITIVE_HINT
from ..model.locator import Locator
from ..model.result import ErrorKind, GhostdriverError
from ..model.window import WindowNode, select_main_tree
from ..resolve import resolve
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


def _element(node: WindowNode) -> dict:
    """One element, described so a caller can find it again."""
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
        from ..backends.windows.enumerate import enumerate_process

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
        from ..backends.windows.modality import top_level_state
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

    def _resolve(
        self, session, expression: str, all_windows: bool
    ) -> list[WindowNode]:
        locator = Locator.parse(expression)
        return [
            node
            for tree in self._trees(session, all_windows)
            for node in resolve(tree, locator)
        ]

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

        try:
            self.sessions.check_caption(session_id, node.text)
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
        from ..backends.windows.text import is_protected

        if not is_protected(node.handle):
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

        from ..backends.windows.modality import surface_of

        return notes.cadence_for(surface_of(handle))

    def _actuator(self, session):
        from ..actuate import Actuator
        from ..backends.windows.modality import snapshot

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
        from ..backends.windows.modality import surface_of
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
        from ..backends.windows.text import read_window_text

        where = expect.get("locator")
        wanted = expect.get("text")
        if not where:
            return None, None
        Locator.parse(where)  # raises ValueError, caught by the caller

        def holds() -> bool:
            found = self._resolve(session, where,
                                  expect.get("all_windows", False))
            if not found:
                return False
            if wanted is None:
                return True
            return any((read_window_text(n.handle) or "") == wanted
                       for n in found)

        described = (
            f"{where} exists" if wanted is None
            else f"{where} reads {wanted!r}"
        )
        return Condition(holds, described), described
