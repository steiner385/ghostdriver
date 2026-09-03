"""Discovery and reading: describe, find, read, capture, wait_for."""

import base64

from ..model.element import AccessibleElement
from ..model.locator import Locator
from ..model.result import ErrorKind, GhostdriverError
from ..summarize import summarize
from ..wait import Condition, wait_for
from .core import (
    MAX_ELEMENTS,
    _element,
    _error,
    _ToolboxCore,
)


class DiscoveryTools(_ToolboxCore):
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
    ) -> dict:
        try:
            session = self.sessions.authorize(session_id, "describe")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)

        trees = self._trees(session, all_windows)
        if not trees:
            return _error(ErrorKind.NOT_FOUND,
                          f"pid {session.pid} has no windows on this desktop")

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
            windows.append({
                "class": tree.class_name,
                "text": tree.text,
                "visible": tree.visible,
                "role": "main" if index == 0 else "other",
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

        return {
            "ok": True,
            "blocked": self._blocking(session),
            "windows": windows,
            "suggested_locators": locators[:30],
            "nodes_shown": totals["nodes"],
            "truncated": truncated,
            "elided_by_collapsing": totals["elided"],
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

        result = {
            "ok": True,
            "locator": locator,
            "match_count": len(matches),
            "elements": [_element(n) for n in matches[:MAX_ELEMENTS]],
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
        self, session_id: str, locator: str, *, all_windows: bool = False
    ) -> dict:
        try:
            session = self.sessions.authorize(session_id, "read")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)

        from ..backends import current
        read_window_text = current().read_window_text

        try:
            matches = self._resolve(session, locator, all_windows)
        except ValueError as exc:
            return _error(ErrorKind.NOT_FOUND, str(exc), locator=locator)

        from ..backends import current
        is_protected = current().is_protected

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
            raw = read_window_text(node.handle)
            value = {
                "class": node.class_name,
                # None and "" are different answers: one is a control that
                # never replied, the other is a control that replied with
                # nothing. Collapsing them asserts a field is empty when it
                # may be full.
                "text": raw,
                "answered": raw is not None,
            }
            # A third answer, and it was previously reported as the first.
            # The system refuses a cross-process read of a password field,
            # so it comes back unanswered -- identical to a control that has
            # stopped pumping messages, and a caller told the wrong one goes
            # off diagnosing a hang that is not happening. Only asked when
            # the read came back empty-handed, so the ordinary path pays
            # nothing.
            if raw is None and is_protected(node.handle):
                value["protected"] = True
                value["reason"] = (
                    "this field hides its contents; the system does not "
                    "disclose them to another process, and this tool will "
                    "not type into it. If a person must fill it in, use "
                    "await_human"
                )
            values.append(value)
        return {
            "ok": True,
            "locator": locator,
            "match_count": len(matches),
            "values": values,
            "unanswered": sum(1 for v in values if not v["answered"]),
        }

    def capture(
        self,
        session_id: str,
        *,
        locator: str | None = None,
        region: dict | None = None,
    ) -> dict:
        """A PNG of the target's window, or of one region of it."""
        try:
            session = self.sessions.authorize(session_id, "capture")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)

        from ..backends import current
        CaptureError = current().CaptureError
        capture_window = current().capture_window

        trees = self._trees(session, all_windows=False)
        if not trees:
            return _error(ErrorKind.NOT_FOUND,
                          f"pid {session.pid} has no windows on this desktop")
        target, crop = trees[0], None

        if locator:
            try:
                matches = self._resolve(session, locator, True)
            except ValueError as exc:
                return _error(ErrorKind.NOT_FOUND, str(exc), locator=locator)
            if not matches:
                return _error(ErrorKind.NOT_FOUND,
                              f"nothing matched {locator!r}", locator=locator)
            if len(matches) > 1:
                return _error(
                    ErrorKind.AMBIGUOUS,
                    f"{len(matches)} elements matched {locator!r}; capture "
                    "needs exactly one. Add within= or index=.",
                    locator=locator,
                )
            crop = matches[0].rect
        elif region:
            crop = (region["left"], region["top"],
                    region["right"], region["bottom"])

        try:
            png, width, height = session.run(
                lambda: capture_window(target.handle, region=crop))
        except CaptureError as exc:
            return _error(ErrorKind.NOT_ACTIONABLE, str(exc))

        return {
            "ok": True,
            "width": width,
            "height": height,
            "mime_type": "image/png",
            "base64": base64.b64encode(png).decode("ascii"),
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

        result = wait_for(
            lambda: self._resolve(session, locator, all_windows),
            wanted,
            timeout_s=timeout_s,
        )
        payload = {
            "ok": result.ok,
            "locator": locator,
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
