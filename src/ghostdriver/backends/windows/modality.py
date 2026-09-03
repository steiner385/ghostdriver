"""Top-level window state, including ownership, for modality detection."""

from ctypes import wintypes

from ...disturbance import Snapshot
from ...modality import TopLevel, find_modal_blocks
from ...surface import is_web_host
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
                hung=winapi.is_hung(hwnd),
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

def snapshot(pid: int) -> Snapshot:
    """What an action is compared against, for `Actuator.observe`.

    Top-level windows only. A full tree walk before and after every action
    would cost more than the action itself, and every question worth asking
    here -- did a dialog appear, is the application held, did it come to the
    front -- is answerable from this much.

    A target that has stopped owning windows is reported as gone rather than
    as an empty desktop, because those mean very different things to a
    caller: one is a session that timed out, the other is a bug in this
    function.
    """
    try:
        state = top_level_state(pid)
    except Exception:
        return Snapshot(alive=False)
    if not state:
        return Snapshot(alive=False)

    blocks, _ = find_modal_blocks(state)
    return Snapshot(
        windows={w.handle: w.text for w in state if w.visible},
        blocked_by=tuple(b.dialog.text or "(untitled)" for b in blocks),
        foreground=winapi.foreground_window(),
        alive=True,
    )

def surface_of(hwnd: int) -> str:
    """Which kind of surface a control sits in: "web" or "native".

    Deliberately the cheap answer, and only the split that matters here. The
    full surface map probes each region through the accessibility layer,
    which is far too expensive to run before every keystroke -- but the one
    question a cadence note needs is whether this control lives inside
    embedded web content, and a web host announces itself in its class name.
    So this walks ancestors and looks.

    A wrong answer costs a cadence, not a correctness bug: the worst case is
    typing at full speed in a region an operator had flagged, or paying
    human pacing in one they had not.
    """
    seen: set[int] = set()
    current = hwnd
    while current and current not in seen:
        seen.add(current)
        if is_web_host(winapi.class_name(current)):
            return "web"
        parent = winapi.user32.GetAncestor(wintypes.HWND(current), GA_PARENT)
        current = int(parent) if parent else 0
    return "native"
