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


def find_modal_blocks(
    windows: list[TopLevel],
) -> tuple[list[ModalBlock], list[UnexplainedBlock]]:
    """Which windows are being held, and by what.

    A window counts as blocking only if it is visible: a disabled owner
    with a *hidden* owned window is not being held by something the user
    can act on, and reporting it as modal would send a caller to interact
    with a window that is not on screen.
    """
    by_handle = {w.handle: w for w in windows}
    blockers: dict[int, TopLevel] = {}
    blocks: list[ModalBlock] = []

    for window in windows:
        owner = by_handle.get(window.owner)
        if owner is None or owner.enabled or not window.visible:
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
