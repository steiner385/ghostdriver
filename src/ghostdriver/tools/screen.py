"""Bringing a window forward on request (D73): the pair to isolation=minimized."""

from ..model.element import AccessibleElement
from ..model.result import ErrorKind, GhostdriverError
from .core import _error, _ToolboxCore


class ScreenTools(_ToolboxCore):
    """The one tool that deliberately interrupts the operator, and only when asked."""

    def foreground(self, session_id: str, *, locator: str | None = None) -> dict:
        """Bring a window of the target to the front, on request only.

        The pair to `isolation=minimized`: one option keeps the target out
        of the way, this brings it deliberately forward. Everything else
        this server does works from the background without a raise (a posted
        message needs no foreground), so this exists for the one case that
        cannot: handing the actual click to a tool that uses real input,
        which requires the window frontmost.

        It interrupts the operator -- the window comes forward and the
        keyboard focus moves with it -- so it is never automatic and never a
        side effect of another tool. Interactive tier, and it says whether it
        took the foreground: a background process's SetForegroundWindow can
        be refused by Windows, and `took_foreground: false` is that refusal,
        honestly (D73).
        """
        try:
            session = self.sessions.authorize(session_id, "foreground")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)
        from ..backends import current

        if locator is not None:
            try:
                matches = self._resolve(session, locator, True)
            except ValueError as exc:
                return _error(ErrorKind.NOT_FOUND, str(exc), locator=locator)
            if not matches:
                return _error(ErrorKind.NOT_FOUND, f"nothing matched {locator!r}", locator=locator)
            node = matches[0]
            handle = node.host_handle if isinstance(node, AccessibleElement) else node.handle
        else:
            trees = self._trees(session, all_windows=False)
            if not trees:
                return _error(ErrorKind.NOT_FOUND,
                              f"pid {session.pid} has no main window to bring forward")
            handle = trees[0].handle

        winapi = current().winapi
        took = session.run(lambda: winapi.bring_foreground(handle))
        return {
            "ok": True,
            "took_foreground": bool(took),
            "window": {"class": winapi.class_name(handle),
                       "handle_ephemeral": f"0x{handle:08X}"},
            "warning": ("the target is now at the front and the keyboard focus "
                        "moved with it: the operator's typing goes here until "
                        "they click away. Do this only when a step needs the "
                        "window frontmost, and tell them first."),
            **({} if took else {"note": (
                "Windows refused the foreground from this background process; "
                "the window may only have flashed in the taskbar. Ask the "
                "operator to click it, or try again once nothing is holding "
                "the foreground.")}),
        }
