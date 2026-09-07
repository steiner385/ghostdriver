"""Is the target blocked, and by what.

A modal dialog does not merely sit on top of an application; it disables
the window it belongs to. Until it is dealt with, every other control in
that window legitimately refuses input -- which from the outside is
indistinguishable from the application having hung, and is the single most
common reason an automated caller starts retrying clicks that can never
work. A caller that knows a modal is up deals with the modal first.

The signature is a Win32 one rather than an application one: a modal dialog
is an owned, visible top-level window whose owner is disabled. Any toolkit
that shows a modal dialog produces it, because that is what showing one
does.

Pure, so it is testable without a desktop. A backend supplies the state.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TopLevel:
    """One top-level window's identity and blocking state."""

    handle: int
    class_name: str
    text: str
    visible: bool
    enabled: bool
    #: The window this one is owned by, or 0. Not a parent: an owned window
    #: is top-level in its own right.
    owner: int = 0
    #: The window says of itself that it is modal, rather than the fact
    #: being inferred from its owner going disabled.
    #:
    #: Two platforms, two signatures for one fact. Win32 has no such
    #: declaration and does not need one -- showing a modal disables the
    #: owner, so `enabled` carries it. GTK/X11 has the declaration
    #: (`_NET_WM_STATE_MODAL`) and *nothing else*: the owner keeps
    #: `SENSITIVE` for the whole life of the modal, so a backend that only
    #: filled in `enabled` would report a completely held application as
    #: fine (D#12).
    #:
    #: A backend sets whichever it can actually observe. False means "not
    #: declared", never "not modal" -- on Windows it is always False.
    modal: bool = False
    #: The system's own verdict: its thread has pumped no message for five
    #: seconds. A frozen application still answers a cached title, so
    #: nothing else here tells it from a busy one (D66).
    hung: bool = False


@dataclass(frozen=True, slots=True)
class ModalBlock:
    """A visible dialog and the window it is holding."""

    dialog: TopLevel
    blocked: TopLevel

    def describe(self) -> str:
        name = self.dialog.text or f"<untitled {self.dialog.class_name}>"
        held = self.blocked.text or f"<untitled {self.blocked.class_name}>"
        return f"{name!r} is holding {held!r}"


@dataclass(frozen=True, slots=True)
class UnexplainedBlock:
    """A disabled window with no visible dialog to account for it.

    Worth reporting separately rather than ignoring. It is what an
    application looks like when a dialog is off-screen, on another desktop,
    or owned by a thread that has stopped pumping -- and it is the state
    most often misread as "the application has hung", because from the
    outside the symptom is identical: nothing responds and nothing explains
    why.
    """

    blocked: TopLevel


def _is_holding(window: TopLevel, owner: TopLevel) -> bool:
    """Is this visible, owned `window` holding its `owner`?

    Both callers have already established that `window` is visible and that
    `owner` is the window it names. This decides only the modality itself.

    There are two signatures for one fact, and a backend supplies whichever
    it can observe (see `TopLevel.modal`):

    - **Win32**: showing a modal *disables* its owner. There is no
      declaration, so `owner.enabled` is the whole signal, and `modal` is
      always False.
    - **GTK/X11**: the modal declares itself with `_NET_WM_STATE_MODAL` and
      names its owner with `WM_TRANSIENT_FOR`, and the owner keeps
      `SENSITIVE` throughout. `enabled` never moves, so it carries nothing
      (D#12).

    A platform answering neither is not blocked. A platform answering both
    is blocked once, not twice -- the caller de-duplicates by owner.
    """
    # Either, not both: these are two dialects of one fact, and no platform
    # is required to speak both. Neither is preferred over the other, which
    # would need list-wide context this does not have and would make a
    # platform that answered both ambiguous for no gain -- the caller
    # de-duplicates by owner, so agreement costs nothing.
    return window.modal or not owner.enabled


def find_modal_blocks(
    windows: list[TopLevel],
) -> tuple[list[ModalBlock], list[UnexplainedBlock]]:
    """Which windows are being held, and by what.

    A window counts as blocking only if it is visible: a disabled owner
    with a *hidden* owned window is not being held by something the user
    can act on, and reporting it as modal would send a caller to interact
    with a window that is not on screen.

    A *disabled* window counts only when something is stacked on it, and
    that distinction was found on a real target. Two shapes look alike:

    - Dialogs stacked on dialogs. Each disables the one below, so a middle
      dialog is disabled and still genuinely holding what is under it. It
      is a link in the chain and belongs in the report.
    - An application proxy owning both its main window and a dialog. Here
      the main window is disabled and owns nothing -- it is not holding
      anything, it is simply another thing being held, alongside the
      dialog. Reporting it said the application was being held by its own
      main window, and named that window as something for an operator to go
      and deal with.

    What separates them is whether anything is stacked on the window in
    question. A link has something above it; a fellow victim does not.
    """
    by_handle = {w.handle: w for w in windows}
    blockers: dict[int, TopLevel] = {}
    blocks: list[ModalBlock] = []

    candidates = [
        (window, by_handle[window.owner])
        for window in windows
        if window.visible
        and window.owner in by_handle
        and _is_holding(window, by_handle[window.owner])
    ]
    # Windows that have something stacked on them. A disabled window in
    # this set is a link in a modal chain; one outside it is just another
    # window the same modal disabled.
    held = {owner.handle for _, owner in candidates}

    for window, owner in candidates:
        if not window.enabled and window.handle not in held:
            continue
        blocks.append(ModalBlock(dialog=window, blocked=owner))
        blockers[owner.handle] = window

    unexplained = [
        UnexplainedBlock(blocked=w)
        for w in windows
        # A disabled *owned* window is usually just a dialog's own parent
        # further up a modal chain, already accounted for by the block on
        # it. Only unowned windows are reported here.
        if not w.enabled and w.visible and w.handle not in blockers and not w.owner
    ]
    return blocks, unexplained


def is_blocked(windows: list[TopLevel]) -> bool:
    blocks, unexplained = find_modal_blocks(windows)
    return bool(blocks or unexplained)
