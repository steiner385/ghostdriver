"""Run a sequence of session tools in one call (D#75).

A hybrid loop is mostly deterministic -- click a tab, set a field, press
Ok, click a row, embed, save -- and each of those steps used to cost a
round trip. `batch` runs a list of them in one call, each carrying its own
`expect`, stopping on the first that does not verify, and reports every
step's verdict.

**It is only a dispatcher.** Each step calls the same Toolbox method a
standalone call would, so it passes the identical `authorize`, denylist and
tier checks -- the batch adds no path around any of them, and grants nothing
a step could not already do. That is why the set of batchable tools is an
allowlist of the session-scoped read-and-act tools, and never the lifecycle
or consent tools (`attach`, `release`, `grant_*`, `launch_isolated`) or the
two that interrupt a person (`foreground`, `await_human`): a batch drives an
already-approved target, it does not change what is approved or wait on a
human.

**Stop on first failure, by default.** A loop's steps depend on each other
-- there is no point pressing Ok on a dialog that never opened -- so a step
whose result is not `ok` stops the batch and the ones after it do not run.
`stop_on_failure=false` runs them all regardless, for a batch of independent
reads. Either way the result says how far it got and carries each step's
verdict, so a failure is located, not just reported.
"""

from ..model.result import ErrorKind, GhostdriverError
from .core import _error, _ToolboxCore

#: The tools a batch may run: session-scoped, and either reading the target
#: or acting on it under the tier ladder. Deliberately an allowlist -- a new
#: tool is not batchable until it is named here, so nothing that changes
#: what is approved or takes the foreground can be reached through a batch.
BATCHABLE = frozenset({
    "click", "set_value", "type_text", "send_keys",
    "find", "read", "read_clipboard", "capture", "describe",
    "modals", "surfaces", "hit_targets", "wait_for", "wait_idle",
    "grid_seek",
})

#: Fields worth keeping from a step's result. A batch reports verdicts, not
#: whole payloads -- a `find`'s element list or a `capture`'s pixels stay
#: with the standalone call. The image a `capture` step would return cannot
#: ride in a JSON batch result anyway, so its dimensions and `saved_to` are
#: kept and the base64 is dropped.
_STEP_FIELDS = (
    "verified", "delivered_to", "hit_container", "warning", "still_arriving",
    "expected", "match_count", "found", "value", "empty", "length", "idle",
    "polls", "row_count", "reached_end", "advanced", "saved_to", "took_foreground",
    "width", "height", "total", "blocked",
)


def _step_summary(index: int, tool: str, result: dict) -> dict:
    """One step's line in the batch result: what it was and how it went."""
    out: dict = {"i": index, "tool": tool, "ok": bool(result.get("ok"))}
    for key in _STEP_FIELDS:
        if key in result and key != "base64":
            out[key] = result[key]
    if not result.get("ok") and result.get("error"):
        out["error"] = result["error"]
    return out


class BatchTools(_ToolboxCore):
    """Run several session tools in one call, each with its own expect."""

    def batch(self, session_id: str, steps: list, *,
              stop_on_failure: bool = True) -> dict:
        """Run `steps` in order against one session.

        Each step is `{tool, args}`: `tool` is one of the batchable tools
        (the session-scoped read-and-act set), `args` its keyword arguments
        *without* `session_id`, which the batch supplies. A step carries its
        own `expect`, so its verdict is real, not "sent". The first step that
        does not verify stops the batch unless `stop_on_failure` is false.
        """
        try:
            self.sessions.authorize(session_id, "batch")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)

        if not isinstance(steps, list) or not steps:
            return _error(ErrorKind.NOT_ACTIONABLE,
                          "steps must be a non-empty list of {tool, args}")

        ran: list[dict] = []
        stopped_at: int | None = None
        all_ok = True

        for index, step in enumerate(steps):
            if not isinstance(step, dict) or "tool" not in step:
                return _error(ErrorKind.NOT_ACTIONABLE,
                              f"step {index} must be an object with a 'tool' key; "
                              f"got {step!r}")
            tool = step["tool"]
            args = step.get("args") or {}
            if not isinstance(args, dict):
                return _error(ErrorKind.NOT_ACTIONABLE,
                              f"step {index}: args must be an object, not {type(args).__name__}")
            if "session_id" in args or "session_ref" in args:
                return _error(ErrorKind.NOT_ACTIONABLE,
                              f"step {index}: omit the session in a step; the batch "
                              "runs every step against its own session")
            if tool not in BATCHABLE:
                return _error(
                    ErrorKind.NOT_ACTIONABLE,
                    f"step {index}: {tool!r} cannot run in a batch. Batchable "
                    f"tools are {sorted(BATCHABLE)}. Lifecycle and consent tools "
                    "(attach, release, grant_*, launch_isolated) and the two that "
                    "interrupt a person (foreground, await_human) run on their own.")

            method = getattr(self, tool)
            try:
                result = method(session_id, **args)
            except TypeError as exc:
                # Bad arguments for that tool: a step failure, not a batch
                # crash, so it obeys stop_on_failure like any other.
                result = _error(ErrorKind.NOT_ACTIONABLE,
                                f"{tool}: bad arguments -- {exc}")

            ran.append(_step_summary(index, tool, result))
            if not result.get("ok"):
                all_ok = False
                if stop_on_failure:
                    stopped_at = index
                    break

        return {
            "ok": all_ok,
            "completed": len(ran),
            "total": len(steps),
            "stopped_at": stopped_at,
            "steps": ran,
        }
