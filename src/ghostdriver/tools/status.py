"""Target status: probe, surfaces, modals, restore."""


from ..model.result import ErrorKind, GhostdriverError
from .core import (
    MAX_ELEMENTS,
    _error,
    _ToolboxCore,
)
from .guidance import BLOCKED_HINT, PIXELS_HINT


class StatusTools(_ToolboxCore):
    """The target's state at a glance -- profile, surfaces, modals -- and putting its windows back."""

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

    def modals(self, session_id: str) -> dict:
        try:
            session = self.sessions.authorize(session_id, "modals")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)

        from ..backends import current
        top_level_state = current().top_level_state
        from ..modality import find_modal_blocks

        state = session.run(lambda: top_level_state(session.pid))
        blocks, unexplained = find_modal_blocks(state)
        return {
            "ok": True,
            "blocked": bool(blocks or unexplained),
            "top_level_windows": len(state),
            "dialogs": [
                {
                    "dialog": b.dialog.text or b.dialog.class_name,
                    "dialog_class": b.dialog.class_name,
                    "holds": b.blocked.text or b.blocked.class_name,
                    "description": b.describe(),
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
