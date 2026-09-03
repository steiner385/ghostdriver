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


@dataclass(frozen=True)
class Workflow:
    name: str
    steps: tuple[Step, ...]
    tier: str = "read_only"
    isolation: str = "none"
    profile: str | None = None
    description: str = ""

    @classmethod
    def load(cls, path: Path) -> "Workflow":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkflowError(f"cannot read workflow {path}: {exc}") from exc
        return cls.from_dict(data, default_name=path.stem)

    @classmethod
    def from_dict(cls, data: dict, *, default_name: str = "") -> "Workflow":
        if not isinstance(data, dict):
            raise WorkflowError("a workflow is a JSON object")
        raw_steps = data.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise WorkflowError("a workflow needs a non-empty 'steps' list")
        steps = []
        for i, raw in enumerate(raw_steps):
            if not isinstance(raw, dict) or not isinstance(raw.get("tool"), str):
                raise WorkflowError(f"step {i} needs a 'tool' name")
            steps.append(Step(
                tool=raw["tool"],
                args=dict(raw.get("args") or {}),
                expect=dict(raw.get("expect") or {}),
                expect_contains=dict(raw.get("expect_contains") or {}),
                expect_ok=bool(raw.get("expect_ok", True)),
                note=str(raw.get("note", "")),
            ))
        return cls(
            name=str(data.get("name") or default_name or "workflow"),
            steps=tuple(steps),
            tier=str(data.get("tier", "read_only")),
            isolation=str(data.get("isolation", "none")),
            profile=data.get("profile"),
            description=str(data.get("description", "")),
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
