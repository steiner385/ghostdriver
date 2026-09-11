"""The operator-present live-actuation gate, and the sandbox-aware naming
that goes with it (D#101, D#110, D#111).

Its own mixin so `core` and `lifecycle` stay under the tool-module limit
(D60), and because the two concerns here are one story: a sandboxed target
(Bambu Studio, a Flatpak) is known to the bus by a name its process does not
carry, and driving it live -- the only way its wxGTK3 fields commit -- takes
a real keystroke on the operator's own display, allowed only when the window
they are watching is already the front.
"""

from ..model.result import ErrorKind
from .core import _error, _ToolboxCore


class _LiveCore(_ToolboxCore):
    def _live_window_or_error(self, pid: int, tier, live: bool):
        """Resolve the window a live session may drive, or the reason it may
        not. `(live_window, None)` on success -- 0 when not asked -- or
        `(0, error_dict)` when a live session is asked for and refused."""
        from ..policy import Tier

        if not live:
            return 0, None
        if tier is Tier.READ_ONLY:
            return 0, _error(
                ErrorKind.DENIED_BY_POLICY,
                "live actuation needs tier=interactive or full: a read_only "
                "session never actuates, so a live grant would authorise "
                "nothing")
        from ..backends import current
        try:
            live_window = current().winapi.resolve_live_window(pid)
        except Exception as exc:
            return 0, _error(ErrorKind.NOT_ACTIONABLE,
                             f"could not check the foreground window: {exc}")
        if not live_window:
            return 0, _error(
                ErrorKind.NOT_ACTIONABLE,
                "live actuation is allowed only into a window of the target "
                "that is the foreground right now (D#111), and none is. Bring "
                "the window you want driven to the front -- the one you are "
                "watching -- and attach again with live=true.")
        return live_window, None

    def _named_target(self, pid: int, process_name: str) -> tuple[str, dict]:
        """The name to list a target under, and the process name kept beside
        it when they differ. A Flatpak's a11y pid is its D-Bus proxy's, so
        `psutil` says `xdg-dbus-proxy` where the bus says `bambu-studio`
        (D#101, D#110); the bus name wins, with the process name kept so a
        caller can still see what the pid really is."""
        from ..backends import current

        try:
            app = current().application_name(pid)
        except Exception:
            app = None
        if app and app != process_name:
            return app, {"process_name": process_name}
        return process_name, {}
