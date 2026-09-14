"""Which top-level window a handle or a screen rectangle belongs to.

Pure geometry over the window trees, plus one read of the desktop's
z-order for the rectangle case (#136). Shared by the capture tool and the
core's region checks; its own module so neither has to import the other.
"""


def _top_level_holding(trees, handle: int):
    """The top-level window whose tree contains `handle`."""
    for tree in trees:
        for node in tree.walk():
            if node.handle == handle:
                return tree
    return None


def _top_level_overlapping(trees, region):
    """The top-level window whose pixels the region shows, or None.

    The window under the region's centre in the desktop's z-order wins
    when it is one of the candidates: that is what a person sees there,
    and a region over an open context menu once rendered the form beneath
    it because the menu and the form overlapped the region equally (#136).
    Otherwise most overlap first; among equals, the *smaller* window -- a
    modal lies entirely inside its owner's rectangle, and the modal, being
    smaller and on top, is the one a person sees there.
    """
    seen = _root_window_at(((region[0] + region[2]) // 2, (region[1] + region[3]) // 2))
    if seen:
        for tree in trees:
            left, top, right, bottom = tree.rect
            if tree.handle == seen and left < region[2] and right > region[0] \
                    and top < region[3] and bottom > region[1]:
                return tree
    best, best_key = None, None
    for tree in trees:
        left, top, right, bottom = tree.rect
        w = min(right, region[2]) - max(left, region[0])
        h = min(bottom, region[3]) - max(top, region[1])
        area = w * h if w > 0 and h > 0 else 0
        if area <= 0:
            continue
        key = (area, -((right - left) * (bottom - top)))
        if best_key is None or key > best_key:
            best, best_key = tree, key
    return best


def _root_window_at(point) -> int:
    """The top-level window the desktop shows at screen `point`, or 0 on a
    backend that cannot say. A read of the z-order; nothing moves."""
    from ..backends import current

    winapi = getattr(current(), "winapi", None)
    if winapi is None or not hasattr(winapi, "window_from_point"):
        return 0
    try:
        hit = winapi.window_from_point(point[0], point[1])
        return winapi.root_window(hit) if hit else 0
    except Exception:
        return 0
