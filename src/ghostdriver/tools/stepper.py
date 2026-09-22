"""The shared execution core: run a list of tool-call steps against a
toolbox, under the allowlist, per-step tier, and stop-on-failure (D#83).

Factored out of `batch` (D#75) so the batch tool and the macro runner (#87)
enforce one safety model from one place. The principle both rely on: every
step is an ordinary tool call that re-authorizes, re-checks the denylist,
refuses ambiguity and enforces its own tier -- this core adds sequencing,
never a way around any of that. It never authorizes anything itself; the
caller has already authorized *itself* (the `batch` tool, the `macro_replay`
tool), and each step's own tool method authorizes the session again.

Pure with respect to the desktop: it calls methods on a toolbox handed in,
so it is tested with a fake toolbox and needs no fixture.
"""

from ..model.result import ErrorKind
from .core import _error

#: The tools a step may run: session-scoped, and either reading the target
#: or acting on it under the tier ladder. Deliberately an allowlist -- a new
#: tool is not runnable in a batch or a macro until it is named here, so
#: nothing that changes what is approved or takes the foreground can be
#: reached through the core.
RUNNABLE_TOOLS = frozenset({
    "click", "set_value", "type_text", "send_keys",
    "find", "read", "read_clipboard", "capture", "describe",
    "modals", "surfaces", "hit_targets", "wait_for", "wait_idle",
    "grid_seek",
    # A fixed dwell between steps (#119): click, settle, capture used to be
    # three round trips because pace was withheld. It changes nothing on the
    # target and names the guess it is (D#76), so it rides in a batch or a
    # macro like any read.
    "pace",
})

#: Fields worth keeping from a step's result. The core reports verdicts, not
#: whole payloads -- a `find`'s element list or a `capture`'s pixels stay
#: with the standalone call. The image a `capture` step would return cannot
#: ride in a JSON result anyway, so its dimensions and `saved_to` are kept
#: and the base64 is dropped.
_STEP_FIELDS = (
    "verified", "delivered_to", "hit_container", "warning", "still_arriving",
    "expected", "match_count", "found", "value", "empty", "length", "idle",
    "polls", "row_count", "reached_end", "advanced", "saved_to", "took_foreground",
    "width", "height", "total", "blocked",
    # What changed around the step, by name -- a window that vanished, the
    # target unblocked. Dropped once, so a typed value that dismissed its
    # dialog reported only "2 other change(s)" and nothing to act on (#117).
    "disturbances", "live_aborted",
    # A seek whose copy route failed says so on its step line too (#182).
    "copies_failed", "copy_stopped",
)


#: How many capture images one batch result carries. Each is a couple of
#: thousand tokens as an image block; a loop that captures every step
#: would otherwise return a wall of pictures (#197).
MAX_BATCH_IMAGES = 4


def step_summary(index: int, tool: str, result: dict) -> dict:
    """One step's line in the run result: what it was and how it went."""
    out: dict = {"i": index, "tool": tool, "ok": bool(result.get("ok"))}
    for key in _STEP_FIELDS:
        if key in result and key != "base64":
            out[key] = result[key]
    if not result.get("ok") and result.get("error"):
        out["error"] = result["error"]
    return out


def step_refusal(where: str, tool: str, args, *, context: str = "batch") -> str | None:
    """Why a step may not run at all, or None if it may -- the shared gate for
    a batch and a macro. `where` labels the step in the message ("step 3",
    "1.then.0"). A withheld tool or a step carrying its own session is refused;
    the caller aborts the whole run on a non-None return, since a run that
    would reach a withheld tool is malformed, not half-runnable.
    """
    if not isinstance(args, dict):
        return f"{where}: args must be an object, not {type(args).__name__}"
    if "session_id" in args or "session_ref" in args:
        return (f"{where}: omit the session in a step; the {context} runs every "
                "step against its own session")
    if tool not in RUNNABLE_TOOLS:
        return (f"{where}: {tool!r} cannot run in a {context}. Tools that can run "
                f"in a {context} are {sorted(RUNNABLE_TOOLS)}. Lifecycle and "
                "consent tools (attach, release, grant_*, launch_isolated) and the "
                "two that interrupt a person (foreground, await_human) run on "
                "their own.")
    return None


def call_tool(toolbox, session_id: str, tool: str, args: dict) -> dict:
    """Dispatch one already-validated tool call. A `TypeError` from bad
    arguments becomes a step-failure result rather than a crash, so it obeys
    stop-on-failure like any other outcome."""
    method = getattr(toolbox, tool)
    try:
        return method(session_id, **args)
    except TypeError as exc:
        return _error(ErrorKind.NOT_ACTIONABLE, f"{tool}: bad arguments -- {exc}")


def run_steps(toolbox, session_id: str, steps, *, stop_on_failure: bool = True,
              context: str = "batch") -> dict:
    """Run `steps` in order against one session on `toolbox`.

    `toolbox` is the object whose methods are the tools (the Toolbox). Each
    step is `{tool, args}`: `tool` is one of `RUNNABLE_TOOLS`, `args` its
    keyword arguments *without* a session, which this supplies from
    `session_id`. Returns `{ok, completed, total, stopped_at, steps}`; a step
    whose result is not `ok` stops the run when `stop_on_failure`.

    Returns a top-level error dict (`ok: false`, `error`) for a malformed
    `steps` list, or a step that names a tool the allowlist withholds -- the
    run is refused rather than half-done. `context` names the caller ("batch",
    "macro") only for the wording of those refusals.
    """
    if not isinstance(steps, list) or not steps:
        return _error(ErrorKind.NOT_ACTIONABLE,
                      "steps must be a non-empty list of {tool, args}")

    ran: list[dict] = []
    images: list[dict] = []
    stopped_at: int | None = None
    all_ok = True

    for index, step in enumerate(steps):
        if not isinstance(step, dict) or "tool" not in step:
            return _error(ErrorKind.NOT_ACTIONABLE,
                          f"step {index} must be an object with a 'tool' key; "
                          f"got {step!r}")
        tool = step["tool"]
        args = step.get("args") or {}
        refusal = step_refusal(f"step {index}", tool, args, context=context)
        if refusal is not None:
            return _error(ErrorKind.NOT_ACTIONABLE, refusal)

        result = call_tool(toolbox, session_id, tool, args)
        line = step_summary(index, tool, result)
        if tool == "capture" and result.get("ok") and result.get("base64"):
            # The pixels cannot ride on a JSON step line, and used to be
            # dropped outright, so every capture in a batch had to be
            # re-issued standalone (#197). They ride beside the result
            # instead, for the protocol layer to return as image blocks.
            if len(images) < MAX_BATCH_IMAGES:
                images.append({"step": index, "base64": result["base64"],
                               "width": result.get("width"), "height": result.get("height")})
                line["image"] = "attached"
            else:
                line["image"] = (f"dropped: a batch carries at most {MAX_BATCH_IMAGES} "
                                 "images; capture it standalone")
        ran.append(line)
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
        **({"images": images} if images else {}),
        "steps": ran,
    }
