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
