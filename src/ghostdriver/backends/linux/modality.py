"""Top-level window state, ownership and modality -- read from X, not AT-SPI.

Windows has one identifier space. An `hwnd` is what the accessibility layer
talks about *and* what the window manager talks about, so `top_level_state`
reports `handle` and `owner` in the same currency without anyone deciding to.

Linux has two, and the split runs straight through this file:

* The **tree** mints handles for AT-SPI accessibles (`tree._mint`). That is
  the space a `WindowNode.handle` is in, and it is what callers pass to
  `blocking_ancestor` and `surface_of`.
* **Modality is a window-manager fact.** `_NET_WM_STATE_MODAL` and
  `WM_TRANSIENT_FOR` are X properties on an *xid*, and D#12 measured that
  AT-SPI carries none of it -- the owner keeps `SENSITIVE` for the modal's
  entire life, and the modal comes back with role `frame` rather than
  `dialog`, so neither a state nor a role gives it away.

So `top_level_state` answers in **xids**: `handle` and `owner` are both X
window ids, which is the only way `find_modal_blocks` can look an owner up
and find it. Functions that take a caller's `WindowNode.handle` correlate
across the boundary first, and `_xid_of` is where that happens.
"""

from __future__ import annotations

import contextlib
from functools import partial
from typing import Any

from ...disturbance import Snapshot
from ...modality import TopLevel, find_modal_blocks
from ...surface import is_web_host
from .. import UnsupportedPlatform
from . import display
from .deadline import call_with_deadline
from .tree import _accessible


def top_level_state(pid: int) -> list[TopLevel]:
    """Identity and blocking state of every managed top-level of `pid`.

    Every field comes from the window manager. Going to AT-SPI for the
    caption instead -- the way the Windows one calls `read_window_text` --
    would cost a bus round trip per window and answer the same string, and
    it would reintroduce the correlation problem for no gain.

    `enabled` is always True, and that is a measurement rather than a stub:
    nothing on this platform ever reports a top-level as insensitive while
    a modal holds it (D#12). The blocking signal is `modal`.
    """
    state: list[TopLevel] = []
    for xid in display.windows_of(pid):
        state.append(
            TopLevel(
                handle=xid,
                # The accessible role is what `class_name` carries elsewhere
                # on this backend (D#40b), and for a top-level the window
                # manager's answer is the window type rather than a role.
                # "frame" is what AT-SPI calls both a window and a modal
                # here, so it is the honest constant.
                class_name="frame",
                text=display.window_name(xid),
                # Not map state: a compositing window manager leaves an
                # iconified window `IsViewable`, so `_NET_WM_STATE_HIDDEN`
                # is the signal (D#13).
                visible=not display.is_hidden(xid),
                enabled=True,
                owner=display.transient_for(xid),
                modal=display.is_modal(xid),
                # There is no `IsHungAppWindow` here. A frozen application
                # is detected by the read deadline instead (D#9), which is
                # the caller's job and not visible from an X property.
                hung=False,
            )
        )
    return state


def _frame_of(accessible: Any) -> Any:
    """Walk up to the top-level frame that contains this accessible."""
    node = accessible
    seen = 0
    while node is not None and seen < 64:
        seen += 1
        if (call_with_deadline(node.get_role_name) or "") == "frame":
            return node
        node = call_with_deadline(node.get_parent)
    return None


def _xid_of(handle: int) -> int | None:
    """The X window carrying the frame that contains `handle`, or None.

    This is the one place the two identifier spaces meet, and there is no
    cheap route across. Measured on the fixture with a modal up:

    * `Atspi.Accessible.get_attributes()` returns `{'toolkit': 'GTK'}` and
      no window id, so the direct answer does not exist.
    * A frame's `get_extents(SCREEN)` reports **0, 0** for both the main
      window and a modal that X had placed at (259, 275) -- GTK4/X11 does
      not answer screen position through the accessibility layer. Position
      cannot be used. **Size matches exactly**, and is used.
    * `_NET_WM_NAME` matches the accessible name exactly, both windows.

    So the key is name *and* size, and ambiguity is refused rather than
    guessed at (D33): two frames of one process with the same title and the
    same size are genuinely indistinguishable from here, and picking one
    would mean answering "what is holding this control" with a coin flip.
    Returning None makes the caller's answer "nothing found", which is the
    same thing it says for an unheld window -- so the *caller* re-asks the
    question per process rather than trusting the miss.
    """
    accessible = _accessible(handle)
    frame = _frame_of(accessible)
    if frame is None:
        return None
    pid = call_with_deadline(frame.get_process_id)
    if pid is None:
        return None
    name = call_with_deadline(frame.get_name) or ""

    size: tuple[int, int] | None = None
    with contextlib.suppress(Exception):
        from gi.repository import Atspi

        extents = call_with_deadline(
            partial(frame.get_extents, Atspi.CoordType.SCREEN)
        )
        if extents is not None:
            size = (extents.width, extents.height)

    matches = [
        xid for xid in display.windows_of(pid)
        if display.window_name(xid) == name
        and (size is None or display.geometry(xid)[2:] == size)
    ]
    return matches[0] if len(matches) == 1 else None


def blocking_ancestor(handle: int) -> int | None:
    """The modal holding this control, if any -- and it is the *modal*.

    The Windows one walks up looking for a window that reports **disabled**,
    because there a modal disables its owner. Here nothing is ever disabled,
    so that walk returns "no" while the application is completely held
    (D#12). The check inverts: not *is anything above me disabled* but **is
    anything modal transient for me**.

    What comes back is therefore the dialog rather than the window it is
    holding, which is also the more useful of the two -- it is the thing an
    operator has to go and deal with. Callers test it for None.

    When the frame cannot be identified unambiguously (`_xid_of`), the
    question is re-asked of the whole process: is anything in it modal at
    all? That is a weaker answer -- it can refuse an action on a second,
    unheld window of the same process -- and it is the safe direction. A
    wrong refusal costs a caller an attempt; a wrong permission actuates
    into a held application, which is the failure D#12 exists to prevent.
    """
    pid = _pid_of_accessible(_accessible(handle))
    if pid is None:
        return None

    state = top_level_state(pid)
    blocks, _ = find_modal_blocks(state)
    if not blocks:
        return None

    xid = _xid_of(handle)
    if xid is None:
        # Ambiguous or unresolvable: answer for the process.
        return blocks[0].dialog.handle
    for block in blocks:
        if block.blocked.handle == xid:
            return block.dialog.handle
    # The control's own frame is not held. It may still *be* the modal, in
    # which case acting on it is exactly what a caller should be doing.
    return None


def _pid_of_accessible(accessible: Any) -> int | None:
    with contextlib.suppress(Exception):
        return int(accessible.get_process_id())
    return None


def snapshot(pid: int) -> Snapshot:
    """What an action is compared against, for `Actuator.observe`.

    Top-level windows only, for the same reason as on Windows: a full tree
    walk before and after every action would cost more than the action, and
    every question worth asking here is answerable from this much.
    """
    try:
        state = top_level_state(pid)
    except UnsupportedPlatform:
        # Not a dead target: a desktop this cannot read (#215).
        raise
    except Exception:
        return Snapshot(alive=False)
    if not state:
        return Snapshot(alive=False)

    blocks, _ = find_modal_blocks(state)
    return Snapshot(
        windows={w.handle: w.text for w in state if w.visible},
        blocked_by=tuple(b.dialog.text or "(untitled)" for b in blocks),
        foreground=display.active_window() or 0,
        alive=True,
    )


def surface_of(handle: int) -> str:
    """Which kind of surface a control sits in: "web" or "native".

    The cheap answer, as on Windows, and only the split a cadence note
    needs. What differs is what gets looked at: there is no window class
    here, so this walks the *accessible* ancestors and tests each role,
    `class_name` on this backend being the accessible role (D#40b).

    **Answered "native" for everything until L8 (#15) measured an embedded
    document.** `document web` -- the AT-SPI role a live document
    publishes under, measured against WebKitGTK's GTK3 binding -- now sits
    in `WEB_HOST_CLASSES` alongside the Win32 window classes, so this walk
    matches it exactly as written: no change needed here, because the
    walk was already written to need none (D#15).
    """
    node = _accessible(handle)
    seen = 0
    while node is not None and seen < 64:
        seen += 1
        role = call_with_deadline(node.get_role_name) or ""
        if is_web_host(role):
            return "web"
        node = call_with_deadline(node.get_parent)
    return "native"
