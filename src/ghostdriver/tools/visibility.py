"""Whether a window is actually clickable where its rect says (#61).

A rect is where a window *would* paint, not whether a person can see it now.
Occluded, minimized and fully visible all report a plausible rect, so a click
posted to a covered or minimized window can land on the glass in front -- the
field report's two blind clicks. This reports that state; it never fails or
refuses on it (a disturbance is information, not a verdict, D28), and it never
raises or activates a window to find out (D55). Split from `core` for the
400-line tool-module limit (D60); `DiscoveryTools` mixes it in.
"""

from ..model.element import AccessibleElement
from .core import _ToolboxCore


class _VisibilityCore(_ToolboxCore):
    """The occlusion read `find` attaches to a match when it is not visible."""

    def _obscured(self, session, node, cache: dict) -> dict | None:
        """The window `node` lives in, when it is not clickable where its rect
        says: minimized, or its centre covered by a window that is not the
        target's own. None when it looks visible -- so a caller reads a flag
        only when it means something (the `actionable`-only-when-False rule).

        Cached per root window: a find of many controls in one window costs
        one z-order read, not one per control.
        """
        from ..backends import current

        winapi = current().winapi
        handle = node.host_handle if isinstance(node, AccessibleElement) else node.handle
        try:
            root = winapi.root_window(handle)
        except Exception:
            return None
        if root in cache:
            return cache[root]

        def read() -> dict | None:
            if winapi.is_minimized(root):
                return {"state": "minimized",
                        "note": "the window is minimized: its rect is not where "
                                "it paints, and a posted click there will not "
                                "land. restore or foreground it first"}
            left, top, right, bottom = winapi.window_rect(root)
            if right <= left or bottom <= top:
                return None
            cx, cy = (left + right) // 2, (top + bottom) // 2
            hit = winapi.window_from_point(cx, cy)
            if not hit or winapi.root_window(hit) == root:
                return None  # nothing there, or the window owns its own centre
            # Something else is on top at the centre. A window of the target's
            # own process tree is the application's own -- a dialog it raised --
            # not an occlusion worth warning about.
            if winapi.window_pid(hit) in self._tree_pids(session):
                return None
            top_hit = winapi.root_window(hit)
            return {"state": "covered",
                    "by": {"class": winapi.class_name(top_hit),
                           "handle_ephemeral": f"0x{top_hit:08X}"},
                    "note": "another window covers this one at its centre, so a "
                            "click posted to its rect may reach the window on "
                            "top. a centre-point check, not a full-coverage test"}

        try:
            result = session.run(read)
        except Exception:
            result = None
        cache[root] = result
        return result
