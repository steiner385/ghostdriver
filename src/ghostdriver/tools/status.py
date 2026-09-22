"""Target status: probe, surfaces, modals, restore."""


from ..model.element import AccessibleElement
from ..model.result import ErrorKind, GhostdriverError
from .core import (
    MAX_ELEMENTS,
    _element,
    _error,
    _ToolboxCore,
)
from .dialogtext import _dialog_text  # noqa: F401  (its old home; tests import it here)
from .guidance import BLOCKED_HINT, HUNG_HINT, PIXELS_HINT


class StatusTools(_ToolboxCore):
    """The target's state at a glance -- profile, surfaces, modals -- and putting its windows back."""

    def read_clipboard(self, session_id: str) -> dict:
        """The text on the clipboard, for the result of a target's own Copy.

        "Copy row values" is the single most useful read some grids have,
        and this tool could trigger it and not read it (D65). The clipboard
        is the person's as much as the target's, so this is interactive
        tier, reads text only, and says to read straight after the copy.
        """
        try:
            session = self.sessions.authorize(session_id, "read_clipboard")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)
        from ..backends import current

        text = session.run(lambda: current().read_clipboard_text())
        return {
            "ok": True,
            "text": text,
            "length": len(text or ""),
            "empty": not text,
            "caution": (
                "the clipboard is shared with the person: what is here may be "
                "theirs, and the target's next copy replaces it. Read it right "
                "after the copy you triggered, and do not keep it"
            ),
        }

    def probe(self, session_id: str) -> dict:
        try:
            session = self.sessions.authorize(session_id, "probe")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)

        from ..probe.runner import run_phase1

        try:
            document = session.run(lambda: run_phase1(session.pid))
        except (RuntimeError, OSError, AttributeError) as exc:
            return _error(ErrorKind.NOT_ACTIONABLE, str(exc))
        return {"ok": True, "profile": document.to_dict()}

    def surfaces(
        self,
        session_id: str,
        *,
        all_windows: bool = False,
        include_hidden: bool = False,
        changed_from: str | None = None,
    ) -> dict:
        try:
            session = self.sessions.authorize(session_id, "surfaces")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)

        from ..backends import current
        region_evidence = current().region_evidence
        from ..surface import (
            map_digest,
            needs_other_mechanism,
            summarize_access,
            summarize_kinds,
            surface_map,
        )

        trees = self._trees(session, all_windows)
        if not trees:
            return _error(ErrorKind.NOT_FOUND,
                          f"pid {session.pid} has no windows on this desktop")

        regions = [
            r
            for tree in trees
            for r in surface_map(tree, region_evidence,
                                 visible_only=not include_hidden)
        ]
        digest = map_digest(regions)
        # On `access`, not on `kind`. A live embedded document is not native
        # and does not need another mechanism -- the accessibility surface
        # already reaches it, and listing it here sent a caller off to build
        # a browser protocol for a region within reach.
        other = needs_other_mechanism(regions)
        return {
            "ok": True,
            "blocked": self._blocking(session),
            "blocked_hint": BLOCKED_HINT,
            "kinds": summarize_kinds(regions),
            # What is readable right now, and how. Separate from `kinds`
            # because it moves while the application runs and `kinds` does
            # not: an engine waking changes this and not that.
            "access": summarize_access(regions),
            "shape_digest": digest,
            "changed": (changed_from is not None and changed_from != digest),
            "regions_needing_another_mechanism": [
                {
                    "kind": r.kind.value,
                    "access": r.access.value,
                    "class": r.class_name,
                    "rect": {"left": r.rect[0], "top": r.rect[1],
                             "right": r.rect[2], "bottom": r.rect[3]},
                    "area_px": r.area,
                    "reason": r.reason,
                    "hint": PIXELS_HINT if r.access.value == "pixels" else (
                        "read it through element locators (type=..., name=...)"
                        if r.access.value == "accessibility" else ""),
                }
                for r in sorted(other, key=lambda r: -r.area)[:MAX_ELEMENTS]
            ],
        }

    def modals(self, session_id: str, *, full_text: bool = False) -> dict:
        try:
            session = self.sessions.authorize(session_id, "modals")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)
        from .dialogtext import DIALOG_CONTROL_CHARS, dialog_controls, join_dialog_text
        per_control = None if full_text else DIALOG_CONTROL_CHARS

        from ..backends import current
        top_level_state = current().top_level_state
        from ..modality import find_modal_blocks

        state = session.run(lambda: top_level_state(session.pid))
        blocks, unexplained = find_modal_blocks(state)
        hung = [t for t in state if t.hung]
        controls = {b.dialog.handle: session.run(
            lambda b=b: dialog_controls(b.dialog.handle, per_control=per_control))
            for b in blocks}
        return {
            "ok": True,
            "blocked": bool(blocks or unexplained),
            "top_level_windows": len(state),
            **({"hung_windows": [{"window": t.text or t.class_name, "class": t.class_name}
                                 for t in hung],
                "hint": HUNG_HINT} if hung else {}),
            "dialogs": [
                {
                    "dialog": b.dialog.text or b.dialog.class_name,
                    "dialog_class": b.dialog.class_name,
                    "holds": b.blocked.text or b.blocked.class_name,
                    "description": b.describe(),
                    # Every text control in the dialog, read whole -- a
                    # scrollable pane shows only part of its buffer, and the
                    # part that matters is often below the fold (D73) -- but
                    # each control capped by default, so a memo holding a
                    # stack trace does not cost the message beside it (#196).
                    "text": join_dialog_text(controls[b.dialog.handle]) or None,
                    "controls": controls[b.dialog.handle],
                    **({"truncated_chars": cut,
                        "note": "long controls were cut to their first "
                                f"{DIALOG_CONTROL_CHARS} characters; full_text=true "
                                "returns everything"}
                       if (cut := sum(c.get("cut", 0) for c in controls[b.dialog.handle])) else {}),
                }
                for b in blocks
            ],
            "unexplained": [
                {
                    "window": u.blocked.text or u.blocked.class_name,
                    "note": "disabled with no visible dialog to account for "
                            "it; a dialog may be off-screen, on another "
                            "desktop, or owned by a thread that stopped "
                            "pumping",
                }
                for u in unexplained
            ],
        }



    def hit_targets(self, session_id: str, locator: str, *,
                    all_windows: bool = False) -> dict:
        """The child windows inside a container, with their rectangles.

        A native container -- a panel of toggle bars, a toolbar of speed
        buttons -- answers `find` with one match: itself. Its parts may be
        child windows (addressable) or painted (not). This lists the child
        windows there are, so a caller aims a point click at a real target
        instead of reading coordinates off a screenshot by eye and missing a
        twelve-pixel bar (D67). None listed means the parts are painted:
        capture the container and click at an offset, or hand it to a person.
        """
        try:
            session = self.sessions.authorize(session_id, "hit_targets")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)
        try:
            matches = self._resolve(session, locator, all_windows)
        except ValueError as exc:
            return _error(ErrorKind.NOT_FOUND, str(exc), locator=locator)
        matches = [m for m in matches if not isinstance(m, AccessibleElement)]
        if not matches:
            return _error(ErrorKind.NOT_FOUND,
                          f"no window matches {locator!r}", locator=locator)
        if len(matches) > 1:
            return _error(ErrorKind.AMBIGUOUS,
                          f"{len(matches)} windows matched {locator!r}; name one "
                          "with within= or index=", locator=locator)
        container = matches[0]

        c_left, c_top, c_right, c_bottom = container.rect

        def descend(node, depth):
            out = []
            for child in node.children:
                left, top, right, bottom = child.rect
                entry = {
                    "class": child.class_name,
                    "text": child.text if child.responsive else None,
                    "handle_ephemeral": f"0x{child.handle:08X}",
                    "rect": {"left": left, "top": top, "right": right, "bottom": bottom},
                    "depth": depth,
                }
                if right <= c_left or left >= c_right or bottom <= c_top or top >= c_bottom:
                    # A child wholly outside its container is clipped away or
                    # scrolled out of view: not a target a click can reach.
                    entry["outside_container"] = True
                out.append(entry)
                out.extend(descend(child, depth + 1))
            return out

        targets = descend(container, 1)
        report = {
            "ok": True,
            "locator": locator,
            "container": _element(container),
            "hit_targets": targets,
            "count": len(targets),
        }
        outside = [t for t in targets if t.get("outside_container")]
        if outside:
            report["outside_container"] = len(outside)
            report["outside_note"] = (
                "child window(s) lie wholly outside the container's rectangle: "
                "clipped or scrolled out of view, so not reachable by a click "
                "until the container scrolls or grows"
            )
        if not targets or len(outside) == len(targets):
            report["note"] = (
                "this container has no reachable child windows: its hit targets "
                "are painted, not windowed. `capture` it to see them and `click` "
                "at={x, y} at an offset, or hand the step to a person"
            )
        return report

    def wait_idle(self, session_id: str, *, timeout_s: float = 30.0,
                  poll_s: float = 0.5) -> dict:
        """Wait until the target's profile-declared busy indicator clears.

        On a target where "the action completed" and "the screen shows the
        result" are seconds apart -- grids that fill one row at four seconds
        and four at eight -- a read taken between them is a confident wrong
        answer (D69). The profile names how the target shows it is busy;
        this waits for that to stop, and says how long it took.
        """
        try:
            session = self.sessions.authorize(session_id, "wait_idle")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)
        if not session.profile.busy_indicator:
            return _error(
                ErrorKind.NOT_ACTIONABLE,
                "this session's profile names no busy_indicator, so there is "
                "nothing to wait on. Add one to the profile ({\"locator\": ...} "
                "present while busy, or {\"region\": ..., \"ink_above\": ...}), "
                "or use wait_for with condition=settled on the control you need")
        import time as _time

        started = _time.monotonic()
        deadline = started + max(0.0, timeout_s)
        busy = self._busy(session)
        polls = 1
        while busy and _time.monotonic() < deadline:
            _time.sleep(poll_s)
            busy = self._busy(session)
            polls += 1
        waited_ms = int((_time.monotonic() - started) * 1000)
        if busy:
            return {"ok": False, "idle": False, "waited_ms": waited_ms, "polls": polls,
                    "error": {"kind": ErrorKind.TIMEOUT.value,
                              "message": f"still busy after {waited_ms}ms; the target may "
                                         "be stuck, or the indicator may stay on -- capture "
                                         "to see"}}
        return {"ok": True, "idle": True, "waited_ms": waited_ms, "polls": polls}

    def restore(self, session_id: str) -> dict:
        """Un-minimize the target, reporting whether that took the foreground.

        It can. Measured: a plain minimized top-level window shown with
        SW_SHOWNOACTIVATE by a process allowed to set the foreground comes
        back *activated* -- there is no un-minimize that does not. The
        no-activate show holds for the case this was built for (a toolkit's
        minimized owner proxy, whose forms the application re-shows itself),
        and `took_foreground` says which case happened. Marked as changing
        the screen for this reason; a caller wanting the guarantee should
        ask the operator to click the taskbar instead.
        """
        try:
            session = self.sessions.authorize(session_id, "restore")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)
        if session_id in self._watches:
            return _error(
                ErrorKind.NOT_ACTIONABLE,
                "this session keeps its target minimized (isolation=minimized); "
                "the watchdog would put it straight back. Release the session, "
                "then un-minimize it from the taskbar.",
            )

        from ..backends import current
        winapi = current().winapi
        from ..backends import current
        restore_process = current().restore_process

        result = restore_process(session.pid)
        return {
            "ok": True,
            # Named, not just counted: a restore that found something minimized
            # when the caller believed nothing was is a question, and the
            # class and visibility of what it found is the answer's first
            # half. (A full-suite run has twice found a fixture window
            # minimized that nothing minimized; alone it never reproduces.)
            "restored": [
                {"handle_ephemeral": f"0x{h:08X}",
                 "class": winapi.class_name(h),
                 "visible_style": winapi.is_visible_style(h)}
                for h in result.restored
            ],
            "now_visible": [
                {"handle_ephemeral": f"0x{h:08X}",
                 "class": winapi.class_name(h)}
                for h in result.newly_visible
            ],
            "took_foreground": result.took_foreground,
            "note": ("nothing was minimized" if not result.restored else
                     "the application re-showed its own forms"),
        }
