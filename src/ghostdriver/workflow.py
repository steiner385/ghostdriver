"""Workflows: a file of tool calls with expectations, run as one unit.

The generic half of the end-to-end harness. A workflow names no target of
its own -- it says "attach to the pid I am given, at this tier, under this
isolation" and then lists steps, each a call to one session tool with its
arguments and, optionally, assertions on the result. Which application,
which endpoints, which controls: those are the operator's, in files under
the operator directory, never here.

The runner does four things a bare sequence of tool calls would not:

- it runs the whole workflow under an interference watch, and a foreground
  taken by the target is a failed run whatever the steps said;
- it stops at the first failed step, because on a real application the
  steps after a failure act on a screen nobody intended;
- it asserts on results with dotted paths, so a workflow can say what it
  expected to read rather than only that a call returned ok;
- it writes a report -- every step, every result, every event -- back to
  the operator directory, where the next person can read what happened.

Pure with respect to the desktop: the toolbox and the watch are handed in,
so the runner is tested with fakes and the tools are tested with the
fixture, separately.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


class WorkflowError(ValueError):
    """The workflow file cannot be run as written."""


@dataclass(frozen=True)
class Step:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    #: Dotted path -> expected value. `values.0.text` reaches into lists.
    expect: dict[str, Any] = field(default_factory=dict)
    #: Dotted path -> substring the value must contain.
    expect_contains: dict[str, str] = field(default_factory=dict)
    #: Whether the call itself must report ok. Off for a step that exists
    #: to prove a refusal -- a denied caption, an ambiguous locator.
    expect_ok: bool = True
    note: str = ""
    #: Set by the recorder (#88): this step carried a postcondition that held
    #: when it was recorded. A step recorded with no `expect` is not verified.
    verified: bool = False
    #: An offset click on a painted region (D66): the least replayable step
    #: there is -- coordinates shift, handles recycle -- so the format says so
    #: out loud rather than pretending a point is a control.
    delivery_only: bool = False


#: The keys a leaf step may carry. An unknown key is refused, not ignored
#: (D33), the way `expect` refuses one (D#71): a typo that silently drops an
#: assertion is exactly the footgun this format exists to close.
STEP_KEYS = frozenset({"tool", "args", "expect", "expect_contains", "expect_ok",
                       "note", "verified", "delivery_only"})
#: The keys a `when` branch may carry.
BRANCH_KEYS = frozenset({"when", "then", "else", "note"})
#: The keys a branch's condition may carry. A locator that must resolve, with
#: an optional refinement. Evaluated in #85; validated here.
GUARD_KEYS = frozenset({"locator", "text", "selected", "pressed", "absent",
                        "all_windows"})
PARAM_KEYS = frozenset({"required", "note"})
PROVENANCE_KEYS = frozenset({"recorded_at", "recorded_against", "revision"})


@dataclass(frozen=True)
class Param:
    """A value bound at replay. A macro that embeds a specific id is a
    screenshot; one that declares a param and binds it is a tool."""
    name: str
    required: bool = True
    note: str = ""


@dataclass(frozen=True)
class Provenance:
    """Where a macro came from, so replay can be honest about it: a macro
    recorded against one profile means nothing on another target class."""
    recorded_at: str = ""
    recorded_against: str = ""  # a profile id
    revision: int = 0

    @property
    def is_empty(self) -> bool:
        return not (self.recorded_at or self.recorded_against or self.revision)


@dataclass(frozen=True)
class Guard:
    """A branch condition, in the locator/`expect` vocabulary the tools
    already speak, so the whole macro stays inspectable and diff-able. Never
    embedded code (that would stop being something a person can read and
    denylist-check). Parsed and validated here; turned into a `find`/`read`
    in #85."""
    locator: str
    text: str | None = None
    selected: bool | None = None
    pressed: bool | None = None
    absent: bool = False
    all_windows: bool = False


@dataclass(frozen=True)
class Branch:
    """`when` a condition holds, run `then`; otherwise run `otherwise`
    (the JSON key is `else`). The one v1 control-flow form; loops and
    handlers are v2/v3 (docs/MACROS.md)."""
    when: Guard
    then: tuple[Node, ...]
    otherwise: tuple[Node, ...] = ()
    note: str = ""


#: A node in a macro body is a leaf step or a branch. The tree is recursive:
#: a branch's arms are themselves nodes.
Node = Step | Branch

#: How deep branches may nest. A bound keeps a macro something a person can
#: still read at a glance, the same instinct as `pace`'s cap (D#76).
MAX_NEST_DEPTH = 8


@dataclass(frozen=True)
class Workflow:
    name: str
    steps: tuple[Node, ...]
    tier: str = "read_only"
    isolation: str = "none"
    profile: str | None = None
    description: str = ""
    #: Params bound at replay, `${name}` in a step's args (#85 substitutes).
    params: tuple[Param, ...] = ()
    provenance: Provenance = field(default_factory=Provenance)

    @classmethod
    def load(cls, path: Path) -> Workflow:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkflowError(f"cannot read workflow {path}: {exc}") from exc
        return cls.from_dict(data, default_name=path.stem)

    @classmethod
    def from_dict(cls, data: dict, *, default_name: str = "") -> Workflow:
        if not isinstance(data, dict):
            raise WorkflowError("a workflow is a JSON object")
        raw_steps = data.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise WorkflowError("a workflow needs a non-empty 'steps' list")
        return cls(
            name=str(data.get("name") or default_name or "workflow"),
            steps=_parse_nodes(raw_steps, "steps"),
            tier=str(data.get("tier", "read_only")),
            isolation=str(data.get("isolation", "none")),
            profile=data.get("profile"),
            description=str(data.get("description", "")),
            params=_parse_params(data.get("params")),
            provenance=_parse_provenance(data.get("provenance")),
        )


# --- parsing the macro body ------------------------------------------------

def _reject_unknown(where: str, raw: dict, allowed: frozenset[str]) -> None:
    extra = sorted(set(raw) - allowed)
    if extra:
        raise WorkflowError(
            f"{where}: unknown key(s) {extra}; allowed here are {sorted(allowed)}")


def _parse_nodes(raw_list: Any, where: str, *, depth: int = 0) -> tuple[Node, ...]:
    if not isinstance(raw_list, list) or not raw_list:
        raise WorkflowError(f"{where} must be a non-empty list")
    if depth > MAX_NEST_DEPTH:
        raise WorkflowError(
            f"{where}: branches nest deeper than {MAX_NEST_DEPTH}; a macro this "
            "deep is no longer one a person can read -- flatten it")
    nodes: list[Node] = []
    for i, raw in enumerate(raw_list):
        at = f"{where}[{i}]"
        if not isinstance(raw, dict):
            raise WorkflowError(f"{at} must be an object")
        is_leaf, is_branch = "tool" in raw, "when" in raw
        if is_leaf and is_branch:
            raise WorkflowError(
                f"{at} has both 'tool' and 'when'; a node is a step or a branch, "
                "not both")
        if is_branch:
            nodes.append(_parse_branch(raw, at, depth=depth))
        elif is_leaf:
            nodes.append(_parse_step(raw, at))
        else:
            raise WorkflowError(
                f"{at} needs a 'tool' (a step) or a 'when' (a branch)")
    return tuple(nodes)


def _parse_step(raw: dict, where: str) -> Step:
    _reject_unknown(where, raw, STEP_KEYS)
    if not isinstance(raw.get("tool"), str):
        raise WorkflowError(f"{where} needs a 'tool' name")
    return Step(
        tool=raw["tool"],
        args=dict(raw.get("args") or {}),
        expect=dict(raw.get("expect") or {}),
        expect_contains=dict(raw.get("expect_contains") or {}),
        expect_ok=bool(raw.get("expect_ok", True)),
        note=str(raw.get("note", "")),
        verified=bool(raw.get("verified", False)),
        delivery_only=bool(raw.get("delivery_only", False)),
    )


def _parse_branch(raw: dict, where: str, *, depth: int) -> Branch:
    _reject_unknown(where, raw, BRANCH_KEYS)
    if "then" not in raw:
        raise WorkflowError(f"{where}: a 'when' branch needs a 'then'")
    otherwise: tuple[Node, ...] = ()
    if raw.get("else") is not None:
        otherwise = _parse_nodes(raw["else"], f"{where}.else", depth=depth + 1)
    return Branch(
        when=_parse_guard(raw["when"], f"{where}.when"),
        then=_parse_nodes(raw["then"], f"{where}.then", depth=depth + 1),
        otherwise=otherwise,
        note=str(raw.get("note", "")),
    )


def _parse_guard(raw: Any, where: str) -> Guard:
    if not isinstance(raw, dict):
        raise WorkflowError(f"{where} must be an object naming a locator")
    _reject_unknown(where, raw, GUARD_KEYS)
    if not isinstance(raw.get("locator"), str):
        raise WorkflowError(f"{where} needs a 'locator' string")
    for flag in ("selected", "pressed"):
        if raw.get(flag) is not None and not isinstance(raw[flag], bool):
            raise WorkflowError(f"{where}: {flag!r} must be true or false")
    if "text" in raw and not isinstance(raw["text"], str):
        raise WorkflowError(f"{where}: 'text' must be a string")
    return Guard(
        locator=raw["locator"],
        text=raw.get("text"),
        selected=raw.get("selected"),
        pressed=raw.get("pressed"),
        absent=bool(raw.get("absent", False)),
        all_windows=bool(raw.get("all_windows", False)),
    )


def _parse_params(raw: Any) -> tuple[Param, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, dict):
        raise WorkflowError("'params' must be an object of name -> {required, note}")
    params: list[Param] = []
    for name, spec in raw.items():
        at = f"params.{name}"
        if not isinstance(spec, dict):
            raise WorkflowError(f"{at} must be an object")
        _reject_unknown(at, spec, PARAM_KEYS)
        params.append(Param(
            name=str(name),
            required=bool(spec.get("required", True)),
            note=str(spec.get("note", "")),
        ))
    return tuple(params)


def _parse_provenance(raw: Any) -> Provenance:
    if raw is None:
        return Provenance()
    if not isinstance(raw, dict):
        raise WorkflowError("'provenance' must be an object")
    _reject_unknown("provenance", raw, PROVENANCE_KEYS)
    revision = raw.get("revision", 0)
    if not isinstance(revision, int) or isinstance(revision, bool):
        raise WorkflowError("provenance.revision must be an integer")
    return Provenance(
        recorded_at=str(raw.get("recorded_at", "")),
        recorded_against=str(raw.get("recorded_against", "")),
        revision=revision,
    )


# --- assertions ------------------------------------------------------------

def dig(data: Any, path: str) -> tuple[bool, Any]:
    """Follow `path` ("values.0.text") into `data`; (found, value)."""
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                return False, None
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return False, None
        else:
            return False, None
    return True, current


def check(step: Step, result: Any) -> list[str]:
    """Every way `result` fails `step`'s expectations, as sentences."""
    failures: list[str] = []
    ok = isinstance(result, dict) and result.get("ok") is True
    if step.expect_ok and not ok:
        message = ""
        if isinstance(result, dict):
            message = (result.get("error") or {}).get("message", "")
        failures.append("the call did not succeed: " + (message or repr(result)))
    if not step.expect_ok and ok:
        failures.append("the call succeeded, and this step expected it to be refused")
    for path, wanted in step.expect.items():
        found, value = dig(result, path)
        if not found:
            failures.append(f"{path} is not in the result")
        elif value != wanted:
            failures.append(f"{path} is {value!r}, expected {wanted!r}")
    for path, fragment in step.expect_contains.items():
        found, value = dig(result, path)
        if not found:
            failures.append(f"{path} is not in the result")
        elif fragment not in str(value):
            failures.append(f"{path} is {value!r}, which does not contain {fragment!r}")
    return failures


# --- the run ---------------------------------------------------------------------

@dataclass
class StepReport:
    index: int
    tool: str
    args: dict[str, Any]
    ok: bool
    failures: list[str]
    elapsed_ms: int
    result: Any
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "index": self.index, "tool": self.tool, "args": self.args,
            "ok": self.ok, "failures": self.failures,
            "elapsed_ms": self.elapsed_ms, "note": self.note,
            "result": _trimmed(self.result),
        }


@dataclass
class RunReport:
    workflow: str
    pid: int
    started_at: float
    verdict: str = "not_run"
    steps: list[StepReport] = field(default_factory=list)
    interference: list[dict] = field(default_factory=list)
    watchdog_events: list[dict] = field(default_factory=list)
    attach: dict = field(default_factory=dict)
    release: dict = field(default_factory=dict)
    error: str = ""
    finished_at: float = 0.0

    @property
    def passed(self) -> bool:
        return self.verdict == "passed"

    def to_dict(self) -> dict:
        return {
            "workflow": self.workflow, "pid": self.pid,
            "verdict": self.verdict, "error": self.error,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "steps": [s.to_dict() for s in self.steps],
            "interference": self.interference,
            "watchdog_events": self.watchdog_events,
            "attach": _trimmed(self.attach), "release": _trimmed(self.release),
        }


def _trimmed(value: Any) -> Any:
    """A result with its pixels left out: a report is for reading."""
    if isinstance(value, dict):
        return {k: ("<png omitted>" if k == "base64" else _trimmed(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_trimmed(v) for v in value]
    return value


class Watch(Protocol):
    """What the runner needs from an interference watch: start, stop, events."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def events(self) -> list[dict]:
        return []


def run_workflow(
    box: Any,
    workflow: Workflow,
    *,
    pid: int,
    watch: Watch | None = None,
    profile_path: str | None = None,
    now: Callable[[], float] = time.time,
    clock: Callable[[], float] = time.monotonic,
) -> RunReport:
    """Attach, run every step until one fails, release, report.

    `box` is a Toolbox (or anything with the same tools). Consent for `pid`
    is the operator's, expressed by running the workflow: it is recorded as
    an operator-tool grant with the workflow's name, so the record says
    why this target was automated.
    """
    from .policy import ConsentSource

    report = RunReport(workflow=workflow.name, pid=pid, started_at=now())
    if watch is not None:
        watch.start()
    session = None
    try:
        box.sessions.record_grant(
            pid, allowed=True, source=ConsentSource.OPERATOR_TOOL,
            note=f"workflow {workflow.name!r} run by the operator")
        attached = box.attach(pid, tier=workflow.tier, profile_path=profile_path,
                              isolation=workflow.isolation)
        report.attach = attached
        if not attached.get("ok"):
            report.verdict = "failed"
            report.error = "attach failed: " + str(
                (attached.get("error") or {}).get("message", attached))
            return report
        session = attached["session_id"]

        for index, step in enumerate(workflow.steps):
            if isinstance(step, Branch):
                # The format holds branches (#84); executing them is the macro
                # runner's job (#85). This linear runner fails clean rather
                # than pretend, so a branch reaching it is a plain error.
                report.steps.append(StepReport(
                    index, "when", {}, False,
                    ["a 'when' branch needs the macro runner (#85); this "
                     "runner executes linear steps only"], 0, None, step.note))
                report.verdict = "failed"
                break
            tool = getattr(box, step.tool, None)
            if tool is None or step.tool.startswith("_") or step.tool == "release":
                report.steps.append(StepReport(
                    index, step.tool, step.args, False,
                    [f"no such tool: {step.tool!r}"], 0, None, step.note))
                report.verdict = "failed"
                break
            started = clock()
            try:
                result = tool(session, **step.args)
            except TypeError as exc:
                result = {"ok": False, "error": {"kind": "not_actionable",
                                                 "message": f"bad arguments: {exc}"}}
            elapsed = int((clock() - started) * 1000)
            if isinstance(result, dict) and result.get("watchdog_events"):
                report.watchdog_events.extend(result["watchdog_events"])
            failures = check(step, result)
            report.steps.append(StepReport(
                index, step.tool, step.args, not failures, failures,
                elapsed, result, step.note))
            if failures:
                report.verdict = "failed"
                break
        else:
            report.verdict = "passed"
    except Exception as exc:
        report.verdict = "failed"
        report.error = f"{type(exc).__name__}: {exc}"
    finally:
        if session is not None:
            try:
                report.release = box.release(session)
                if report.release.get("watchdog_events"):
                    report.watchdog_events.extend(report.release["watchdog_events"])
            except Exception as exc:
                report.release = {"ok": False, "error": str(exc)}
        if watch is not None:
            watch.stop()
            report.interference = watch.events()
            if any(e.get("kind") == "foreground_taken" for e in report.interference):
                report.verdict = "failed"
                report.error = (report.error + "; " if report.error else "") + \
                    "the target took the foreground during the run"
        report.finished_at = now()
    return report
