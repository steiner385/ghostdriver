"""What to say at the moment of need.

A real session dismissed a dialog unread because nothing named `modals`
when it learned the target was held, and paged a grid blind because
nothing named `probe_grid`. Errors and blocked states are the right place
to name the tool that addresses them; these are the sentences they use.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - types only
    from ..model.window import WindowNode
    from ..session import Profile

#: Said wherever a block is reported: the moment a caller learns the target
#: is held is the moment they need the tool that reads what is holding it.
BLOCKED_HINT = (
    "read the dialog with `modals` before acting; its buttons are separate "
    "top-level windows (all_windows=true). If a person must answer it, use "
    "`await_human`. Dismissing a dialog unread is the one thing this tool is "
    "built to prevent."
)

#: For a region that exposes nothing: what the tool can still do with it.
PIXELS_HINT = (
    "no window or element names its content. `probe_grid` finds an exact-text "
    "route (a copy command, a focus-revealed surface) and records it; `capture` "
    "shows it; `click` with at={x, y} acts at a point inside it; `send_keys` "
    "moves through it (home, end, pageup, pagedown, down)."
)


#: Said by modals and describe when the system reports a window's thread
#: hung: it has pumped no message for five seconds.
HUNG_HINT = (
    "the application has stopped pumping messages: the system reports it "
    "hung. Nothing sent to it will be handled until it recovers or is "
    "ended. Stop acting on it and tell the person; a capture still shows "
    "its last rendering"
)

#: Said when a route needs to write the person's clipboard and the session
#: was not attached with clipboard=true (D70).
CLIPBOARD_NOT_ALLOWED = (
    "the clipboard route was not tried: this session may not write the "
    "person's clipboard. The target's own Copy command writes it, which is a "
    "disruption they notice. If the operator agrees, attach with "
    "clipboard=true; every format is then saved and put back around each "
    "copy, but choose a moment when they are not copying themselves"
)

def text_guard(
    profile: "Profile", node: "WindowNode", locator: str,
) -> tuple[str | None, str | None]:
    """Whether a region whose text query answers may be probed anyway.

    Returns `(refusal, waiver)`, at most one of them set. A region `read`
    already answers is refused, because spending a side effect on something
    a free call reads is the wrong trade (D46) -- and for a button, whose
    caption *is* its content, that reasoning holds exactly.

    Measured against a real owner-drawn grid it did not hold (D#1):
    `WM_GETTEXT` answered `'Character Grid'`, a static accessible name the
    class sets once, and `read` returned it whatever glyphs were painted
    inside. The guard refused the very control `probe_grid` exists to
    reach, and the caller who followed its advice got a plausible,
    content-free answer with no way to tell it was wrong (#141).

    Nothing available here separates a caption from a label: the text is
    non-empty in both cases, and a driver that inferred which from the
    class name would be picking rather than refusing (D33). So the guard
    stays and the person waives it, per class, in the profile -- a declared
    fact beating a measured one (D35), the same shape as
    `posted_click_only` (D#122) and `hover_before_click` (D#133). The
    waiver is said in the report rather than applied silently: a probe that
    ran because of a declaration should read as one.
    """
    if not node.text:
        return None, None
    declared = profile.declares_label_text(node.class_name)
    if declared is not None:
        return None, (
            f"{node.text[:40]!r} is a label, not content: profile "
            f"text_is_label matches {declared!r}"
        )
    named = repr(node.class_name) if node.class_name else "its class"
    return (
        f"{locator!r} answers a text query with ({node.text[:40]!r}), so "
        "probing it would spend a side effect on a region `read` already "
        "reads. Use `read` -- unless that text is a fixed label the class "
        "sets once rather than the region's content, which nothing here can "
        f"measure (D#141). If the operator knows it is, list {named} in the "
        "profile's `text_is_label` and probe again"
    ), None


#: Carried by a click result when the target's window is not its thread's
#: active window -- which a second top-level window of the same thread
#: need not be.
FOCUS_NOTE = (
    "the target's window is not its thread's active window, so a control "
    "that checks that before acting on a click ignores it. Controls differ: "
    "a VCL form records its active control without it, so one grid proceeds "
    "while another, asking the window state directly, does not; `expect` is "
    "how to tell which. This tool never activates a window: that is the "
    "division of labour, not a gap. A control that insists on an active "
    "window is a step for a person (await_human, with until_change when you "
    "cannot name what will appear) or for a tool that does activate windows, "
    "such as computer use, given the coordinates this tool found."
)


#: Said when a route delivered, the named expectation did not hold, and
#: nothing changed around the action (#195). Seven retries of the same
#: click were made against a verdict that read "try again"; the routes
#: named here are the ones still inside the contract, in the order to try
#: them. Never a pointer tool (D#133).
NO_EFFECT_HINT = (
    "Delivered to the control and nothing changed: it may act only on a "
    "route this did not take. Still inside the contract: a combo or "
    "dropdown opens from the keyboard (send_keys [\"f4\"] to the field); an "
    "editable grid cell opens its editor on f2 or a double-click (count=2), "
    "and then takes set_value on the editor window it shows (find with "
    "all_windows=true); a popup-menu item takes menu_by_keyboard=true. A "
    "control that checks that its window is active before acting ignores a "
    "posted click while another window is active -- see focus. Otherwise "
    "this is a step for a person: await_human."
)
