"""The macro lifecycle, minus record and replay: save, list, show, delete (#86).

A macro is a workflow file (D#84), so these are operator bookkeeping over the
operator directory's `workflows/` folder -- session-free, like `list_targets`
and `grant_targets`, and never target knowledge in the repo (D60). Recording a
macro from a live session is `macro_record` (#88); running one is
`macro_replay` (#87). Here a macro is created from a step-list the caller
already has (the `batch` it just ran, say), read back, listed, and archived.
"""

import json
import time

from ..model.result import ErrorKind, GhostdriverError
from ..operator import ENV_VAR, OperatorDir, OperatorDirError
from ..policy import Tier
from ..workflow import (
    Branch,
    ForEach,
    RepeatUntil,
    Workflow,
    WorkflowError,
    bind,
    missing_required,
    run_macro_body,
)
from .core import _error, _ToolboxCore


def _describe_node(node) -> dict:
    """A node for `macro_show`: a leaf's tool and its honesty flags, or a
    branch's condition and arms -- so a reader sees the shape and which steps
    are verified vs merely delivered, without the full args."""
    if isinstance(node, Branch):
        return {
            "when": node.when.locator,
            "then": [_describe_node(n) for n in node.then],
            "else": [_describe_node(n) for n in node.otherwise],
            "note": node.note,
        }
    if isinstance(node, RepeatUntil):
        return {"repeat_until": node.until.locator, "max": node.max,
                "do": [_describe_node(n) for n in node.do], "note": node.note}
    if isinstance(node, ForEach):
        return {"for_each": node.var, "in": node.items,
                "do": [_describe_node(n) for n in node.do], "note": node.note}
    return {"tool": node.tool, "verified": node.verified,
            "delivery_only": node.delivery_only, "note": node.note}


def _no_directory() -> dict:
    return _error(
        ErrorKind.NOT_ACTIONABLE,
        f"macros live in the operator directory ({ENV_VAR}); none is configured, "
        "so there is nowhere to keep one")


#: Tier order, so replay can check a session is at least the tier a macro
#: declares before it runs a step the session's own tier would refuse anyway
#: -- a fail-fast with a clear reason (#87).
_TIER_RANK = {Tier.READ_ONLY: 0, Tier.INTERACTIVE: 1, Tier.FULL: 2}


def _plan_node(node, bindings: dict) -> dict:
    """One node in a dry-run plan: a leaf with its params bound, or a branch
    whose arm is chosen at run time. A plan is honest that a branch cannot be
    resolved without acting -- the condition is read from the screen the
    previous step leaves (docs/MACROS.md, open questions)."""
    if isinstance(node, Branch):
        return {
            "when": node.when.locator,
            "resolved": "at run time (the condition is read from the target)",
            "then": [_plan_node(n, bindings) for n in node.then],
            "else": [_plan_node(n, bindings) for n in node.otherwise],
        }
    if isinstance(node, RepeatUntil):
        return {"repeat_until": node.until.locator, "max": node.max,
                "resolved": "runs the body until the condition holds, at run time",
                "do": [_plan_node(n, bindings) for n in node.do]}
    if isinstance(node, ForEach):
        resolved, unbound = (bind(node.items, bindings)
                             if isinstance(node.items, str) else (node.items, []))
        entry = {"for_each": node.var, "in": resolved,
                 "do": [_plan_node(n, bindings) for n in node.do]}
        if unbound:
            entry["unbound"] = unbound
        return entry
    bound_args, unbound = bind(node.args, bindings)
    entry = {"tool": node.tool, "args": bound_args,
             "verified": node.verified, "delivery_only": node.delivery_only}
    if unbound:
        entry["unbound"] = unbound
    return entry


class MacroTools(_ToolboxCore):
    """Create, read, list and archive macros. Operator bookkeeping, not a
    session's -- these touch the operator directory, not a target."""

    def macro_save(self, name: str, steps: list, *, description: str = "",
                   tier: str = "read_only", isolation: str = "none",
                   profile: str | None = None, params: dict | None = None,
                   provenance: dict | None = None, handlers: list | None = None) -> dict:
        """Persist a step-list as a macro, validated. The steps are the macro
        body (leaves, `when` branches, loops, D#84/#97); `handlers` are reactive
        on_disturbance handlers (#106); `params` and `provenance` are stored as
        given. A malformed macro is refused here, not at replay."""
        doc: dict = {"name": name, "steps": steps, "tier": tier}
        if handlers:
            doc["handlers"] = handlers
        if description:
            doc["description"] = description
        if isolation != "none":
            doc["isolation"] = isolation
        if profile:
            doc["profile"] = profile
        if params:
            doc["params"] = params
        if provenance:
            doc["provenance"] = provenance
        try:
            Workflow.from_dict(doc)  # validate; raises WorkflowError
        except WorkflowError as exc:
            return _error(ErrorKind.NOT_ACTIONABLE, f"the macro is malformed: {exc}")
        try:
            folder = OperatorDir.resolve()
        except OperatorDirError:
            return _no_directory()
        try:
            path, replaced = folder.save_workflow(name, doc)
        except OperatorDirError as exc:
            return _error(ErrorKind.NOT_ACTIONABLE, str(exc))
        return {"ok": True, "name": name, "saved_to": str(path), "replaced": replaced}

    def macro_list(self) -> dict:
        """Every macro's name, description, step count and params."""
        try:
            folder = OperatorDir.resolve()
        except OperatorDirError:
            return _no_directory()
        macros = []
        for name in folder.list_workflows():
            entry: dict = {"name": name}
            try:
                data = json.loads((folder.workflows / f"{name}.json")
                                  .read_text(encoding="utf-8"))
                entry["description"] = str(data.get("description", ""))
                entry["steps"] = len(data.get("steps") or [])
                entry["params"] = sorted((data.get("params") or {}).keys())
            except (OSError, json.JSONDecodeError):
                entry["description"] = "(unreadable)"
            macros.append(entry)
        return {"ok": True, "macros": macros, "total": len(macros)}

    def macro_show(self, name: str) -> dict:
        """One macro: its metadata, provenance, params, and per-step verified /
        delivery_only flags -- the honesty a reader needs before replaying it."""
        try:
            folder = OperatorDir.resolve()
        except OperatorDirError:
            return _no_directory()
        try:
            path = folder.workflow_path(name)  # raises if not there
        except OperatorDirError as exc:
            return _error(ErrorKind.NOT_FOUND, str(exc))
        try:
            wf = Workflow.load(path)
        except WorkflowError as exc:
            return _error(ErrorKind.NOT_ACTIONABLE, f"the macro will not load: {exc}")
        return {
            "ok": True,
            "name": wf.name,
            "description": wf.description,
            "tier": wf.tier,
            "profile": wf.profile,
            "params": [{"name": p.name, "required": p.required, "note": p.note}
                       for p in wf.params],
            "provenance": {"recorded_at": wf.provenance.recorded_at,
                           "recorded_against": wf.provenance.recorded_against,
                           "revision": wf.provenance.revision},
            "steps": [_describe_node(n) for n in wf.steps],
            "handlers": [{"on_disturbance": h.window, "then": h.then, "max": h.max,
                          "handle": [_describe_node(n) for n in h.handle]}
                         for h in wf.handlers],
        }

    def macro_delete(self, name: str) -> dict:
        """Archive a macro rather than destroy it. It leaves the listing but
        stays recoverable under the archive -- deleting operator data the tool
        did not create is a thing to be able to undo (the look-before rule)."""
        try:
            folder = OperatorDir.resolve()
        except OperatorDirError:
            return _no_directory()
        try:
            folder.workflow_path(name)  # raises if it is not there
        except OperatorDirError as exc:
            return _error(ErrorKind.NOT_FOUND, str(exc))
        dest = folder.archive_workflow(name, time.strftime("%Y%m%d-%H%M%S"))
        return {"ok": True, "name": name, "archived_to": str(dest),
                "note": "archived, not destroyed; recover it from the archive if needed"}

    def macro_replay(self, session_id: str, name: str, *,
                     params: dict | None = None, dry_run: bool = False) -> dict:
        """Replay a macro against an already-attached session.

        The operator has approved the target and chosen its tier by attaching;
        replay runs the macro's body against that session through the shared
        core (D#85), under the interference watch a workflow run uses -- a
        foreground taken by the target during the run fails it whatever the
        steps said. Params are bound here (a missing required one is refused,
        not guessed, D33); `dry_run` resolves them and returns the plan without
        acting, which a mutating macro's first run should look at. A macro
        recorded against a different profile is warned about, not refused,
        unless one of its locators cannot resolve. Replays from the start and
        reports where it stopped; resume is deferred.
        """
        try:
            session = self.sessions.authorize(session_id, "macro_replay")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)
        try:
            folder = OperatorDir.resolve()
        except OperatorDirError:
            return _no_directory()
        try:
            path = folder.workflow_path(name)
        except OperatorDirError as exc:
            return _error(ErrorKind.NOT_FOUND, str(exc))
        try:
            wf = Workflow.load(path)
        except WorkflowError as exc:
            return _error(ErrorKind.NOT_ACTIONABLE, f"the macro will not load: {exc}")

        bindings = dict(params or {})
        missing = missing_required(wf.params, bindings)

        warnings = []
        recorded = wf.provenance.recorded_against
        here = session.profile.profile_id
        if recorded and here and recorded != here:
            warnings.append(
                f"this macro was recorded against profile {recorded!r}, but the "
                f"session's profile is {here!r}; a locator from one target class "
                "may mean nothing on another -- replaying anyway, watch the steps")

        # A dry run inspects; it neither acts nor is gated. It shows the plan
        # with params bound (an unbound one marked, not refused), so a mutating
        # macro's first run -- or a read-only session -- can see what it would
        # do before it does it.
        if dry_run:
            return {
                "ok": True, "dry_run": True, "name": wf.name, "tier": wf.tier,
                "warnings": warnings, "missing_required": missing,
                "plan": [_plan_node(n, bindings) for n in wf.steps],
                "handlers": [{"on_disturbance": h.window, "then": h.then, "max": h.max,
                              "handle": [_plan_node(n, bindings) for n in h.handle]}
                             for h in wf.handlers],
                "note": "nothing was actuated; a branch resolves at run time, so "
                        "the plan shows both arms, and a handler fires only if its "
                        "window appears",
            }

        # A real run binds or refuses (D33), and needs a session at least the
        # macro's declared tier -- its steps enforce their own tier too, but
        # this fails fast with the reason rather than midway through.
        if missing:
            return _error(
                ErrorKind.NOT_ACTIONABLE,
                f"the macro needs param(s) {missing} bound at replay; pass "
                f"params={{{missing[0]!r}: ...}}. A macro never guesses a value.")
        try:
            needed = Tier(wf.tier)
        except ValueError:
            needed = Tier.READ_ONLY
        if _TIER_RANK.get(session.tier, 0) < _TIER_RANK.get(needed, 0):
            return _error(
                ErrorKind.DENIED_BY_POLICY,
                f"this macro is written for the {needed.value!r} tier, but the "
                f"session is {session.tier.value!r}; re-attach at {needed.value!r} "
                "to replay it")

        from ..backends import current
        watch = current().InterferenceWatch(
            session.pid, family=lambda: [session.pid, *_descendants(session.pid)])
        watch.start()
        try:
            outcome = run_macro_body(self, session_id, wf.steps, bindings,
                                     context="macro", handlers=wf.handlers)
        finally:
            watch.stop()
        interference = watch.events()
        took_foreground = any(e.get("kind") == "foreground_taken" for e in interference)

        result = dict(outcome)
        result["name"] = wf.name
        if warnings:
            result["warnings"] = warnings
        if interference:
            result["interference"] = interference
        if took_foreground:
            result["ok"] = False
            result["foreground_taken"] = True

        stamp = time.strftime("%Y%m%d-%H%M%S")
        report = {
            "macro": wf.name, "session": session_id, "pid": session.pid,
            "ok": result["ok"], "bindings": bindings, "warnings": warnings,
            "steps": outcome["steps"], "refused": outcome.get("refused"),
            "stopped_at": outcome.get("stopped_at"), "interference": interference,
        }
        try:
            result["report_saved_to"] = str(
                folder.write_report(f"macro-{wf.name}", stamp, report))
        except OSError:
            result["report_saved_to"] = None
        return result

    # --- recording (#88) ---------------------------------------------------

    def record_start(self, session_id: str) -> dict:
        """Begin recording this session's actuations into a buffer, to be
        saved as a macro. Only the doing is captured -- clicks, typing, waits
        -- not the reads used to decide, and only calls that succeed, so a
        refused secret never lands in a macro. Each captured step carries
        whether it was verified or only delivered (D66)."""
        try:
            session = self.sessions.authorize(session_id, "record_start")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)
        if session_id in self._recordings:
            return _error(ErrorKind.NOT_ACTIONABLE,
                          "already recording this session; record_save or "
                          "record_discard the current one first")
        self._recordings[session_id] = {
            "steps": [], "started_at": time.time(),
            "profile_id": session.profile.profile_id, "tier": session.tier.value,
        }
        return {"ok": True, "recording": True, "session": session_id}

    def record_save(self, session_id: str, name: str, *, description: str = "",
                    params: dict | None = None) -> dict:
        """Stop recording and save the buffered steps as a macro. Provenance
        records when and against which profile it was recorded. The result
        says how many steps are delivery_only (unconfirmed), so the recorder
        is never sold as more certain than it is."""
        try:
            self.sessions.authorize(session_id, "record_save")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)
        recording = self._recordings.pop(session_id, None)
        if recording is None:
            return _error(ErrorKind.NOT_ACTIONABLE,
                          "not recording this session; record_start first")
        steps = recording["steps"]
        if not steps:
            return _error(ErrorKind.NOT_ACTIONABLE,
                          "nothing a macro can replay was recorded -- the session "
                          "did no actuations, or none succeeded")
        provenance = {
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                         time.gmtime(recording["started_at"])),
            "recorded_against": recording["profile_id"],
            "revision": 1,
        }
        result = self.macro_save(name, steps, description=description,
                                 tier=recording["tier"], params=params,
                                 provenance=provenance)
        if result.get("ok"):
            delivered = sum(1 for step in steps if step.get("delivery_only"))
            result["recorded"] = len(steps)
            result["delivery_only"] = delivered
            if delivered:
                result["note"] = (
                    f"{delivered} of {len(steps)} recorded steps are delivery_only "
                    "-- an offset click on a painted region, or an actuation with no "
                    "expect -- so replay cannot confirm them by locator; review them")
        else:
            # the save was refused: put the recording back so it is not lost
            self._recordings[session_id] = recording
        return result

    def record_discard(self, session_id: str) -> dict:
        """Stop recording and throw the buffer away."""
        try:
            self.sessions.authorize(session_id, "record_discard")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)
        discarded = self._recordings.pop(session_id, None) is not None
        return {"ok": True, "discarded": discarded}


def _descendants(pid: int) -> list:
    """The processes the target spawned, through the backend -- so the
    interference watch covers a dialog a helper process owns (D71)."""
    from ..backends import current
    try:
        return list(current().descendants(pid))
    except Exception:
        return []
