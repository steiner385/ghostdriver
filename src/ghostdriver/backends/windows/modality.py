"""Top-level window state, including ownership, for modality detection."""

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
