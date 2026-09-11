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


def held_on_this_run(tool: str, result: dict) -> bool:
    """Did this call's own postcondition hold, on this run?

    The runtime verdict, as distinct from a macro step's static `verified`
    flag (which says whether it held *when recorded*). An actuation held when
    its `expect` verified (effect / committed / display). A wait that returned
    ok held by construction: the condition it named actually came true. A
    read has no postcondition and can never claim to have held (#112).
    """
    if not result.get("ok"):
        return False
    if tool in ("wait_for", "wait_idle"):
        return True
    return result.get("verified") in _VERIFIED


def capture_step(tool: str, bound: dict, result: dict,
                 defaults: dict | None = None) -> dict | None:
    """A macro step for this call, or None if it is not one to record.

    `bound` is the call's arguments (the session stripped); `result` its
    outcome; `defaults` the tool's own signature defaults, when the caller has
    them. Returns None for a non-recordable tool or a call that did not
    succeed -- so nothing a person did not actually accomplish, and no
    refused secret, ever lands in a macro.
    """
    if tool not in RECORDABLE or not result.get("ok"):
        return None
    # The MCP layer passes every parameter explicitly, defaults included, so
    # `at=None` arrives as a *present* key and `button="left"` as a present
    # value. Neither was asked for. A None is "not given" and is dropped
    # (#108: a present-but-None `at` used to flag a verified click as an
    # offset click); a value equal to the tool's own default is dropped too
    # (#112), so the macro records exactly what was asked -- readable, and
    # diff-able -- while replay is unaffected, since an omitted arg takes the
    # same default at run time. A non-default value is always kept.
    defaults = defaults or {}
    args = {k: v for k, v in bound.items()
            if k not in ("session_id", "session_ref")
            and v is not None
            and not (k in defaults and v == defaults[k])}
    verified = held_on_this_run(tool, result)
    # An offset click (`at`) can never be confirmed by locator -- the least
    # replayable step there is (D66) -- so it is delivery_only whatever the
    # verdict said. A *value* for at, not a present key.
    delivery_only = (tool not in ("wait_for", "wait_idle")
                     and (result.get("verified") in _DELIVERED
                          or args.get("at") is not None))
    return {"tool": tool, "args": args,
            "verified": verified, "delivery_only": delivery_only}
