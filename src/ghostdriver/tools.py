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
import time
from dataclasses import dataclass, replace
from typing import Any

from .model.locator import Locator
from .model.result import ErrorKind, GhostdriverError
from .model.window import WindowNode, select_main_tree
from .hosting import classify_process, hosted_frame_note, is_frame_host
from .policy import (
    ConsentSource, Tier, describe_target, extract_endpoints,
)
from .resolve import resolve
from .session import ConsentRequired, Profile, SessionManager
from .summarize import summarize
from .disturbance import INPUT_SENSITIVE_HINT
from .wait import Condition, wait_for

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
        # this session will actually read, not on the process, and it names
        # the application inside so the caller gets a pid to attach to.
        selected = self._trees(session.pid, all_windows=False)
        if selected and is_frame_host(selected[0].class_name):
            from .backends.windows.hosted import resolve_hosted_app

            found = resolve_hosted_app(selected[0].handle, session.pid)
            app_name = ""
            if found is not None:
                try:
                    app_name = psutil.Process(found.pid).name()
                except (psutil.Error, OSError):
                    app_name = ""
            summary["window_ownership"] = "measured-a-frame"
            summary["hosting_note"] = hosted_frame_note(
                found.pid if found else None, app_name,
                found.share if found else 0.0,
            )
            if found is not None:
                summary["hosted_application_pid"] = found.pid
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

        from .backends.windows.text import is_protected

        values = []
        for node in matches[:MAX_ELEMENTS]:
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

    # --- actuation -------------------------------------------------------
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
            matches = self._resolve(session.pid, locator, all_windows)
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
        from .backends.windows.text import is_protected

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
        from .cadence import ROBOT, by_name

        if requested is not None:
            return by_name(requested)
        notes = session.profile.sensitivity
        if not notes.notes:
            return ROBOT
        if all(n.surface == "*" for n in notes.notes):
            return notes.cadence_for()

        from .backends.windows.modality import surface_of

        return notes.cadence_for(surface_of(handle))

    def _actuator(self, pid: int):
        from .actuate import Actuator
        from .backends.windows.modality import snapshot

        return Actuator(observe=lambda: snapshot(pid))

    def _remember(self, session_id: str, tool: str, locator: str,
                  prepared, result) -> None:
        """Record the outcome, so a later claim about it can be checked.

        Every actuation, not only failures: a differential needs both
        halves, and the successful paced attempt is the half that makes the
        failure mean something.
        """
        from .backends.windows.modality import surface_of
        from .ledger import Outcome

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

    def click(
        self,
        session_id: str,
        locator: str,
        *,
        all_windows: bool = False,
        expect: dict | None = None,
    ) -> dict:
        """Actuate one control.

        `expect` names something that should be true afterwards -- a locator
        and the text it should then have. Without it the result reports that
        the input was delivered and claims nothing about its effect, because
        on this class of target those are genuinely different statements.
        """
        prepared, failure = self._prepared(
            session_id, "click", locator, all_windows, None
        )
        if failure is not None:
            return failure

        from .backends.windows import verbs

        try:
            after, described = self._expectation(prepared.session, expect)
        except ValueError as exc:
            return _error(ErrorKind.NOT_FOUND, f"expect is unusable: {exc}")
        result = self._actuator(prepared.session.pid).perform(
            verbs.click(prepared.node.handle),
            expect_before=verbs.unblocked(prepared.node.handle),
            expect_after=after,
        )
        self._remember(session_id, "click", locator, prepared, result)
        return self._reported(
            result, prepared, locator,
            verified=("effect" if after is not None and result.ok
                      else "delivery_only"),
            expected=described,
        )

    def set_value(
        self,
        session_id: str,
        locator: str,
        text: str,
        *,
        all_windows: bool = False,
        expect_text: str | None = None,
        expect: dict | None = None,
        cadence: str | None = None,
    ) -> dict:
        """Replace a field\'s contents, and check what actually landed.

        Two different things can go wrong here and both are silent, so both
        are checked rather than assumed.

        **The field may not have taken all of it.** Typing goes through the
        control\'s own input handling, so a length limit or a mask applies
        exactly as it would to a person -- measured at about twenty
        characters on a field whose declared limit was thirty thousand. The
        display is therefore always read back and compared. A field that
        reformats what it is given (a date mask turning 01012026 into
        01/01/2026) will fail that comparison the first time; pass
        `expect_text` with the reformatted value and the reformatting
        becomes something asserted rather than something skimmed past.

        **The application may not have accepted it.** A field can display a
        value the application never received. Nothing here can see that --
        it shows up in a mirror label, a grid cell, a change log -- so
        `expect` is how a caller names where to look. Only then does the
        result say `verified: "committed"`.

        With `expect`, a pattern-based tier is offered first and falls
        through if it does not commit. Without it, this types and only
        types: an unverifiable shortcut whose failure is invisible is not
        worth the milliseconds it saves.
        """
        prepared, failure = self._prepared(
            session_id, "set_value", locator, all_windows, cadence
        )
        if failure is not None:
            return failure

        refusal = self._refuse_if_protected(prepared.node, "type into")
        if refusal is not None:
            return refusal

        from .actuate import Condition
        from .backends.windows import verbs
        from .backends.windows.text import read_window_text

        handle = prepared.node.handle
        wanted = text if expect_text is None else expect_text
        shows = lambda: (read_window_text(handle) or "") == wanted  # noqa: E731

        try:
            commit, described = self._expectation(prepared.session, expect)
        except ValueError as exc:
            return _error(ErrorKind.NOT_FOUND, f"expect is unusable: {exc}")
        if commit is None:
            after = Condition(shows, f"the field shows {wanted!r}")
        else:
            after = Condition(
                lambda: shows() and commit.check(),
                f"the field shows {wanted!r} and {commit.description}",
            )

        result = self._actuator(prepared.session.pid).perform(
            verbs.set_text(handle, text, cadence=prepared.cadence,
                           allow_pattern=commit is not None),
            expect_before=verbs.unblocked(handle),
            expect_after=after,
        )

        self._remember(session_id, "set_value", locator, prepared, result)
        shown = read_window_text(handle)
        reported = self._reported(
            result, prepared, locator,
            verified=("committed" if commit is not None and result.ok
                      else "display" if result.ok else "none"),
            display=shown,
            expected=described,
        )
        if not result.ok and shown is not None and shown != wanted:
            reported["error"]["message"] += (
                f"; the field shows {shown!r}, not {wanted!r}. If the control "
                "reformats what it is given, pass expect_text with the value "
                "it should end up showing"
            )
        if commit is None and result.ok:
            reported["unverified"] = (
                "the field displays this value; whether the application "
                "accepted it was not checked. Pass expect naming where the "
                "committed value appears to check it"
            )
        return reported

    def type_text(
        self,
        session_id: str,
        locator: str,
        text: str,
        *,
        all_windows: bool = False,
        cadence: str | None = None,
        expect: dict | None = None,
    ) -> dict:
        """Type into a control at the caret, without clearing it first.

        `set_value` is what replaces a field. This appends, inserts, or
        types into something that is not a field at all -- a grid cell in
        edit mode, a search box that filters as it goes.
        """
        prepared, failure = self._prepared(
            session_id, "type_text", locator, all_windows, cadence
        )
        if failure is not None:
            return failure

        refusal = self._refuse_if_protected(prepared.node, "type into")
        if refusal is not None:
            return refusal

        from .backends.windows import verbs

        try:
            after, described = self._expectation(prepared.session, expect)
        except ValueError as exc:
            return _error(ErrorKind.NOT_FOUND, f"expect is unusable: {exc}")
        result = self._actuator(prepared.session.pid).perform(
            verbs.send_keys(prepared.node.handle, list(text),
                            cadence=prepared.cadence),
            expect_before=verbs.unblocked(prepared.node.handle),
            expect_after=after,
        )
        self._remember(session_id, "type_text", locator, prepared, result)
        return self._reported(
            result, prepared, locator,
            verified=("effect" if after is not None and result.ok
                      else "delivery_only"),
            expected=described,
        )

    def send_keys(
        self,
        session_id: str,
        locator: str,
        keys: list[str],
        *,
        all_windows: bool = False,
        cadence: str | None = None,
        expect: dict | None = None,
    ) -> dict:
        """Send named keys to a control.

        For keys whose meaning is the key rather than the character:
        `enter`, `tab`, `escape`, `backspace`, `delete`. On this class of
        target these often reach things the mouse cannot -- committing a
        grid row, dismissing a dialog whose buttons ignore clicks.
        """
        prepared, failure = self._prepared(
            session_id, "send_keys", locator, all_windows, cadence
        )
        if failure is not None:
            return failure

        from .backends.windows import verbs
        from .backends.windows.input import NAMED_KEYS

        # Named keys carry nothing, so `tab` out of a password field a
        # person has filled in is fine. A character is the credential.
        if any(len(k) == 1 for k in keys):
            refusal = self._refuse_if_protected(prepared.node,
                                                "send characters to")
            if refusal is not None:
                return refusal

        unknown = [k for k in keys
                   if k.lower() not in NAMED_KEYS and len(k) != 1]
        if unknown:
            return _error(
                ErrorKind.NOT_ACTIONABLE,
                f"unknown key name(s) {unknown}; expected a single character "
                f"or one of {sorted(NAMED_KEYS)}",
            )

        try:
            after, described = self._expectation(prepared.session, expect)
        except ValueError as exc:
            return _error(ErrorKind.NOT_FOUND, f"expect is unusable: {exc}")
        result = self._actuator(prepared.session.pid).perform(
            verbs.send_keys(prepared.node.handle, keys,
                            cadence=prepared.cadence),
            expect_before=verbs.unblocked(prepared.node.handle),
            expect_after=after,
        )
        self._remember(session_id, "send_keys", locator, prepared, result)
        return self._reported(
            result, prepared, locator,
            verified=("effect" if after is not None and result.ok
                      else "delivery_only"),
            expected=described,
            keys=keys,
        )

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

        from .actuate import Condition
        from .backends.windows.text import read_window_text

        where = expect.get("locator")
        wanted = expect.get("text")
        if not where:
            return None, None
        Locator.parse(where)  # raises ValueError, caught by the caller

        def holds() -> bool:
            found = self._resolve(session.pid, where,
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

        from .sensitivity import learned_from_differential, merge_into_document

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
    ) -> dict:
        """Hand a step to the person, and wait for the target to show it done.

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

        from .backends.windows.text import read_window_text

        wanted = until.get("text")
        # "gone" is as common a signal as "there": a sign-in dialog closing
        # is how you know someone signed in.
        absent = bool(until.get("absent", False))

        def satisfied() -> bool:
            found = self._resolve(session.pid, where, all_windows)
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
