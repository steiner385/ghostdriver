"""The tool surface, as plain functions returning plain data.

Deliberately separate from the MCP binding. The protocol layer is a thin
adapter over this; everything that could be wrong — a tier not enforced, a
result that blows a context budget, an error that says nothing useful — is
wrong here, and can be tested here without a protocol client.

Two rules shape every result.

**Locators, not handles.** A handle is valid only for the enumeration that
produced it: the OS recycles them, and one held across a call answers about
a window that no longer exists. Every element carries a locator that can be
re-resolved instead. Handles are still reported, marked ephemeral, because
they are what makes two same-captioned controls distinguishable in a single
result — but nothing should store one.

**Results are for an agent's context, not a file.** A target with ~1,100
windows can answer almost any query with more than a caller can read.
Everything that can return many rows caps them and says what it capped.
"""

import base64
from dataclasses import dataclass
from typing import Any

from .model.locator import Locator
from .model.result import ErrorKind, GhostdriverError
from .model.window import WindowNode, select_main_tree
from .hosting import classify_process, note_for_measured_window
from .policy import (
    ConsentSource, Tier, describe_target, extract_endpoints,
)
from .resolve import resolve
from .session import ConsentRequired, Profile, SessionManager
from .summarize import summarize
from .wait import Condition, wait_for

#: Most elements any single result will enumerate. A locator matching more
#: than this is almost always a locator that needs narrowing, and returning
#: nine hundred rows to prove it helps nobody.
MAX_ELEMENTS = 50


def _error(kind: ErrorKind, message: str, **extra: Any) -> dict:
    return {"ok": False, "error": {"kind": kind.value, "message": message, **extra}}


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
    if node.text:
        described["locator"] = f'class={node.class_name} text="{node.text}"'
    return described


@dataclass
class Toolbox:
    """Every tool, over one session manager."""

    sessions: SessionManager

    # --- lifecycle -------------------------------------------------------

    def list_targets(self) -> dict:
        """Every process that owns windows, and what it is connected to.

        The endpoint is here because this is the list a person is shown when
        deciding which targets to allow. "the client" is not enough to
        answer with; "the client, connected to the dev gateway" is.
        """
        import psutil

        from .backends.windows import winapi
        from .backends.windows.enumerate import top_level_windows

        attached = {s.pid: s.session_id for s in self.sessions.open_sessions()}
        targets = []
        for process in psutil.process_iter(["pid", "name"]):
            pid = process.info["pid"]
            try:
                windows = top_level_windows(pid)
            except OSError:
                continue
            if not windows:
                continue
            try:
                endpoints = extract_endpoints(psutil.Process(pid).cmdline())
            except (psutil.Error, OSError):
                endpoints = []
            grant = self.sessions.grant_for(pid)
            # Whether this process owns windows for other applications, or
            # is an application whose frame something else owns. Cheap: the
            # top-level class names alone decide it.
            kind, note = classify_process(
                [winapi.class_name(h) for h in windows]
            )
            targets.append({
                "pid": pid,
                "name": process.info["name"],
                "top_level_windows": len(windows),
                "endpoints": [e.normalized for e in endpoints],
                "summary": describe_target(
                    process.info["name"], pid, endpoints
                ),
                "consent": (
                    None if grant is None
                    else ("allowed" if grant.allowed else "restricted")
                ),
                "window_ownership": kind,
                "hosting_note": note,
                "session_id": attached.get(pid),
            })
        targets.sort(key=lambda t: -t["top_level_windows"])
        return {
            "ok": True,
            "targets": targets[:MAX_ELEMENTS],
            "total": len(targets),
            "note": (
                "No target may be automated until the operator approves it "
                "for this session. Show them the candidates and ask which "
                "to allow and which to leave alone."
            ),
        }

    def grant_targets(
        self,
        allow: list[int] | None = None,
        restrict: list[int] | None = None,
        *,
        note: str = "",
        source: ConsentSource = ConsentSource.OPERATOR_TOOL,
    ) -> dict:
        """Record which targets the operator approved or ruled out.

        Session-scoped and revisable: a later decision replaces an earlier
        one, so someone can change their mind mid-task without restarting
        anything. Restricting a target that already has an open session
        takes effect immediately -- the next call on that session refuses.
        """
        recorded = []
        for pid in allow or []:
            recorded.append(self.sessions.record_grant(
                pid, allowed=True, source=source, note=note))
        for pid in restrict or []:
            recorded.append(self.sessions.record_grant(
                pid, allowed=False, source=source, note=note))
        if not recorded:
            return _error(
                ErrorKind.NOT_ACTIONABLE,
                "nothing to record: pass allow=[...] or restrict=[...]",
            )
        grants = self.sessions.grants()
        return {
            "ok": True,
            "recorded": [g.describe() for g in recorded],
            "allowed": sorted(g.pid for g in grants if g.allowed),
            "restricted": sorted(g.pid for g in grants if not g.allowed),
        }

    def attach(
        self,
        pid: int,
        *,
        tier: str = "read_only",
        profile_path: str | None = None,
    ) -> dict:
        """Open a session against a target the operator has approved.

        When nobody has decided about this target yet, the result says so
        and carries what a person needs to be asked -- which application,
        and where it is pointed. That is a question, not a failure.
        """
        import psutil

        try:
            process = psutil.Process(pid)
            command_line = process.cmdline()
            name = process.name()
        except (psutil.Error, OSError) as exc:
            return _error(ErrorKind.NOT_FOUND, f"cannot read pid {pid}: {exc}")

        try:
            profile = (
                Profile.load(profile_path) if profile_path else Profile.none()
            )
            session = self.sessions.attach(
                pid,
                command_line=command_line,
                tier=Tier(tier),
                profile=profile,
            )
        except ConsentRequired as exc:
            endpoints = extract_endpoints(command_line)
            return {
                "ok": False,
                "error": {"kind": exc.kind.value, "message": exc.message},
                # Everything needed to put the question to a person, so the
                # caller does not have to go and gather it.
                "needs_consent": True,
                "target": {
                    "pid": pid,
                    "name": name,
                    "endpoints": [e.normalized for e in endpoints],
                    "summary": describe_target(name, pid, endpoints),
                },
            }
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)
        except ValueError:
            return _error(ErrorKind.DENIED_BY_POLICY,
                          f"unknown tier {tier!r}; "
                          f"expected one of {[t.value for t in Tier]}")

        summary = session.summary()
        summary["ok"] = True
        # Said at attach, not left for the caller to discover from a
        # profile that quietly describes a title bar. Judged on the window
        # this session will actually read, not on the process.
        selected = self._trees(session.pid, all_windows=False)
        note = (
            note_for_measured_window(selected[0].class_name)
            if selected else ""
        )
        if note:
            summary["window_ownership"] = "measured-a-frame"
            summary["hosting_note"] = note
        # Said at attach because it changes what every later call means: a
        # target with nothing on screen answers every read with nothing.
        summary["blocked"] = self._blocking(session.pid)
        return summary

    def release(self, session_id: str) -> dict:
        self.sessions.release(session_id)
        return {"ok": True, "released": session_id}

    # --- shared plumbing -------------------------------------------------

    def _trees(self, pid: int, all_windows: bool) -> list[WindowNode]:
        from .backends.windows.enumerate import enumerate_process

        trees = enumerate_process(pid)
        if not trees:
            return []
        if all_windows:
            return sorted(trees, key=lambda t: -sum(1 for _ in t.walk()))
        main = select_main_tree(trees)
        return [main] if main else []

    def _blocking(self, pid: int) -> list[str]:
        from .backends.windows.modality import top_level_state
        from .modality import find_modal_blocks

        blocks, unexplained = find_modal_blocks(top_level_state(pid))
        return (
            [b.describe() for b in blocks]
            + [
                f"{u.blocked.text or u.blocked.class_name} is disabled with "
                "no visible dialog to account for it"
                for u in unexplained
            ]
        )

    def _resolve(
        self, pid: int, expression: str, all_windows: bool
    ) -> list[WindowNode]:
        locator = Locator.parse(expression)
        return [
            node
            for tree in self._trees(pid, all_windows)
            for node in resolve(tree, locator)
        ]

    # --- discovery -------------------------------------------------------

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

        trees = self._trees(session.pid, all_windows)
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
            "blocked": self._blocking(session.pid),
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
            matches = self._resolve(session.pid, locator, all_windows)
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

    # --- reading ---------------------------------------------------------

    def read(
        self, session_id: str, locator: str, *, all_windows: bool = False
    ) -> dict:
        try:
            session = self.sessions.authorize(session_id, "read")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)

        from .backends.windows.text import read_window_text

        try:
            matches = self._resolve(session.pid, locator, all_windows)
        except ValueError as exc:
            return _error(ErrorKind.NOT_FOUND, str(exc), locator=locator)

        values = []
        for node in matches[:MAX_ELEMENTS]:
            raw = read_window_text(node.handle)
            values.append({
                "class": node.class_name,
                # None and "" are different answers: one is a control that
                # never replied, the other is a control that replied with
                # nothing. Collapsing them asserts a field is empty when it
                # may be full.
                "text": raw,
                "answered": raw is not None,
            })
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

        from .backends.windows.capture import CaptureError, capture_window

        trees = self._trees(session.pid, all_windows=False)
        if not trees:
            return _error(ErrorKind.NOT_FOUND,
                          f"pid {session.pid} has no windows on this desktop")
        target, crop = trees[0], None

        if locator:
            try:
                matches = self._resolve(session.pid, locator, True)
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
            png, width, height = capture_window(target.handle, region=crop)
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
            lambda: self._resolve(session.pid, locator, all_windows),
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

    # --- meta ------------------------------------------------------------

    def probe(self, session_id: str) -> dict:
        try:
            session = self.sessions.authorize(session_id, "probe")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)

        from .probe.runner import run_phase1

        try:
            document = run_phase1(session.pid)
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

        from .backends.windows.region import region_evidence
        from .surface import (
            SurfaceKind, map_digest, summarize_kinds, surface_map,
        )

        trees = self._trees(session.pid, all_windows)
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
        other = [r for r in regions if r.kind is not SurfaceKind.NATIVE]
        return {
            "ok": True,
            "blocked": self._blocking(session.pid),
            "kinds": summarize_kinds(regions),
            "shape_digest": digest,
            "changed": (changed_from is not None and changed_from != digest),
            "regions_needing_another_mechanism": [
                {
                    "kind": r.kind.value,
                    "class": r.class_name,
                    "rect": {"left": r.rect[0], "top": r.rect[1],
                             "right": r.rect[2], "bottom": r.rect[3]},
                    "area_px": r.area,
                    "reason": r.reason,
                }
                for r in sorted(other, key=lambda r: -r.area)[:MAX_ELEMENTS]
            ],
        }

    def modals(self, session_id: str) -> dict:
        try:
            session = self.sessions.authorize(session_id, "modals")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)

        from .backends.windows.modality import top_level_state
        from .modality import find_modal_blocks

        state = top_level_state(session.pid)
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
        """Un-minimize the target without taking the foreground."""
        try:
            session = self.sessions.authorize(session_id, "restore")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)

        from .backends.windows import winapi
        from .backends.windows.restore import restore_process

        result = restore_process(session.pid)
        return {
            "ok": True,
            "restored": [f"0x{h:08X}" for h in result.restored],
            "now_visible": [
                {"handle_ephemeral": f"0x{h:08X}",
                 "class": winapi.class_name(h)}
                for h in result.newly_visible
            ],
            "took_foreground": result.took_foreground,
            "note": ("nothing was minimized" if not result.restored else
                     "the application re-showed its own forms"),
        }
