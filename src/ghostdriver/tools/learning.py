"""Learning by probing: probe_phase2 and probe_grid."""

import time

from ..model.result import ErrorKind, GhostdriverError
from ..probe.profile import merge_learned
from .acting import _ActingCore
from .core import (
    _element,
    _error,
)
from .guidance import CLIPBOARD_NOT_ALLOWED


class LearningTools(_ActingCore):
    """Probing how a target's controls and grids actually behave, under an operator's list."""

    def probe_phase2(
        self,
        session_id: str,
        *,
        only: list[str] | None = None,
        settle_ms: int = 1500,
    ) -> dict:
        """Learn how this target\'s controls actuate, by actuating them.

        The one part of this server that acts without a task asking it to,
        so every rail the spec names is enforced here rather than trusted to
        the caller.

        **It never chooses its own targets.** The controls come from
        `safe_controls` in the profile document, which an operator wrote.
        `only` may narrow that list; nothing can widen it. A locator that is
        not in the file is refused even if it is passed explicitly, which is
        the difference between a list and a suggestion.

        **The denylist still applies.** A caption in both lists is a
        contradiction in the operator\'s own policy, and the refusal says so
        rather than picking one.

        **Nothing is learned from a control that was refused.** Ambiguous
        locators, denylisted captions, a held application: all reported, none
        recorded.

        Requires the `full` tier, which nothing grants by default.
        """
        try:
            session = self.sessions.authorize(session_id, "probe_phase2")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)

        from ..probe.phase2 import SafeControl, learn

        try:
            listed = [SafeControl.from_dict(raw)
                      for raw in session.profile.safe_controls]
        except ValueError as exc:
            return _error(ErrorKind.DENIED_BY_POLICY,
                          f"the safe-control list is unusable: {exc}")
        if not listed:
            return _error(
                ErrorKind.NOT_ACTIONABLE,
                "this target has no safe_controls in its profile document. "
                "Phase 2 actuates controls, and it will only actuate ones an "
                "operator has listed -- there is nothing here to run",
            )

        if only is not None:
            wanted = set(only)
            unknown = sorted(wanted - {c.locator for c in listed})
            if unknown:
                return _error(
                    ErrorKind.DENIED_BY_POLICY,
                    f"{unknown} are not in this target\'s safe-control list. "
                    "`only` narrows what is listed; it cannot add to it",
                )
            listed = [c for c in listed if c.locator in wanted]

        report = learn(listed, lambda c: self._probe_one(session, c, settle_ms))
        report["ok"] = True
        report["profile"] = str(session.profile.path or "")

        # Written back only when there is a path to write to, and only the
        # two fields this learned. Everything else in the document is left
        # exactly as it was.
        if session.profile.path and report["actuation_map"]:
            try:
                merged = merge_learned(
                    session.profile.path,
                    actuation_map=report["actuation_map"],
                    focus_behavior=report["focus_behavior"],
                )
                report["written"] = merged
            except (OSError, ValueError) as exc:
                report["written"] = False
                report["write_error"] = str(exc)
        else:
            report["written"] = False
        return report

    def _probe_one(self, session, control, settle_ms: int):
        """Actuate one listed control and report what it taught.

        Deliberately not reusing `click`: this needs the tier the ladder
        reached and the disturbances around it, and it must refuse rather
        than fall back on anything the tool surface would forgive.
        """
        from ..backends import current
        verbs = current().verbs
        from ..backends import current
        snapshot = current().snapshot
        from ..probe.phase2 import ControlOutcome

        def refused(reason: str, class_name: str = "") -> ControlOutcome:
            return ControlOutcome(locator=control.locator,
                                  class_name=class_name, refused=reason,
                                  expect_source=control.expect_source)

        try:
            matches = self._resolve(session, control.locator, True)
        except ValueError as exc:
            return refused(f"locator is unusable: {exc}")
        if not matches:
            return refused("nothing matches this locator now")
        if len(matches) > 1:
            return refused(f"{len(matches)} elements match; phase 2 will not "
                           "guess which one an operator meant")

        node = matches[0]
        try:
            self.sessions.check_caption(session.session_id, node.text)
        except GhostdriverError as exc:
            return refused(
                f"listed as safe but also denied: {exc.message}. That is a "
                "contradiction in this profile\'s own policy, and it is not "
                "for this tool to pick a side",
                node.class_name,
            )

        expectation, _ = self._expectation(session, control.expect)
        if expectation is None:
            return refused("its expect could not be built", node.class_name)

        # Marshalled through the session like every other actuation, so
        # this learns correctly even on a hidden-desktop target.
        before_foreground = session.run(
            lambda: snapshot(session.pid)).foreground
        started = time.monotonic()
        result = self._perform(
            session,
            verbs.click(node.handle),
            expect_before=verbs.unblocked(node.handle),
            expect_after=expectation,
        )
        if result.precondition_verified is False:
            return refused("the application was held by a dialog",
                           node.class_name)

        # The application may take the foreground on a delay, which is the
        # whole reason focus_behavior is worth learning -- so this waits
        # past the action rather than sampling once and moving on.
        taken, delay = self._watch_foreground(
            session, before_foreground, started, settle_ms
        )
        # Every tier sent its message and none satisfied the expectation.
        # The control was acted on -- that has to be reported even though it
        # taught the map nothing, and with a drafted expectation it is the
        # likeliest outcome of all.
        delivered = (
            result.error is not None
            and result.error.get("kind") == ErrorKind.POSTCONDITION_FAILED.value
        )
        return ControlOutcome(
            locator=control.locator,
            class_name=node.class_name,
            tiers_attempted=result.tiers_attempted,
            tier_used=result.tier_used,
            verified=bool(result.postcondition_verified),
            delivered=delivered,
            foreground_taken=taken,
            foreground_delay_ms=delay,
            expect_source=control.expect_source,
            observed=result.disturbances,
        )

    def _watch_foreground(self, session, before: int, started: float,
                          settle_ms: int):
        """Whether the target came to the front, and how long after acting.

        Sampled rather than checked once. Measured on a real target, the
        grab arrives hundreds of milliseconds after the click -- long enough
        that a single check straight afterwards would report a target that
        does disturb the desktop as one that does not.
        """
        from ..backends import current
        snapshot = current().snapshot

        deadline = started + (settle_ms / 1000.0)
        while time.monotonic() < deadline:
            state = session.run(lambda: snapshot(session.pid))
            if state.foreground != before and state.foreground in state.windows:
                return True, int((time.monotonic() - started) * 1000)
            time.sleep(0.05)
        return False, None

    def probe_grid(
        self,
        session_id: str,
        locator: str,
        *,
        allow_clipboard: bool = True,
        all_windows: bool = False,
    ) -> dict:
        """Find how exact text comes out of an owner-drawn region.

        `read` returns nothing for a grid that paints itself, and a capture
        is pixels a caller can look at but not verify against (D46). What a
        caller needs is a route to the text, and the spec says those are
        probed before anything is built on OCR. This tries them cheapest
        first: a focus-revealed accessibility surface, which costs nothing
        shared, and only if that fails the control\'s own copy, which
        touches the session-wide clipboard and says so.

        Same rails as phase 2. Full tier, because the clipboard route sends
        a message and reads a shared resource; the region is named by the
        caller, exactly one match; a denylisted caption or a held
        application refuses. And a region that already answers `read` is
        refused too -- it is not a grid, and the tool would be spending a
        side effect on something a free call already reads.
        """
        try:
            session = self.sessions.authorize(session_id, "probe_grid")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)

        node, failure = self._one(session, locator, all_windows)
        if failure is not None:
            return failure
        try:
            self.sessions.check_caption(session_id, node.text)
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message, locator=locator)

        from ..backends import current
        blocking_ancestor = current().blocking_ancestor

        if session.run(lambda: blocking_ancestor(node.handle)) is not None:
            return _error(ErrorKind.NOT_ACTIONABLE,
                          "the application is held by a dialog; deal with it "
                          "before probing anything")
        if node.text:
            return _error(
                ErrorKind.NOT_ACTIONABLE,
                f"{locator!r} already answers with text ({node.text[:40]!r}); "
                "it is not a painted region. Use `read`",
            )

        from ..backends import current
        copy_route = current().copy_route
        focus_route = current().focus_route
        from ..gridstrategy import GridProbe, find_grid_strategy

        # Routed through the session: the focus re-scan and the clipboard
        # copy both have to run where the target's windows are.
        may_copy = allow_clipboard and session.clipboard
        finding = find_grid_strategy(GridProbe(
            accessible_on_focus=lambda: session.run(lambda: focus_route(node)),
            clipboard_copy=(
                (lambda: session.run(lambda: copy_route(node)))
                if may_copy else None
            ),
        ))
        report = {"ok": True, "locator": locator, "element": _element(node),
                  **finding.to_dict()}
        if allow_clipboard and not session.clipboard:
            report["clipboard"] = CLIPBOARD_NOT_ALLOWED
        if finding.strategy.value == "unknown":
            report["meaning"] = _unknown_meaning(len(finding.attempts), allow_clipboard)

        if session.profile.path and finding.strategy.value != "unknown":
            try:
                merge_learned(
                    session.profile.path,
                    grid_strategy=finding.strategy.value,
                    grid_evidence=finding.to_dict(),
                )
                report["written"] = True
            except (OSError, ValueError) as exc:
                report["written"] = False
                report["write_error"] = str(exc)
        else:
            report["written"] = False
        return report


def _unknown_meaning(routes_tried: int, allow_clipboard: bool) -> str:
    """Said with an UNKNOWN finding, so it is read as the answer it is.

    A session that got UNKNOWN on two grids, both routes, zero lines,
    wondered whether the probe had failed. It had not: the grid exposes
    nothing, and the report should say so rather than leave the next
    session to re-run it (D64).
    """
    untried = ("" if allow_clipboard else
               "; the clipboard route was not tried (allow_clipboard=false)")
    return (
        f"{routes_tried} route(s) ran and none produced structured text{untried}. "
        "This is a real outcome, not a failure of the probe: the grid exposes "
        "nothing readable through the accessibility tree or the clipboard, and "
        "repeating it will not change that. What remains for this grid is "
        "pixels -- capture to see the rows, click at={x, y} to act on one -- "
        "the caret keys through send_keys, and a person, through await_human, "
        "for reading a value."
    )
