"""Discovery and reading: describe, find, read, capture, wait_for."""

from .. import disclosure as disclosure_report
from ..backends import current
from ..model.element import AccessibleElement
from ..model.locator import Locator
from ..model.result import ErrorKind, GhostdriverError
from ..summarize import summarize
from ..wait import Condition, wait_for
from .core import MAX_ELEMENTS, _element, _error
from .guidance import BLOCKED_HINT, HUNG_HINT
from .visibility import _VisibilityCore

#: Above this fraction of non-background pixels a control has painted
#: something, whatever it says when asked for its text.
#: Re-exported from the reporting policy, which owns it now.
#: `tools/acting.py` imports it from here.
INK_THRESHOLD = disclosure_report.INK_THRESHOLD


#: The longest one wait_for call will wait. A screen that takes forty
#: seconds to fill is one sixty-second wait, not four ten-second ones.
MAX_WAIT_S = 300.0


#: How many suggested locators one describe carries; the rest are counted.
MAX_SUGGESTED = 30


class DiscoveryTools(_VisibilityCore):
    """Seeing the target: its tree, single elements, text, pixels, and waiting on it."""

    def describe(
        self,
        session_id: str,
        *,
        depth: int = 5,
        max_nodes: int = 200,
        all_windows: bool = False,
        include_hidden: bool = False,
        collapse_threshold: int = 3,
        within: str | None = None,
    ) -> dict:
        try:
            session = self.sessions.authorize(session_id, "describe")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)

        trees = self._trees(session, all_windows)
        if not trees:
            return _error(ErrorKind.NOT_FOUND,
                          f"pid {session.pid} has no windows on this desktop")
        if within:
            # Root the summary at one window (#210). At scale the first
            # describe collapses same-class siblings and hides everything
            # under them -- 1,093 of 1,102 nodes, measured -- which is the
            # right first answer and a dead end without a way back in.
            try:
                matches = self._resolve(session, within, all_windows)
            except ValueError as exc:
                return _error(ErrorKind.NOT_FOUND, str(exc), locator=within)
            matches = [m for m in matches if not isinstance(m, AccessibleElement)]
            if len(matches) != 1:
                return _error(
                    ErrorKind.NOT_FOUND if not matches else ErrorKind.AMBIGUOUS,
                    f"within must name exactly one window; {within!r} matched "
                    f"{len(matches)}. Use one of an earlier describe's "
                    "suggested_locators, or add index=", locator=within)
            trees = [matches[0]]

        windows, locators = [], []
        remaining, omitted, skipped = max_nodes, 0, 0
        truncated = False
        totals = {"nodes": 0, "elided": 0, "below_depth": 0}

        for index, tree in enumerate(trees):
            if all_windows and not include_hidden and not tree.visible:
                skipped += 1
                continue
            if remaining <= 0:
                omitted += 1
                continue
            summary = summarize(
                tree, max_depth=depth, visible_only=not include_hidden,
                max_nodes=remaining, collapse_threshold=collapse_threshold,
            )
            if not summary.node_count:
                continue
            hung = session.run(lambda h=tree.handle: current().winapi.is_hung(h))
            windows.append({
                "class": tree.class_name,
                "text": tree.text,
                "visible": tree.visible,
                "role": "main" if index == 0 else "other",
                "pid": tree.pid,
                **({"hung": True, "hint": HUNG_HINT} if hung else {}),
                "tree": summary.text,
            })
            remaining -= summary.node_count
            totals["nodes"] += summary.node_count
            totals["elided"] += summary.elided_nodes
            totals["below_depth"] += summary.depth_elided_nodes
            truncated = truncated or summary.truncated
            for locator in summary.suggested_locators:
                if locator not in locators:
                    locators.append(locator)

        blocked = self._blocking(session)
        return {
            "ok": True,
            "blocked": blocked,
            **({"blocked_hint": BLOCKED_HINT} if blocked else {}),
            **({"within": within} if within else {}),
            "windows": windows,
            "suggested_locators": locators[:MAX_SUGGESTED],
            # A cap that says nothing reads as "that was all of them" (D11).
            **({"suggested_locators_omitted": len(locators) - MAX_SUGGESTED}
               if len(locators) > MAX_SUGGESTED else {}),
            "nodes_shown": totals["nodes"],
            "truncated": truncated,
            "elided_by_collapsing": totals["elided"],
            **({"expand_hint": (
                "a collapsed group ([N x Class ...]) hides everything under its "
                "members. To see inside one, describe again with within=<its "
                "locator> -- the captioned ones are in suggested_locators; an "
                "uncaptioned one is class=<Class> index=<n>.")}
               if totals["elided"] else {}),
            "below_depth": totals["below_depth"],
            "windows_omitted_for_budget": omitted,
            "windows_hidden": skipped,
            "searched": "every top-level window" if all_windows
                        else "the main window only",
        }

    def find(
        self, session_id: str, locator: str, *, all_windows: bool = False
    ) -> dict:
        try:
            session = self.sessions.authorize(session_id, "find")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)

        try:
            matches = self._resolve(session, locator, all_windows)
        except ValueError as exc:
            return _error(ErrorKind.NOT_FOUND, str(exc), locator=locator)

        vis_cache: dict = {}
        elements = []
        for node in matches[:MAX_ELEMENTS]:
            described = _element(node)
            # Only when obscured, and only then: a visible window says nothing,
            # the way `actionable` is emitted only when False (#61).
            obscured = self._obscured(session, node, vis_cache)
            if obscured is not None:
                described["obscured"] = obscured
            note = session.profile.note_for(getattr(node, "class_name", None))
            if note:
                described["note"] = note
            elements.append(described)
        drift = self._drift_note(session, locator)
        result = {
            "ok": True,
            "locator": locator,
            "match_count": len(matches),
            **({"index_drift": drift} if drift else {}),
            "frame": "screen",
            **self._frame_note(),
            "elements": elements,
            "searched": "every top-level window" if all_windows
                        else "the main window only",
        }
        if len(matches) > MAX_ELEMENTS:
            result["truncated"] = (
                f"{len(matches)} matched; {MAX_ELEMENTS} returned. Narrow the "
                "locator with class=, within= or index=."
            )
        if not matches and not all_windows:
            result["hint"] = (
                "only the main window was searched. Menus, dropdowns, lookup "
                "lists and modal dialogs are separate top-level windows; "
                "retry with all_windows=true."
            )
        return result

    def read(
        self, session_id: str, locator: str, *, all_windows: bool = False,
        disclose: bool = False,
    ) -> dict:
        """Read what a locator matches.

        `disclose` asks for the contents of a field the driver would
        otherwise decline to look at. It exists because one platform cannot
        tell a hidden entry from a plain one by inspection, so it withholds
        both by class (D#34b) -- and without a way to ask, a caller with a
        legitimate need for a plain text field's value has none.

        It never overrides `protected`: a field the toolkit *declares* a
        password is not disclosed at any grain, because that one is not a
        guess.

        **The asking is what is recorded, never the answer** (D62), and it
        needs no code here to be so. The tracer records every tool's `args`
        and, of the result, only `ok` and any error -- so `disclose=true`
        lands in the trace as the request it was, while the values it
        returned do not. An operator reading a session back can see that a
        value was exposed and which locator exposed it, without the value
        being written down.
        """
        try:
            session = self.sessions.authorize(session_id, "read")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)

        read_window_text = current().read_window_text

        try:
            matches = self._resolve(session, locator, all_windows)
        except ValueError as exc:
            return _error(ErrorKind.NOT_FOUND, str(exc), locator=locator)

        is_protected = current().is_protected
        disclosure = current().disclosure

        values = []
        for node in matches[:MAX_ELEMENTS]:
            if isinstance(node, AccessibleElement):
                # An element answers with its name, or its value when it
                # publishes one; the surface always answers, so there is no
                # unanswered case here.
                values.append({
                    "type": node.control_type,
                    "text": node.value if node.value is not None else node.name,
                    "answered": True,
                    **({"selected": node.selected} if node.selected is not None else {}),
                })
                continue
            raw = read_window_text(node.handle, disclose=disclose)
            value = disclosure_report.describe(node.class_name, raw)
            if raw == "" and node.visible:
                try:
                    ink = session.run(lambda h=node.handle: current().ink_fraction(h))
                except Exception:
                    ink = 0.0
                disclosure_report.note_unreliable(value, ink)
            # Why a read came back empty-handed, asked only when it did --
            # so the ordinary path pays nothing, and neither call reads the
            # value itself.
            if raw is None:
                disclosure_report.explain_empty_handed(
                    value,
                    protected=is_protected(node.handle),
                    verdict=disclosure(node.handle),
                )
            values.append(value)
        return {
            "ok": True,
            "locator": locator,
            "match_count": len(matches),
            "values": values,
            "unanswered": sum(1 for v in values if not v["answered"]),
        }

    def wait_for(
        self,
        session_id: str,
        locator: str,
        *,
        condition: str = "present",
        timeout_s: float = 10.0,
        all_windows: bool = False,
    ) -> dict:
        try:
            session = self.sessions.authorize(session_id, "wait_for")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)
        try:
            wanted = Condition(condition)
        except ValueError:
            return _error(
                ErrorKind.NOT_ACTIONABLE,
                f"unknown condition {condition!r}; expected one of "
                f"{[c.value for c in Condition]}",
            )
        try:
            Locator.parse(locator)
        except ValueError as exc:
            return _error(ErrorKind.NOT_FOUND, str(exc), locator=locator)

        timeout_s = min(float(timeout_s), MAX_WAIT_S)
        result = wait_for(
            lambda: self._resolve(session, locator, all_windows),
            wanted,
            timeout_s=timeout_s,
        )
        payload = {
            "ok": result.ok,
            "locator": locator,
            "timeout_s": timeout_s,
            "condition": result.condition.value,
            "polls": result.polls,
            "elapsed_ms": result.elapsed_ms,
            "match_count": len(result.matches),
            "reason": result.reason,
        }
        if not result.ok:
            payload["error"] = {
                "kind": ErrorKind.TIMEOUT.value, "message": result.reason,
            }
        return payload
