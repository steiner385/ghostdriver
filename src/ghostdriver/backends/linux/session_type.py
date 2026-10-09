"""Which display server a claimant's desktop runs: X11 or Wayland (#215).

Measured on linux-host-a (GNOME 50, Wayland), not assumed: XWayland answers X
queries about X clients only, so on a Wayland session every X-sourced fact
about the desktop is a fact about the wrong desktop. `_NET_ACTIVE_WINDOW`
named gnome-shell while Chrome held the front; `snapshot` of a live Chrome
said `alive=False`. Enumeration is AT-SPI-sourced and was right. So the
question "is this desktop X11" has to be asked before any X call, and per
claimant: a hidden desktop on a Wayland host is still an X server.

`XDG_SESSION_TYPE` wins when it is set, because it names the *session*.
`WAYLAND_DISPLAY` alone also leaks into the children of a nested
compositor started from an X session.

**When the environment says nothing, the X server is asked.** A server
launched outside the graphical session inherits `DISPLAY=:0` and neither
variable -- measured on linux-host-a, where this guard was otherwise switched off
in exactly the deployment it exists for (final review, #215). Xwayland
advertises the `XWAYLAND` extension and a plain X server does not, so
`display.py` registers a probe that reads it.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Literal

from .. import UnsupportedPlatform
from . import desktop_claim

DisplayServer = Literal["x11", "wayland"]

#: Answers "is this claimant's X server Xwayland?". Registered by
#: `display.py`, which owns the connection; None until it is imported.
_server_probe: Callable[[str], bool] | None = None


def register_server_probe(probe: Callable[[str], bool]) -> None:
    global _server_probe
    _server_probe = probe


class X11Only(UnsupportedPlatform):
    """This name reads or drives the desktop through X, and the desktop is
    a Wayland session, where X sees only XWayland clients."""


def display_server(owner: str | None = None,
                   environ: Mapping[str, str] | None = None) -> DisplayServer:
    """The display server `owner`'s desktop runs (default: whoever is
    asking now). A hidden desktop answers from what it registered; the
    operator's desktop from the process environment."""
    owner = owner or desktop_claim.effective_owner()
    if owner != desktop_claim.OPERATOR_DESKTOP:
        registered = desktop_claim.environment_for(owner)
        return "wayland" if registered.get("WAYLAND_DISPLAY") else "x11"
    env = os.environ if environ is None else environ
    kind = env.get("XDG_SESSION_TYPE", "")
    if kind == "x11":
        return "x11"
    if kind == "wayland":
        return "wayland"
    if env.get("WAYLAND_DISPLAY"):
        return "wayland"
    # The environment is silent: ask the X server itself. Skipped when a
    # caller passes its own `environ` -- that caller is asking about it.
    if environ is None and _server_probe is not None and _server_probe(owner):
        return "wayland"
    return "x11"


def require_x11(what: str) -> None:
    """Refuse `what` on a Wayland desktop, saying why."""
    if display_server() == "wayland":
        raise X11Only(
            f"{what} reads the desktop through X11, and this is a Wayland "
            "session, where X sees only XWayland clients -- the answer "
            "would be about the wrong desktop. Reading the window tree "
            "still works. See docs/LINUX.md (Wayland) for what is measured."
        )
