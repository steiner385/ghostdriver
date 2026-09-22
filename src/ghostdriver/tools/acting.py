"""The plumbing every tool that *acts* shares.

Every actuation runs the same four steps before it touches anything:
resolve to exactly one element, refuse a denylisted identity, refuse a
held application, and pick a cadence. Then it performs under the ladder
and reports one shape. Split from `core` so the reading families do not
carry it; `ActuationTools` and `LearningTools` subclass this.
"""


from typing import Any

from ..model.element import AccessibleElement
from ..model.result import ErrorKind, GhostdriverError
from .core import (
    MAX_ELEMENTS,
    SENSITIVE_HINT,
    _element,
    _error,
    _Prepared,
)
from .deny import _DenyCore
from .drift import whitespace_note
from .expect import _ExpectCore
from .guidance import FOCUS_NOTE


class _ActingCore(_DenyCore, _ExpectCore):
    """Resolve, gate, perform, report: the steps every acting tool shares."""

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
                   "windows, so try all_windows=true")
                + whitespace_note(locator),
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
        refusal = self._denied_region(session, self._aim(node, None), locator)
        if refusal is not None:
            return None, refusal

        try:
            pace = self._cadence(session, node.handle, cadence)
        except ValueError as exc:
            return None, _error(ErrorKind.DENIED_BY_POLICY, str(exc))

        return _Prepared(session=session, node=node, cadence=pace,
                         drift=self._drift_note(session, locator)), None

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

    def _actuator(self, session, *, verify_timeout_s: float | None = None,
                  tiers=None):
        from ..actuate import Actuator
        from ..backends import current
        snapshot = current().snapshot

        observe = lambda: session.run(lambda: snapshot(session.pid))  # noqa: E731
        kw: dict[str, Any] = {"observe": observe}
        if verify_timeout_s is not None:
            kw["verify_timeout_s"] = verify_timeout_s
        if tiers is not None:
            # A live session may reach tier 4 -- the real-Enter commit on the
            # operator's own display (D#111) -- which the default ladder
            # excludes (D9). Passed explicitly, never on by default.
            kw["tiers"] = tiers
        return Actuator(**kw)

    def _perform(self, session, attempts, *, verify_timeout_s: float | None = None,
                 tiers=None, **kw):
        """Run an actuation where the target can be seen.

        The whole perform is marshalled, not each message: verb posts, the
        settle, the observe snapshot and any postcondition all have to run
        on the target's desktop thread, and running perform there once puts
        every part of it in the right place. session.run is re-entrant, so
        the snapshot and conditions inside -- which call back through the
        session -- execute inline rather than deadlocking.
        """
        return session.run(
            lambda: self._actuator(session, verify_timeout_s=verify_timeout_s,
                                   tiers=tiers).perform(attempts, **kw))

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

    def _focus_report(self, prepared) -> dict:
        """Where the target thread's active window and focus stand after an
        action, read with GetGUIThreadInfo: nothing is touched.

        Two grids on one target, same technique: posted row clicks selected
        in one and were ignored by the other. A control decides for itself
        whether to act on a click it has been handed, and some check that
        their window is the thread's active one first; a second top-level
        window of the same thread need not be, and this tool never activates
        one (D55). Reporting the state lets the next session tell that case
        from a click that missed (D64).
        """
        from ..backends import current

        winapi = current().winapi
        handle = prepared.node.handle

        def named(h):
            return None if not h else {"class": winapi.class_name(h), "handle_ephemeral": h}

        def read():
            state = winapi.thread_gui_state(handle)
            root = winapi.root_window(handle)
            active = state["active"]
            return {
                "thread_active_window": named(active),
                "thread_focus": named(state["focus"]),
                "target_window_active": bool(active) and winapi.root_window(active) == root,
            }

        try:
            report = prepared.session.run(read)
        except Exception:  # a diagnostic must never fail the action it describes
            return {"thread_active_window": None, "thread_focus": None,
                    "target_window_active": None}
        if not report["target_window_active"]:
            report["note"] = FOCUS_NOTE
        return report

    def _delivery(self, prepared, point) -> dict:
        """Which window a posted click reaches: the innermost one under the
        point, which is the located window itself only when nothing of its
        own sits there. Said whenever it differs, so "delivered" names the
        control that got it and never a panel that dropped it (D66)."""
        from ..backends import current

        node = prepared.node
        winapi, deepest = current().winapi, current().deepest_child_at
        if isinstance(node, AccessibleElement):
            host = node.host_handle
            left, top, right, bottom = node.rect

            def read():
                p = ((left + right) // 2, (top + bottom) // 2) if point is None else (
                    left + point[0], top + point[1])
                cx, cy = winapi.screen_to_client(host, p)
                return deepest(host, cx, cy)
        else:
            host = node.handle

            def read():
                cx, cy = winapi.client_centre(host) if point is None else point
                return deepest(host, cx, cy)

        try:
            target, tx, ty = prepared.session.run(read)
        except Exception:
            return {}
        if target == host:
            # No child window under the point. On an owner-drawn grid that is
            # the normal, correct case (the rows are painted), so this is not
            # flagged here -- hit_targets is where a caller checks whether a
            # container has addressable children (D67).
            return {}
        return {"delivered_to": {
            "class": winapi.class_name(target), "handle_ephemeral": f"0x{target:08X}",
            "at": {"x": tx, "y": ty},
            "note": "the innermost window under the point; a click posted to "
                    "the located window itself would have been dropped there",
        }}

    def _renders_content(self, prepared) -> bool:
        """Whether the control has painted anything but its background."""
        from ..backends import current
        from .discovery import INK_THRESHOLD

        node = prepared.node
        handle = node.host_handle if isinstance(node, AccessibleElement) else node.handle
        region = node.rect if isinstance(node, AccessibleElement) else None
        try:
            ink = prepared.session.run(lambda: current().ink_fraction(handle, region=region))
        except Exception:
            return False
        return ink > INK_THRESHOLD

    def _to_logical(self, point):
        """A point read off a physical-pixel screenshot, in this tool's frame."""
        from ..backends import current

        scale = current().winapi.display_scale()
        return (round(point[0] / scale), round(point[1] / scale))

    def _outcome(self, result, session, locator: str) -> dict | None:
        """What a failed actuation *did*, when the result can tell.

        Two cases the flat sentence hid. A window appeared or the target
        became held: the action was delivered and the application answered
        it -- an Error dialog is the outcome, not a miss (#194). A route
        delivered and nothing at all changed: the control may act only on a
        route this did not take, and the second such delivery on the same
        control in one session is said to be the second, because that is
        what stops the third (#195). `ok` stays false either way: a named
        expectation that did not hold did not hold (D28).
        """
        from .guidance import NO_EFFECT_HINT

        if (result.error or {}).get("kind") != ErrorKind.POSTCONDITION_FAILED.value:
            return None
        appeared = [d.get("detail") for d in result.disturbances
                    if d.get("change") == "window_appeared"]
        held = [d.get("detail") for d in result.disturbances
                if d.get("change") == "blocked"]
        if appeared or held:
            raised = appeared or held
            return {
                "outcome": "delivered_raised_window",
                "fields": {"raised": raised},
                "lead": (f"delivered, and a window appeared ({', '.join(raised)}); the "
                         "named expectation did not hold. Read it with modals and "
                         "deal with it before retrying: it may be the application's "
                         "answer to this action."),
            }
        delivered = (len(result.declined) < len(result.routes_attempted)
                     if result.routes_attempted else result.tier_used is not None)
        if delivered and not result.disturbances:
            # Every failed actuation on this control this session, this one
            # included -- it was recorded before this report was built.
            count = sum(1 for o in self.sessions.ledger.outcomes(session.session_id)
                        if o.locator == locator and not o.ok)
            again = (f"This is delivery #{count} to this control with no effect in "
                     "this session; the same route will not act on a retry. "
                     if count >= 2 else "")
            return {
                "outcome": "delivered_no_effect",
                "fields": {"no_effect_count": max(count, 1)},
                "lead": again + NO_EFFECT_HINT,
            }
        return None

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
            "route": result.route_used,
            "tiers_attempted": result.tiers_attempted,
            "routes_attempted": result.routes_attempted,
            **({"declined": result.declined} if result.declined else {}),
            "cadence": prepared.cadence.name,
            "elapsed_ms": result.elapsed_ms,
            "disturbances": result.disturbances,
            **({"index_drift": prepared.drift} if getattr(prepared, "drift", None) else {}),
            **extra,
        }
        if result.error is not None:
            error = dict(result.error)
            outcome = self._outcome(result, prepared.session, locator)
            if outcome is not None:
                # The diagnosis used to sit one layer down, in disturbances
                # and focus, under a top line that read "try again" (#194,
                # #195). The top line now says what happened.
                reported["outcome"] = outcome["outcome"]
                reported.update(outcome.get("fields", {}))
                error["message"] = outcome["lead"] + " " + error["message"]
            elif result.disturbances:
                error["message"] += (
                    f"; {len(result.disturbances)} other change(s) happened "
                    "around this action -- see disturbances. " + SENSITIVE_HINT
                )
            reported["error"] = error
        if self._busy_after_action(prepared.session):
            # The action is done; the screen is not. On a target whose grids
            # fill seconds after the click, a result read now is wrong (D69).
            reported["still_arriving"] = True
            reported["settle_hint"] = (
                "the target shows its busy indicator: the effect of this action "
                "may still be arriving, and a grid or a block read now can be "
                "incomplete. wait_idle first, then read"
            )
        return reported
