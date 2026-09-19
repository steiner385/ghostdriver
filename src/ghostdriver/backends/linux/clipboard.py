"""The clipboard, and the two grid routes that use it (#105).

The Windows grid routes are a posted `WM_COPY` (no focus, no input) and a
posted `WM_SETFOCUS`. Neither has a counterpart here: D#11 measured GTK
discarding sent events, so there is no way to make a control copy or focus
without real input. So on Linux both routes are **tier 4** -- they take the
keyboard for an instant through XTest -- and are therefore available only
inside a live session (D#111), the same gate the value commit sits behind.

The clipboard itself is the person's, read and written with the same tool
they use -- `xclip` under X11, `wl-paste`/`wl-copy` under Wayland, chosen by
`WAYLAND_DISPLAY` (D#105a) -- so a copy the tool triggers and the person's
own copy land in the same place. `xclip` reaches an X selection, which under
a Wayland session is not the compositor's own clipboard, so the two tools
are a choice, not a fallback chain: whichever one is missing is simply not
tried. Only text is snapshotted and restored; a bitmap or a private target
the selection held is noted as lost, as on Windows (D70).
"""

from __future__ import annotations

import os
import subprocess
from functools import partial
from typing import Any

from ...gridstrategy import RouteResult, Strategy
from ...model.window import WindowNode
from .deadline import call_with_deadline
from .tree import _accessible

#: Targets that mean "plain text, nothing lost" -- the ones `xclip -o -t
#: TARGETS` or `wl-paste --list-types` name for a text selection with no
#: content of its own. Anything else held is reported as lost on restore.
_X11_TEXT_TARGETS = ("UTF8_STRING", "STRING", "TEXT", "text/plain",
                      "text/plain;charset=utf-8", "TARGETS", "MULTIPLE",
                      "TIMESTAMP")
_WAYLAND_TEXT_TARGETS = ("text/plain", "text/plain;charset=utf-8",
                          "UTF8_STRING", "STRING", "TEXT")


def _wayland_session() -> bool:
    """True when this process is in a Wayland session.

    `WAYLAND_DISPLAY` is the same signal a Wayland-aware application uses to
    pick its own backend, so a driver process inherits it from whoever
    launched it rather than guessing from `DISPLAY` -- XWayland sets that
    too, so its presence alone would pick the wrong tool.
    """
    return bool(os.environ.get("WAYLAND_DISPLAY"))


def _xclip(args: list[str], data: bytes | None = None) -> tuple[bool, bytes]:
    try:
        done = subprocess.run(["xclip", "-selection", "clipboard", *args],
                              input=data, capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False, b""
    return done.returncode == 0, done.stdout


def _wl_paste(args: list[str]) -> tuple[bool, bytes]:
    try:
        done = subprocess.run(["wl-paste", *args], capture_output=True,
                              timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False, b""
    return done.returncode == 0, done.stdout


def _wl_copy(data: bytes) -> bool:
    try:
        done = subprocess.run(["wl-copy"], input=data, capture_output=True,
                              timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def read_clipboard_text() -> str | None:
    """The clipboard's text now, or None when it holds none.

    `xclip -o` and `wl-paste` both fail rather than return empty when the
    selection holds no text target (or the tool is not installed), and that
    is None here: "nothing text-shaped" is a real answer distinct from an
    empty string.
    """
    ok, out = _wl_paste([]) if _wayland_session() else _xclip(["-o"])
    if not ok:
        return None
    return out.decode("utf-8", "replace")


def snapshot_clipboard() -> dict:
    """The clipboard's text and the targets it holds, to put back later.

    Text only for the value; the target list is kept so a route that
    replaced a non-text selection (an image) can say what was lost, since
    neither `xclip` nor `wl-paste` can hand a bitmap back through this path.
    """
    boring: tuple[str, ...]
    if _wayland_session():
        ok, out = _wl_paste(["--list-types"])
        held = out.decode("utf-8", "replace").splitlines() if ok else []
        boring = _WAYLAND_TEXT_TARGETS
    else:
        ok, out = _xclip(["-o", "-t", "TARGETS"])
        held = out.decode("utf-8", "replace").split() if ok else []
        boring = _X11_TEXT_TARGETS
    text = read_clipboard_text()
    lost = [t for t in held if t not in boring]
    return {"text": text, "lost": lost}


def restore_clipboard(snapshot: dict) -> int:
    """Put the text back. Returns 1 if something was restored, 0 otherwise.

    A snapshot with no text leaves the clipboard as it is rather than
    clearing it: the copy route already overwrote it, and blanking it would
    be a second surprise for the person.
    """
    text = snapshot.get("text")
    if text is None:
        return 0
    if _wayland_session():
        ok = _wl_copy(text.encode("utf-8"))
    else:
        ok, _ = _xclip(["-i"], data=text.encode("utf-8"))
    return 1 if ok else 0


SHARED_CLIPBOARD_CAVEAT = (
    "this used the clipboard, which is the person's: their prior text was "
    "put back, but not atomically -- anything they copied in the gap is lost, "
    "and a non-text selection could not be restored"
)


def _action_named(node: Any, name: str) -> int | None:
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    count = call_with_deadline(partial(Atspi.Action.get_n_actions, node)) or 0
    for i in range(count):
        got = call_with_deadline(partial(Atspi.Action.get_action_name, node, i))
        if got and got.lower() == name:
            return i
    return None


def copy_route(node: WindowNode, *, want_text: bool = False) -> RouteResult:
    """Ask the region to copy itself, read what it produced, put things back.

    First an AT-SPI `copy` action if the control publishes one -- free, no
    input -- then a real Ctrl+C through XTest, which needs the control
    focused and is why this is a live-only, tier-4 route. `want_text`
    returns the copied rows for a caller actually reading the grid; the
    probe leaves it False and keeps only the shape.
    """
    from ...gridstrategy import RouteResult as _RR  # local, avoids cycle at import
    from . import display

    accessible = _accessible(node.handle)
    prior = snapshot_clipboard()

    did_copy = False
    idx = _action_named(accessible, "copy")
    if idx is not None:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi

        did_copy = bool(call_with_deadline(partial(Atspi.Action.do_action, accessible, idx)))
    if not did_copy:
        # Real Ctrl+C: focus the control, then the chord through XTest.
        from . import input as linux_input

        linux_input.focus_via_component(node.handle)
        did_copy = display.press_chord("c", ctrl=True)

    text = read_clipboard_text() if did_copy else None
    restored = restore_clipboard(prior)
    caveat = SHARED_CLIPBOARD_CAVEAT
    if prior["lost"]:
        caveat += f"; {len(prior['lost'])} non-text target(s) it held are gone"
    if not restored and prior.get("text") is not None:
        caveat += "; and the prior contents could NOT be put back"

    from ...gridstrategy import looks_like_a_grid

    ok, lines = looks_like_a_grid(text or "")
    return _RR(
        strategy=Strategy.CLIPBOARD_COPY,
        worked=ok,
        lines=lines,
        caveat=caveat,
        detail=(((text or "") if want_text else f"{lines} line(s) of tab-delimited text")
                if ok else
                ("the control did not change the clipboard" if text is None
                 else "the control copied something, but not grid-shaped text")),
    )


def focus_route(node: WindowNode) -> RouteResult:
    """Tell the region it has focus and see whether its accessible tree fills.

    `grab_focus` is the only focus route here, and D#102 measured that it
    raises the window to the foreground on wxGTK3 -- so this too is a
    live-only action. Whether it *reveals* anything is the question the
    Windows one asks: some controls populate their tree only once focused.
    """
    from . import input as linux_input

    before = _descendant_count(node.handle)
    linux_input.focus_via_component(node.handle)
    after = _descendant_count(node.handle)
    revealed = after - before
    return RouteResult(
        strategy=Strategy.ACCESSIBLE_ON_FOCUS,
        worked=revealed > 0,
        lines=after if revealed > 0 else 0,
        detail=f"{before} accessible descendants before focus, {after} after",
    )


def _descendant_count(handle: int) -> int:
    accessible = _accessible(handle)
    total = [0]

    def walk(node: Any, depth: int) -> None:
        if depth > 24:
            return
        kids = call_with_deadline(node.get_child_count) or 0
        for i in range(kids):
            child = call_with_deadline(partial(node.get_child_at_index, i))
            if child is not None:
                total[0] += 1
                walk(child, depth + 1)

    walk(accessible, 0)
    return total[0]
