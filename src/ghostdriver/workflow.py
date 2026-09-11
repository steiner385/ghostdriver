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
import re
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


@dataclass(frozen=True)
class RepeatUntil:
    """Run `do` while `until` does NOT hold, checked *before* each iteration
    (so an already-satisfied condition runs it zero times), up to `max`
    times. A macro cannot spin: `max` is required and capped (v2, #97)."""
    until: Guard
    do: tuple[Node, ...]
    max: int
    note: str = ""


@dataclass(frozen=True)
class ForEach:
    """Run `do` once per item in `items`, binding `var` -- referenced as
    ${var} in the arm's args. `items` is a list, or a ${param} that binds to
    one at run time (v2, #97)."""
    var: str
    items: Any
    do: tuple[Node, ...]
    note: str = ""


@dataclass(frozen=True)
class Handler:
    """React to a UI disturbance the operator named (v3, #106). `window` is a
    locator for the window whose appearance triggers `handle` -- ordinary
    macro steps, run through the same checks any leaf gets. `then` is 'retry'
    (re-run the interrupted step) or 'continue'. Bounded: `max` firings, past
    which the run stops rather than react in a loop. A handler is authored,
    never a wildcard, never learned."""
    window: str
    handle: tuple[Node, ...]
    then: str = "continue"
    max: int = 3


#: A node in a macro body is a leaf step, a branch, or a loop. The tree is
#: recursive: an arm or a loop body is itself a list of nodes. A Handler is not
#: a node -- it is declared for the whole run, and its `handle` is nodes.
Node = Step | Branch | RepeatUntil | ForEach

#: The keys each control-flow node may carry (loops, #97).
REPEAT_KEYS = frozenset({"repeat_until", "max", "do", "note"})
FOREACH_KEYS = frozenset({"for_each", "in", "do", "note"})

#: How deep branches and loops may nest. A bound keeps a macro something a
#: person can still read at a glance, the same instinct as `pace`'s cap (D#76).
MAX_NEST_DEPTH = 8

#: The hard ceiling on any one loop, so `max` cannot be set absurdly and a
#: for_each cannot be handed a runaway list. A loop is a convenience, not a
#: place to park a run (D#76).
MAX_ITERATIONS = 1000

#: The keys a reactive handler and its trigger may carry (#106).
HANDLER_KEYS = frozenset({"on_disturbance", "handle", "then", "max"})
ON_DISTURBANCE_KEYS = frozenset({"window"})

#: The hard ceiling on how many times one handler may fire in a run, so a
#: disturbance that keeps recurring stops the run with a reason rather than
#: dismiss-and-retry forever.
MAX_HANDLER_FIRINGS = 20


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
    #: Reactive handlers, active for the whole run (#106). Declared at the top
    #: level, not inline in steps, because a handler is a property of the run,
    #: not a point in it.
    handlers: tuple[Handler, ...] = ()

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
            handlers=_parse_handlers(data.get("handlers")),
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
        kinds = [k for k in ("tool", "when", "repeat_until", "for_each")
                 if k in raw]
        if len(kinds) != 1:
            raise WorkflowError(
                f"{at} must be exactly one of a step ('tool'), a branch "
                "('when'), or a loop ('repeat_until' / 'for_each'); it has "
                f"{sorted(kinds) or 'none of them'}")
        kind = kinds[0]
        if kind == "tool":
            nodes.append(_parse_step(raw, at))
        elif kind == "when":
            nodes.append(_parse_branch(raw, at, depth=depth))
        elif kind == "repeat_until":
            nodes.append(_parse_repeat(raw, at, depth=depth))
        else:
            nodes.append(_parse_foreach(raw, at, depth=depth))
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


def _parse_repeat(raw: dict, where: str, *, depth: int) -> RepeatUntil:
    _reject_unknown(where, raw, REPEAT_KEYS)
    if "do" not in raw:
        raise WorkflowError(f"{where}: a 'repeat_until' loop needs a 'do'")
    max_raw = raw.get("max")
    if not isinstance(max_raw, int) or isinstance(max_raw, bool) or max_raw < 1:
        raise WorkflowError(
            f"{where}: a loop needs 'max', a positive integer bound on its "
            "iterations, so it cannot spin")
    if max_raw > MAX_ITERATIONS:
        raise WorkflowError(
            f"{where}: max {max_raw} exceeds the {MAX_ITERATIONS} ceiling on a loop")
    return RepeatUntil(
        until=_parse_guard(raw["repeat_until"], f"{where}.repeat_until"),
        do=_parse_nodes(raw["do"], f"{where}.do", depth=depth + 1),
        max=max_raw,
        note=str(raw.get("note", "")),
    )


def _parse_foreach(raw: dict, where: str, *, depth: int) -> ForEach:
    _reject_unknown(where, raw, FOREACH_KEYS)
    var = raw.get("for_each")
    if not isinstance(var, str) or not var.isidentifier():
        raise WorkflowError(
            f"{where}: 'for_each' names the loop variable, an identifier like "
            f"'row'; got {var!r}")
    if "in" not in raw:
        raise WorkflowError(f"{where}: a 'for_each' loop needs an 'in' -- a list "
                            "or a ${param} that binds to one")
    items = raw["in"]
    if not isinstance(items, (list, str)):
        raise WorkflowError(
            f"{where}: 'in' must be a list or a ${{param}} string, not "
            f"{type(items).__name__}")
    if "do" not in raw:
        raise WorkflowError(f"{where}: a 'for_each' loop needs a 'do'")
    return ForEach(
        var=var,
        items=list(items) if isinstance(items, list) else items,
        do=_parse_nodes(raw["do"], f"{where}.do", depth=depth + 1),
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


def _parse_handlers(raw: Any) -> tuple[Handler, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise WorkflowError("'handlers' must be a list of on_disturbance handlers")
    handlers: list[Handler] = []
    for i, item in enumerate(raw):
        where = f"handlers[{i}]"
        if not isinstance(item, dict):
            raise WorkflowError(f"{where} must be an object")
        _reject_unknown(where, item, HANDLER_KEYS)
        trigger = item.get("on_disturbance")
        if not isinstance(trigger, dict):
            raise WorkflowError(
                f"{where}: 'on_disturbance' names the window to react to")
        _reject_unknown(f"{where}.on_disturbance", trigger, ON_DISTURBANCE_KEYS)
        window = trigger.get("window")
        if (not isinstance(window, str) or not window.strip()
                or window.strip() in ("*", "class=*")):
            raise WorkflowError(
                f"{where}: on_disturbance.window must name a specific window "
                "(a class locator), never a wildcard -- a handler reacts to a "
                "case the operator named, not to anything that appears")
        if "handle" not in item:
            raise WorkflowError(
                f"{where}: a handler needs a 'handle' -- the steps to run")
        then = item.get("then", "continue")
        if then not in ("continue", "retry"):
            raise WorkflowError(
                f"{where}: 'then' is 'continue' or 'retry', not {then!r}")
        max_raw = item.get("max", 3)
        if not isinstance(max_raw, int) or isinstance(max_raw, bool) or max_raw < 1:
            raise WorkflowError(f"{where}: 'max' must be a positive integer")
        if max_raw > MAX_HANDLER_FIRINGS:
            raise WorkflowError(
                f"{where}: max {max_raw} exceeds the {MAX_HANDLER_FIRINGS} "
                "ceiling on handler firings")
        handlers.append(Handler(
            window=window,
            handle=_parse_nodes(item["handle"], f"{where}.handle"),
            then=then, max=max_raw))
    return tuple(handlers)


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


# --- the macro runner: params and branches (#85) ---------------------------

#: ${name} -- a parameter reference in a step's args or a guard's locator.
_PARAM_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _substitute(value: Any, bindings: dict[str, Any], unresolved: list[str]) -> Any:
    """Replace ${name} in `value` from `bindings`, recursing into dicts/lists.

    A value that is *exactly* ``${name}`` keeps the binding's type -- an int
    stays an int, a dict stays a dict -- so ``at: {x: ${x}}`` binds a number.
    Embedded in a larger string it interpolates as text. A name with no
    binding is collected in `unresolved` and left untouched, so the caller can
    refuse rather than guess (D33).
    """
    if isinstance(value, str):
        whole = _PARAM_RE.fullmatch(value)
        if whole:
            name = whole.group(1)
            if name in bindings:
                return bindings[name]
            unresolved.append(name)
            return value

        def repl(match: re.Match[str]) -> str:
            name = match.group(1)
            if name in bindings:
                return str(bindings[name])
            unresolved.append(name)
            return match.group(0)

        return _PARAM_RE.sub(repl, value)
    if isinstance(value, dict):
        return {k: _substitute(v, bindings, unresolved) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, bindings, unresolved) for v in value]
    return value


def bind(value: Any, bindings: dict[str, Any]) -> tuple[Any, list[str]]:
    """`value` with its ${name}s bound, and the names that had no binding."""
    unresolved: list[str] = []
    return _substitute(value, bindings, unresolved), sorted(set(unresolved))


def missing_required(params: tuple[Param, ...], bindings: dict[str, Any]) -> list[str]:
    """Required params with no binding. An unbound required param is refused,
    not guessed (D33)."""
    return [p.name for p in params if p.required and p.name not in bindings]


def _guard_holds(box: Any, session_id: str, guard: Guard,
                 bindings: dict[str, Any]) -> tuple[bool | None, str | None]:
    """Whether a branch condition holds, read from the target. `(holds, error)`
    -- error is set when the condition could not be evaluated (an unbound
    locator param, a failed read, or a state the target does not expose yet),
    and the caller refuses rather than branch on a guess.

    Presence/absence is `find`'s match count; `text`, `selected` and `pressed`
    refine a present match. `pressed` depends on a readable toggle state
    (#77); until a control exposes it, a `pressed` guard is unevaluable and
    says so rather than silently reading false.
    """
    locator, unbound = bind(guard.locator, bindings)
    if unbound:
        return None, f"the condition's locator has unbound param(s) {unbound}"
    found = box.find(session_id, locator, all_windows=guard.all_windows)
    if not found.get("ok"):
        return None, ("could not evaluate the condition: "
                      + str((found.get("error") or {}).get("message", found)))
    elements = found.get("elements") or []
    if guard.absent:
        return len(elements) == 0, None
    if not elements:
        return False, None

    holds = True
    for key, wanted, label in (("text", guard.text, "text"),
                               ("selected", guard.selected, "selected state"),
                               ("pressed", guard.pressed, "pressed state")):
        if wanted is None:
            continue
        readable = [e for e in elements if key in e]
        if not readable:
            hint = " yet (#77)" if key == "pressed" else ""
            return None, f"cannot read the {label} of the matched control{hint}"
        holds = holds and any(e.get(key) == wanted for e in readable)
    return holds, None


@dataclass
class MacroStep:
    """One leaf's outcome in a macro run. `path` locates it in the tree
    ("0", "1.then.0"), so a failure in a branch is placed exactly."""
    path: str
    tool: str
    ok: bool
    failures: list[str]
    #: Static flags, copied from the macro file: whether the step's expect
    #: held *when recorded*, and whether it is an offset click (D#84).
    verified: bool = False
    delivery_only: bool = False
    #: The runtime verdict: did this step's own postcondition hold on *this*
    #: run? Distinct from `verified` so a reader can tell "confirmed when
    #: recorded" from "confirmed just now" -- a hand-authored step is never
    #: `verified` in the file but can still hold every time it runs (#112).
    held: bool = False

    def to_dict(self) -> dict:
        return {"path": self.path, "tool": self.tool, "ok": self.ok,
                "failures": self.failures, "verified": self.verified,
                "delivery_only": self.delivery_only, "held": self.held}


def run_macro_body(
    box: Any,
    session_id: str,
    nodes: tuple[Node, ...],
    bindings: dict[str, Any],
    *,
    context: str = "macro",
    stop_on_failure: bool = True,
    handlers: tuple[Handler, ...] = (),
) -> dict:
    """Walk a macro body against one session: substitute params, evaluate
    `when` branches, and dispatch each leaf through the shared allowlist (#83).

    Returns `{ok, completed, steps, refused, stopped_at}`. A withheld tool, an
    unbound param, or an unevaluable condition **refuses the whole run**
    (`refused` set) -- those are macro-authoring or binding errors, and the
    honest response is to stop, not to run half a macro on a guess (D33). A
    leaf whose assertions fail is an ordinary step failure that stops the run
    when `stop_on_failure`. This is the evaluation core; `macro_replay` (#87)
    wraps it with attach, the interference watch, and the report.
    """
    from .tools.recording import held_on_this_run
    from .tools.stepper import call_tool, step_refusal

    records: list[MacroStep] = []
    state: dict[str, Any] = {"stopped": False, "refused": None, "in_handler": False}
    handler_counts: dict[int, int] = {}

    #: The actuations a declared disturbance is checked after: a dialog appears
    #: in response to an action, not a read.
    _ACTUATIONS = frozenset({"click", "set_value", "type_text", "send_keys"})

    def stopping() -> bool:
        return bool(state["stopped"] or state["refused"])

    def react(tool: str, step_path: str, bindings: dict[str, Any]) -> str | None:
        """After an actuation, run the first declared handler whose window is
        present, and return its `then` ('retry'/'continue'), or None. A
        handler's own steps do not re-trigger handlers (`in_handler`), so the
        reaction cannot recurse; each handler's `max` firings bound it, past
        which the run stops rather than loop."""
        if not handlers or tool not in _ACTUATIONS or state["in_handler"]:
            return None
        for index, handler in enumerate(handlers):
            found = box.find(session_id, handler.window, all_windows=True)
            if not found.get("ok") or (found.get("match_count") or 0) < 1:
                continue
            handler_counts[index] = handler_counts.get(index, 0) + 1
            if handler_counts[index] > handler.max:
                state["refused"] = (
                    f"{step_path}: the handler for {handler.window!r} has fired "
                    f"{handler.max} times and the disturbance is still there; "
                    "stopping rather than react in a loop")
                return None
            records.append(MacroStep(
                f"{step_path}.on_disturbance[{index}]", "on_disturbance",
                True, [], False, False))
            state["in_handler"] = True
            try:
                walk(handler.handle, f"{step_path}.handle.", bindings)
            finally:
                state["in_handler"] = False
            if stopping():
                return None
            return handler.then
        return None

    def walk(nodes: tuple[Node, ...], path: str, bindings: dict[str, Any]) -> None:
        for i, node in enumerate(nodes):
            if stopping():
                return
            at = f"{path}{i}"
            if isinstance(node, Branch):
                holds, err = _guard_holds(box, session_id, node.when, bindings)
                if err is not None:
                    state["refused"] = f"{at}.when: {err}"
                    return
                arm, label = (node.then, "then") if holds else (node.otherwise, "else")
                walk(arm, f"{at}.{label}.", bindings)
                continue
            if isinstance(node, RepeatUntil):
                _run_repeat(node, at, bindings)
                continue
            if isinstance(node, ForEach):
                _run_foreach(node, at, bindings)
                continue

            bound_args, unbound = bind(node.args, bindings)
            if unbound:
                state["refused"] = (
                    f"{at}: unbound param(s) {unbound}; bind them at replay or fix "
                    "the macro -- refused, not guessed")
                return
            refusal = step_refusal(at, node.tool, bound_args, context=context)
            if refusal is not None:
                state["refused"] = refusal
                return
            attempt = 0
            while True:
                attempt += 1
                step_path = at if attempt == 1 else f"{at}.retry[{attempt - 1}]"
                result = call_tool(box, session_id, node.tool, bound_args)
                failures = check(node, result)
                records.append(MacroStep(step_path, node.tool, not failures,
                                         failures, node.verified, node.delivery_only,
                                         held=held_on_this_run(node.tool, result)))
                if failures and stop_on_failure:
                    state["stopped"] = True
                    return
                if react(node.tool, step_path, bindings) == "retry":
                    if stopping():
                        return
                    continue
                if stopping():
                    return
                break

    def _run_repeat(node: RepeatUntil, at: str, bindings: dict[str, Any]) -> None:
        # Check before each iteration: an already-satisfied condition runs the
        # body zero times, and a run that reaches `max` without the condition
        # holding is a failure -- the loop did not achieve what it named -- not
        # a silent stop.
        for iteration in range(node.max):
            holds, err = _guard_holds(box, session_id, node.until, bindings)
            if err is not None:
                state["refused"] = f"{at}.repeat_until: {err}"
                return
            if holds:
                return
            walk(node.do, f"{at}.repeat[{iteration}].", bindings)
            if stopping():
                return
        records.append(MacroStep(
            f"{at}.repeat_until", "repeat_until", False,
            [f"the condition never held after {node.max} iterations"], False, False))
        if stop_on_failure:
            state["stopped"] = True

    def _run_foreach(node: ForEach, at: str, bindings: dict[str, Any]) -> None:
        items = node.items
        if isinstance(items, str):
            items, unbound = bind(items, bindings)
            if unbound:
                state["refused"] = (
                    f"{at}.for_each: unbound param(s) {unbound} in 'in'; a "
                    "for_each iterates a bound list")
                return
        if not isinstance(items, list):
            state["refused"] = (
                f"{at}.for_each: 'in' resolved to {type(items).__name__}, not a "
                "list; a for_each iterates a list")
            return
        if len(items) > MAX_ITERATIONS:
            state["refused"] = (
                f"{at}.for_each: {len(items)} items exceeds the {MAX_ITERATIONS} "
                "ceiling on a loop")
            return
        for j, item in enumerate(items):
            walk(node.do, f"{at}.each[{j}].", {**bindings, node.var: item})
            if stopping():
                return

    walk(nodes, "", bindings)
    stopped_at = None
    if state["stopped"]:
        stopped_at = next((r.path for r in records if not r.ok), None)
    return {
        "ok": state["refused"] is None and all(r.ok for r in records),
        "completed": len(records),
        "steps": [r.to_dict() for r in records],
        "refused": state["refused"],
        "stopped_at": stopped_at,
    }


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
            if isinstance(step, (Branch, RepeatUntil, ForEach)):
                # The format holds branches and loops (#84, #97); executing
                # them is the macro runner's job (run_macro_body). This linear
                # runner fails clean rather than pretend, so control flow
                # reaching it is a plain error.
                report.steps.append(StepReport(
                    index, "control-flow", {}, False,
                    ["a branch or loop needs the macro runner (run_macro_body); "
                     "this runner executes linear steps only"], 0, None, step.note))
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
