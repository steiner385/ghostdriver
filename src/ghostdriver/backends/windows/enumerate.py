"""Build platform-neutral WindowNode trees from live windows."""

from ctypes import wintypes

from ...model.window import WindowNode
from . import winapi
from .text import read_window_text


def top_level_windows(pid: int) -> list[int]:
    """Every top-level window belonging to `pid`, in Z-order."""
    found: list[int] = []

    def callback(hwnd, _lparam):
        if winapi.window_pid(hwnd) == pid:
            found.append(hwnd)
        return True

    winapi.user32.EnumWindows(winapi.WNDENUMPROC(callback), 0)
    return found


def direct_children(hwnd: int) -> list[int]:
    """Immediate children only.

    EnumChildWindows returns every descendant flattened, which would place
    grandchildren at depth 1 and make ancestor scoping meaningless. Walking
    GW_CHILD then GW_HWNDNEXT preserves the real tree.
    """
    out: list[int] = []
    child = winapi.user32.GetWindow(wintypes.HWND(hwnd), winapi.GW_CHILD)
    while child:
        out.append(child)
        child = winapi.user32.GetWindow(wintypes.HWND(child), winapi.GW_HWNDNEXT)
    return out


def build_tree(hwnd: int, *, max_depth: int = 32) -> WindowNode:
    """Recursively build a WindowNode for `hwnd` and its descendants."""

    def build(handle: int, depth: int) -> WindowNode:
        children: tuple[WindowNode, ...] = ()
        if depth < max_depth:
            children = tuple(
                build(c, depth + 1) for c in direct_children(handle)
            )
        raw_text = read_window_text(handle)
        return WindowNode(
            handle=handle,
            class_name=winapi.class_name(handle),
            text=raw_text or "",
            rect=winapi.window_rect(handle),
            visible=bool(winapi.user32.IsWindowVisible(wintypes.HWND(handle))),
            enabled=bool(winapi.user32.IsWindowEnabled(wintypes.HWND(handle))),
            pid=winapi.window_pid(handle),
            children=children,
            responsive=raw_text is not None,
        )

    return build(hwnd, 0)


def enumerate_process(pid: int) -> list[WindowNode]:
    """One tree per top-level window of `pid`."""
    return [build_tree(h) for h in top_level_windows(pid)]
