"""Operator-in-the-loop tools: record_input_sensitivity, await_human."""

import time
from dataclasses import replace

from ..model.locator import Locator
from ..model.result import ErrorKind, GhostdriverError
from .core import (
    _error,
    _ToolboxCore,
)


class HumanTools(_ToolboxCore):
    """The operator in the loop: recording what they know, and waiting for what only they can do."""

    def record_input_sensitivity(
        self,
        session_id: str,
        *,
        locator: str | None = None,
        note: str = "",
    ) -> dict:
        """Record that this target rejects machine-speed input.

        Written only when this server saw the differential itself: the same
        action, on the same element, failing at robot cadence and succeeding
        at a human one. A caller cannot assert it -- the party asking for a
        note recorded is the party that most wants it recorded, and an
        assertion about its own history is indistinguishable from a guess.

        Where there is no evidence, the refusal says which half is missing,
        because the caller believes it saw something and needs to know what
        the server does not have.

        The note goes into the profile document the operator supplied at
        attach. Without one there is nowhere durable to put it, so the note
        is returned instead, for a person to place -- writing a file nobody
        pointed at would be a side effect nobody asked for.
        """
        try:
            session = self.sessions.authorize(
                session_id, "record_input_sensitivity"
            )
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)

        from ..sensitivity import learned_from_differential, merge_into_document

        found = self.sessions.ledger.differential(session_id, locator)
        if found is None:
            return _error(
                ErrorKind.NOT_ACTIONABLE,
                "nothing recorded here shows machine-speed input being "
                "refused: " + self.sessions.ledger.why_not(session_id, locator),
            )

        learned = learned_from_differential(found.surface, found.describe())
        if note:
            learned = replace(learned, evidence=f"{learned.evidence}; {note}")

        if session.profile.path is None:
            return {
                "ok": True,
                "written": False,
                "note": learned.to_dict(),
                "reason": (
                    "this session was attached without a profile document, "
                    "so there is nowhere durable to record it. Give this note "
                    "to the operator, or re-attach with profile_path set"
                ),
            }

        try:
            outcome = merge_into_document(session.profile.path, learned)
        except (OSError, ValueError) as exc:
            return _error(
                ErrorKind.DENIED_BY_POLICY,
                f"could not update {session.profile.path}: {exc}",
            )
        return {"ok": True, **outcome}

    def _notice(self, ask: str):
        """The on-screen notice, or None where the platform cannot show one.
        A notice that cannot be shown must not stop the wait."""
        try:
            from ..backends import current

            shown = current().OperatorNotice(ask)
            shown.show()
            return shown
        except Exception:
            return None

    def await_human(
        self,
        session_id: str,
        ask: str,
        *,
        until: dict | None = None,
        timeout_s: float = 120.0,
        poll_s: float = 0.5,
        all_windows: bool = False,
        confirmed: bool = False,
        notice: bool = True,
    ) -> dict:
        """Hand a step to the person, and wait for the target to show it done.

        **The ask is put where the person is looking.** In a chat client the
        ask can end up folded inside a tool call they have to expand to
        read, and while this waits nobody is told anything. So, unless
        `notice` is off, it is also shown on their screen for the length of
        the wait: a small always-on-top window in the corner that never
        takes focus and closes when the wait ends. The agent should still
        say it in chat first -- the notice is where the ask is *kept*, the
        chat is where it is *noticed*.

        Some steps are not the driver\'s to take. A password is the clearest
        case -- it would have to pass through this process to be typed, and
        no amount of care makes that worth the convenience -- but the same
        is true of anything an operator has said they want to do themselves,
        and of a decision that needs a person\'s judgement rather than a
        locator.

        What this adds over the agent simply asking in chat is *evidence*.
        A reply saying "done" is a claim; `until` is a condition checked
        against the target itself, so the agent resumes on something
        observed rather than something asserted. Both together are better
        still: the person confirms, and the application agrees.

        Without `until` this returns immediately, having asked and verified
        nothing -- said plainly in the result, because "I asked" and "it
        happened" are as different here as everywhere else in this tool.

        Bounded, and reports a timeout as a timeout. A person may be away
        from the machine, and a tool that waited indefinitely would take the
        session with them.

        **It never carries the value.** There is no parameter for a
        credential and no way to supply one, in either direction. The point
        is that the secret goes from the person into the application without
        passing through here.
        """
        try:
            session = self.sessions.authorize(session_id, "await_human")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)

        asked = (ask or "").strip()
        if not asked:
            return _error(
                ErrorKind.NOT_ACTIONABLE,
                "say what the person needs to do; this is relayed to them "
                "as written, so an empty ask reaches them as an empty ask",
            )

        if until is None:
            return {
                "ok": True,
                "asked": asked,
                "confirmed_by_operator": confirmed,
                "waited_ms": 0,
                "verified": False,
                "note": (
                    "nothing was checked against the target, because no "
                    "`until` was given. Pass one naming what will be true "
                    "once the person has done it, and this waits for the "
                    "application to show it rather than taking anyone\'s word"
                ),
            }

        where = until.get("locator")
        if not where:
            return _error(ErrorKind.NOT_ACTIONABLE,
                          "`until` needs a locator naming what to wait for")
        try:
            Locator.parse(where)
        except ValueError as exc:
            return _error(ErrorKind.NOT_FOUND, f"until is unusable: {exc}")

        from ..backends import current
        read_window_text = current().read_window_text

        wanted = until.get("text")
        # "gone" is as common a signal as "there": a sign-in dialog closing
        # is how you know someone signed in.
        absent = bool(until.get("absent", False))

        def satisfied() -> bool:
            found = self._resolve(session, where, all_windows)
            if absent:
                return not found
            if not found:
                return False
            if wanted is None:
                return True
            return any((read_window_text(n.handle) or "") == wanted
                       for n in found)

        started = time.monotonic()
        deadline = started + max(0.0, timeout_s)
        met = False
        shown = self._notice(asked) if notice else None
        try:
            while True:
                try:
                    met = satisfied()
                except GhostdriverError:
                    # The target went away while we waited, which is an answer.
                    met = False
                    break
                if met:
                    break
                now = time.monotonic()
                if now >= deadline:
                    break
                time.sleep(min(poll_s, deadline - now))
        finally:
            if shown is not None:
                shown.close()

        waited_ms = int((time.monotonic() - started) * 1000)
        described = (
            f"{where} is gone" if absent
            else f"{where} exists" if wanted is None
            else f"{where} reads {wanted!r}"
        )
        if met:
            return {
                "ok": True,
                "asked": asked,
                "confirmed_by_operator": confirmed,
                "waited_ms": waited_ms,
                "verified": True,
                "expected": described,
            }
        return {
            "ok": False,
            "asked": asked,
            "confirmed_by_operator": confirmed,
            "waited_ms": waited_ms,
            "verified": False,
            "expected": described,
            "error": {
                "kind": ErrorKind.TIMEOUT.value,
                "message": (
                    f"waited {waited_ms}ms and {described} is still not so. "
                    "The person may not have finished, or may not have seen "
                    "the request -- ask them before retrying, and do not "
                    "attempt the step yourself if it was handed over for a "
                    "reason"
                ),
            },
        }
