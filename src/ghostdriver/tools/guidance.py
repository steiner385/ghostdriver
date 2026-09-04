"""What to say at the moment of need.

A real session dismissed a dialog unread because nothing named `modals`
when it learned the target was held, and paged a grid blind because
nothing named `probe_grid`. Errors and blocked states are the right place
to name the tool that addresses them; these are the sentences they use.
"""

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
