"""Denied places: an actuation aimed inside a profile-named region is refused (D72)."""

from ..model.element import AccessibleElement
from ..model.result import ErrorKind
from .core import _error, _ToolboxCore


class _DenyCore(_ToolboxCore):
    """Where an actuation lands, and whether the profile forbids acting there."""

    def _aim(self, node, point) -> tuple[int, int]:
        """Where an actuation on `node` lands, on screen: `point` inside it
        (client-relative for a window, from the top-left for an element), or
        its centre."""
        from ..backends import current

        winapi = current().winapi
        if isinstance(node, AccessibleElement):
            left, top, right, bottom = node.rect
            if point is None:
                return (left + right) // 2, (top + bottom) // 2
            return left + int(point[0]), top + int(point[1])
        client = winapi.client_centre(node.handle) if point is None else (int(point[0]), int(point[1]))
        return winapi.client_to_screen(node.handle, client)

    def _denied_region(self, session, aim: tuple[int, int], locator: str) -> dict | None:
        """The profile's denied places: refuse when the aim lands in one.

        A grid cell, a painted toolbar button, a row in an owner-drawn list
        have no caption and no identity for the denylist to match; they have
        a place inside a window the profile can name (D72). Each entry's
        window is resolved now, so the region follows the window wherever
        it is.
        """
        from ..backends import current

        winapi = current().winapi
        for entry in session.profile.deny_regions:
            try:
                matches = self._resolve(session, entry["within"], True)
            except ValueError:
                continue
            region = entry["region"]
            for match in matches:
                if isinstance(match, AccessibleElement):
                    ox, oy = match.rect[0], match.rect[1]
                else:
                    ox, oy = winapi.client_to_screen(match.handle, (0, 0))
                left, top = ox + int(region["left"]), oy + int(region["top"])
                right, bottom = ox + int(region["right"]), oy + int(region["bottom"])
                if left <= aim[0] < right and top <= aim[1] < bottom:
                    note = entry.get("note") or "no note"
                    return _error(
                        ErrorKind.DENIED_BY_POLICY,
                        f"refused: the point {aim} lies in a denied region of "
                        f"{entry['within']!r} ({note}); the profile's denylist "
                        "forbids acting there",
                        locator=locator)
        return None
