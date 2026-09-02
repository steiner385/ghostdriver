"""Top-level window state, including ownership, for modality detection."""

from ctypes import wintypes

from ...modality import TopLevel
from . import winapi
from .enumerate import top_level_windows
from .text import read_window_text


def top_level_state(pid: int) -> list[TopLevel]:
    """Identity and blocking state of every top-level window of `pid`.

    `read_window_text` rather than a cached caption: a dialog's title is
    the one piece of information that tells an operator which dialog is
    holding the application, and it is worth a timeout-capped read.
    """
    state: list[TopLevel] = []
    for hwnd in top_level_windows(pid):
        text = read_window_text(hwnd)
        state.append(
            TopLevel(
                handle=hwnd,
                class_name=winapi.class_name(hwnd),
                text=text or "",
                visible=bool(winapi.user32.IsWindowVisible(hwnd)),
                enabled=bool(winapi.user32.IsWindowEnabled(hwnd)),
                owner=winapi.owner_window(hwnd),
            )
        )
    return state


#: `GetAncestor` codes: the immediate parent, and the top-level owner.
GA_PARENT = 1
GA_ROOT = 2

winapi.user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
winapi.user32.GetAncestor.restype = wintypes.HWND


def blocking_ancestor(hwnd: int) -> int | None:
    """The disabled window standing between `hwnd` and the user, if any.

    `IsWindowEnabled` answers for one window and no further. Measured on
    the fixture with a modal up: the top-level reports disabled and its
    buttons report *enabled*, because a modal disables the top-level and
    the children are only unreachable through it. A driver that asks the
    control alone therefore sees nothing wrong, actuates into a held
    application, and reports whatever happens next as the truth.

    So the chain gets walked. A returned handle is the reason an action
    should not be attempted, and naming it is what lets an operator see
    *which* window is holding the application rather than a bare refusal.
    """
    seen: set[int] = set()
    current = hwnd
    while current and current not in seen:
        seen.add(current)
        if not winapi.user32.IsWindowEnabled(wintypes.HWND(current)):
            return current
        parent = winapi.user32.GetAncestor(wintypes.HWND(current), GA_PARENT)
        current = int(parent) if parent else 0
    return None
