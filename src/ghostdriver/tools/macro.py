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

from ..model.result import ErrorKind
from ..operator import ENV_VAR, OperatorDir, OperatorDirError
from ..workflow import Branch, Workflow, WorkflowError
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
    return {"tool": node.tool, "verified": node.verified,
            "delivery_only": node.delivery_only, "note": node.note}


def _no_directory() -> dict:
    return _error(
        ErrorKind.NOT_ACTIONABLE,
        f"macros live in the operator directory ({ENV_VAR}); none is configured, "
        "so there is nowhere to keep one")


class MacroTools(_ToolboxCore):
    """Create, read, list and archive macros. Operator bookkeeping, not a
    session's -- these touch the operator directory, not a target."""

    def macro_save(self, name: str, steps: list, *, description: str = "",
                   tier: str = "read_only", isolation: str = "none",
                   profile: str | None = None, params: dict | None = None,
                   provenance: dict | None = None) -> dict:
        """Persist a step-list as a macro, validated. The steps are the macro
        body (leaves and `when` branches, D#84); `params` and `provenance` are
        stored as given. A malformed macro is refused here, not at replay."""
        doc: dict = {"name": name, "steps": steps, "tier": tier}
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
