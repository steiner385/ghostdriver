"""Turning a live tool call into a recorded macro step (#88).

A session that is recording (`record_start`) buffers its actuations as macro
steps as they happen, so a sequence a person worked out by hand can be saved
and replayed. The honesty is structural: a step carries whether it was
*verified* (its `expect` held) or only *delivered* (an offset click on a
painted region, or an actuation with no postcondition), so a recorded macro
cannot pass off a blind click as a confirmed one (D66).

Only the doing is recorded -- the actuations and the waits, not the reads the
agent used to decide -- so a recording is the macro, not the exploration
around it. And only a call that *succeeded*: a `set_value` into a protected
field is already refused (it never returns ok), so a typed secret is never
buffered, and the credential path stays `await_human`, which never carries
the value.
"""

#: The tools a recording captures: the session-scoped actuations, plus the
#: two waits (a wait that returned ok is its own verification -- the
#: condition held). Reads are exploration, not macro steps.
RECORDABLE = frozenset({"click", "set_value", "type_text", "send_keys",
                        "wait_for", "wait_idle"})

#: `verified` verdicts: the action's own postcondition held.
_VERIFIED = frozenset({"effect", "committed", "display"})
#: `delivered` verdicts: the input went out, unconfirmed.
_DELIVERED = frozenset({"delivery_only", "delivered_inactive"})


def capture_step(tool: str, bound: dict, result: dict) -> dict | None:
    """A macro step for this call, or None if it is not one to record.

    `bound` is the call's arguments (the session stripped); `result` its
    outcome. Returns None for a non-recordable tool or a call that did not
    succeed -- so nothing a person did not actually accomplish, and no
    refused secret, ever lands in a macro.
    """
    if tool not in RECORDABLE or not result.get("ok"):
        return None
    args = {k: v for k, v in bound.items()
            if k not in ("session_id", "session_ref")}
    if tool in ("wait_for", "wait_idle"):
        # A wait that returned ok is verified by construction: the condition
        # it named actually held.
        verified, delivery_only = True, False
    else:
        verdict = result.get("verified")
        verified = verdict in _VERIFIED
        # An offset click (`at`) can never be confirmed by locator -- the
        # least replayable step there is (D66) -- so it is delivery_only
        # whatever the verdict said.
        delivery_only = verdict in _DELIVERED or "at" in args
    return {"tool": tool, "args": args,
            "verified": verified, "delivery_only": delivery_only}
