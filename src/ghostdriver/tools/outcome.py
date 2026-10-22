"""What a failed actuation *did*, when the result can tell (#194, #195,
#240, #244). Its own module: `acting.py` sat at the tool-module limit (D60).

Two cases the flat "none produced the expected result" hid. A window
appeared or the target became held: the action was delivered and the
application answered it -- an Error dialog is the outcome, not a miss. A
route delivered and nothing at all changed: the control may act only on a
route this did not take; the result names those routes, counts repeats of
the same action, and carries a hand-off for a person. `ok` stays false
either way: a named expectation that did not hold did not hold (D28).
"""

from ..model.result import ErrorKind
from .core import _physical
from .guidance import NO_EFFECT_HINT


def actuation_outcome(result, history: list, locator: str, node=None, at=None) -> dict | None:
    """The outcome block for a failed actuation, or None.

    `history` is this session's ledger, this action already recorded last;
    `node` and `at` are what was aimed at, for the hand-off's point.
    """
    if (result.error or {}).get("kind") != ErrorKind.POSTCONDITION_FAILED.value:
        return None
    appeared = [d.get("detail") for d in result.disturbances
                if d.get("change") == "window_appeared"]
    held = [d.get("detail") for d in result.disturbances
            if d.get("change") == "blocked"]
    if appeared or held:
        raised = appeared or held
        return {
            "outcome": "delivered_raised_window",
            "fields": {"raised": raised},
            "lead": (f"delivered, and a window appeared ({', '.join(raised)}); the "
                     "named expectation did not hold. Read it with modals and "
                     "deal with it before retrying: it may be the application's "
                     "answer to this action."),
        }
    delivered = (len(result.declined) < len(result.routes_attempted)
                 if result.routes_attempted else result.tier_used is not None)
    if not (delivered and not result.disturbances):
        return None
    # Failed deliveries of *this same action* -- tool, locator and what was
    # sent -- this session, this one included. A different button, point or
    # count is a different action, not a retry (#240).
    this = history[-1] if history else None
    count = sum(1 for o in history
                if this is not None and not o.ok and o.locator == locator
                and o.tool == this.tool and o.action == this.action)
    again = (f"This is delivery #{count} of this same action to this control "
             "with no effect in this session; repeating it will not act. "
             if count >= 2 else "")
    fields: dict = {"no_effect_count": max(count, 1)}
    handoff = _handoff(node, at, result)
    if handoff is not None:
        fields["handoff"] = handoff
    return {"outcome": "delivered_no_effect", "fields": fields,
            "lead": again + NO_EFFECT_HINT}


def _handoff(node, at, result) -> dict | None:
    """What a person needs to take the step (#244): the control, where on
    the screen the action aimed, and what was already tried -- shaped for
    `await_human`. It names no tool. A control that answers only real input
    is a step for someone at the desk; ghostdriver never moves the
    operator's pointer to do it (D#133)."""
    if node is None or not getattr(node, "rect", None):
        return None
    left, top, right, bottom = node.rect
    if at is not None:
        x, y = left + int(at[0]), top + int(at[1])
    else:
        x, y = (left + right) // 2, (top + bottom) // 2
    class_name = getattr(node, "class_name", "") or ""
    physical = _physical((x, y, x, y)).get("physical_rect")
    return {
        "class": class_name,
        "point": {"x": x, "y": y, "frame": "screen, logical"},
        **({"physical_point": {"x": physical["left"], "y": physical["top"]}} if physical else {}),
        "tried": list(result.routes_attempted),
        "ask": (f"Please click the {class_name or 'control'} at screen point ({x}, {y})"
                + (f" ({physical['left']}, {physical['top']} in physical pixels)" if physical else "")
                + ": it did not respond to the automated input tried "
                f"({', '.join(result.routes_attempted) or 'the posted route'})."),
    }
