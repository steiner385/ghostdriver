"""Discovery and reading: describe, find, read, capture, wait_for."""

import base64

from ..backends import current
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
    _top_level_holding,
    _top_level_overlapping,
)
from .guidance import BLOCKED_HINT, HUNG_HINT

#: Above this fraction of non-background pixels a control has painted
#: something, whatever it says when asked for its text.
INK_THRESHOLD = 0.02


#: The longest one wait_for call will wait. A screen that takes forty
#: seconds to fill is one sixty-second wait, not four ten-second ones.
MAX_WAIT_S = 300.0


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
            "frame": "screen",
            **self._frame_note(),
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

        read_window_text = current().read_window_text

        try:
            matches = self._resolve(session, locator, all_windows)
        except ValueError as exc:
            return _error(ErrorKind.NOT_FOUND, str(exc), locator=locator)

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
            if raw == "" and node.visible:
                # Empty answer, painted content: the read path does not work
                # on this control, and saying "empty" would be wrong (D66).
                try:
                    ink = session.run(lambda h=node.handle: current().ink_fraction(h))
                except Exception:
                    ink = 0.0
                if ink > INK_THRESHOLD:
                    value["read_unreliable"] = True
                    value["rendered_ink"] = ink
                    value["note"] = (
                        "answers empty to a text query but renders content; the "
                        "read path is unreliable on this control. Verify by "
                        "capture, or through the value's effect elsewhere"
                    )
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
        save_as: str | None = None,
        frame: str = "logical",
    ) -> dict:
        """A PNG of the target's window, or of one region of it."""
        try:
            session = self.sessions.authorize(session_id, "capture")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)
        if frame == "physical" and region is not None:
            scale = current().winapi.display_scale()
            region = {k: round(v / scale) for k, v in region.items()}

        CaptureError = current().CaptureError
        capture_window = current().capture_window

        # Every top-level window of the target and its tree, because the
        # window to *render* is the one that holds the match -- a modal is
        # its own top-level window, and rendering the main window cropped
        # to the modal's rectangle gives the pixels underneath the modal,
        # confidently and wrongly. Measured in the field before this.
        trees = self._trees(session, all_windows=True)
        if not trees:
            return _error(ErrorKind.NOT_FOUND,
                          f"pid {session.pid} has no windows on this desktop")
        main = self._trees(session, all_windows=False)
        target, crop = (main[0] if main else trees[0]), None

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
            match = matches[0]
            holder = _top_level_holding(trees, match.handle)
            if holder is None:
                return _error(ErrorKind.NOT_FOUND,
                              f"{locator!r} matched a window no top-level window holds")
            # A region alongside a locator crops within the located window,
            # rather than being silently dropped (D67). Screen coordinates,
            # like every region, so a rect from find() is used as-is.
            if region:
                target, crop = holder, (region["left"], region["top"],
                                        region["right"], region["bottom"])
            else:
                target, crop = holder, match.rect
        elif region:
            crop = (region["left"], region["top"],
                    region["right"], region["bottom"])
            # The window the region lies in, by overlap: a region a caller
            # copied from find() is in screen coordinates, and only the
            # window it overlaps most can render it.
            holder = _top_level_overlapping(trees, crop)
            if holder is None:
                return _error(
                    ErrorKind.NOT_FOUND,
                    f"region {crop} (screen coordinates) overlaps no window of "
                    "the target; rects from find() and describe() are in screen "
                    "coordinates, so pass one of those")
            target = holder

        try:
            png, width, height = session.run(
                lambda: capture_window(target.handle, region=crop))
        except CaptureError as exc:
            return _error(ErrorKind.NOT_ACTIONABLE, str(exc))

        left, top, right, bottom = target.rect
        result = {
            "ok": True,
            "width": width,
            "height": height,
            "mime_type": "image/png",
            # The frame every rectangle in this tool uses, said so a region
            # copied out of one result is known to be valid in another.
            "frame": "screen",
            "rendered": {
                "class": target.class_name,
                "text": target.text,
                "pid": target.pid,
                "handle_ephemeral": f"0x{target.handle:08X}",
                "rect": {"left": left, "top": top, "right": right, "bottom": bottom},
            },
            "base64": base64.b64encode(png).decode("ascii"),
        }
        if crop is not None:
            inside = (max(crop[0], left), max(crop[1], top),
                      min(crop[2], right), min(crop[3], bottom))
            if inside != tuple(crop):
                result["clipped_to_window"] = True
        result.update(self._frame_note())
        if save_as is not None:
            from ..operator import save_capture

            try:
                result["saved_to"] = str(save_capture(save_as, png))
            except (OSError, ValueError) as exc:
                result["saved_to"] = None
                result["save_error"] = str(exc)
        return result

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
