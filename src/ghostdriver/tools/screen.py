"""What is on the screen: a picture of the target, and bringing a window
forward on request (D73), the pair to isolation=minimized.

`capture` lived with the discovery tools until that module reached the
400-line guard (#120); a picture is a screen matter, so it moved here.
"""

import base64

from ..backends import UnsupportedPlatform, current
from ..model.element import AccessibleElement
from ..model.result import ErrorKind, GhostdriverError
from ..model.window import WindowNode
from ..surface import Access, SurfaceKind, classify_node
from .core import _error, _physical, _ToolboxCore
from .geometry import _top_level_holding, _top_level_overlapping


def _judge_by_pixels(node: WindowNode) -> dict | None:
    """This control's "state unknowable from window messages, judge by
    pixels" verdict -- absent unless it is exactly that (D#63).

    `capture` has already resolved one node for a locator; classifying it
    costs one region's worth of evidence, not a walk over the whole tree,
    which is why `find` does not do this for every row of a listing (D#51)
    but a single captured control can. Silent for every other verdict --
    native, web, unknown -- because those are not the case `enabled` gets
    wrong (D#51) and flagging them here would be noise with no caller to
    read it, the `actionable`-only-when-False discipline (D66) applied to a
    second field.
    """
    try:
        gather = current().region_evidence
    except UnsupportedPlatform:
        return None
    region = classify_node(node, gather)
    if region.kind is not SurfaceKind.OWNER_DRAWN or region.access is not Access.PIXELS:
        return None
    return {
        "kind": region.kind.value,
        "access": region.access.value,
        "reason": region.reason,
        "note": "state is unknowable from window messages here -- `enabled` "
                "is not proof of anything (D#51) -- so judge this control by "
                "the pixels above",
    }


class ScreenTools(_ToolboxCore):
    """A picture of the target, and the one tool that deliberately interrupts
    the operator -- only when asked."""

    def foreground(self, session_id: str, *, locator: str | None = None) -> dict:
        """Bring a window of the target to the front, on request only.

        The pair to `isolation=minimized`: one option keeps the target out
        of the way, this brings it deliberately forward. Everything else
        this server does works from the background without a raise (a posted
        message needs no foreground), so this exists for the one case that
        cannot: handing the actual click to a tool that uses real input,
        which requires the window frontmost.

        It interrupts the operator -- the window comes forward and the
        keyboard focus moves with it -- so it is never automatic and never a
        side effect of another tool. Interactive tier, and it says whether it
        took the foreground: a background process's SetForegroundWindow can
        be refused by Windows, and `took_foreground: false` is that refusal,
        honestly (D73).
        """
        try:
            session = self.sessions.authorize(session_id, "foreground")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)
        from ..backends import current

        if locator is not None:
            try:
                matches = self._resolve(session, locator, True)
            except ValueError as exc:
                return _error(ErrorKind.NOT_FOUND, str(exc), locator=locator)
            if not matches:
                return _error(ErrorKind.NOT_FOUND, f"nothing matched {locator!r}", locator=locator)
            node = matches[0]
            handle = node.host_handle if isinstance(node, AccessibleElement) else node.handle
        else:
            trees = self._trees(session, all_windows=False)
            if not trees:
                return _error(ErrorKind.NOT_FOUND,
                              f"pid {session.pid} has no main window to bring forward")
            handle = trees[0].handle

        winapi = current().winapi
        took = session.run(lambda: winapi.bring_foreground(handle))
        return {
            "ok": True,
            "took_foreground": bool(took),
            "window": {"class": winapi.class_name(handle),
                       "handle_ephemeral": f"0x{handle:08X}"},
            "warning": ("the target is now at the front and the keyboard focus "
                        "moved with it: the operator's typing goes here until "
                        "they click away. Do this only when a step needs the "
                        "window frontmost, and tell them first."),
            **({} if took else {"note": (
                "Windows refused the foreground from this background process; "
                "the window may only have flashed in the taskbar. Ask the "
                "operator to click it, or try again once nothing is holding "
                "the foreground.")}),
        }

    def capture(
        self,
        session_id: str,
        *,
        locator: str | None = None,
        region: dict | None = None,
        save_as: str | None = None,
        frame: str = "logical",
        scale: float = 1.0,
    ) -> dict:
        """A PNG of the target's window, or of one region of it.

        Given `locator`, the result carries `surface` when -- and only when
        -- the located control paints its own contents: `enabled` cannot
        answer for such a control (D#51), and this says so on the one
        result where classifying it costs nothing extra (D#63).
        """
        try:
            session = self.sessions.authorize(session_id, "capture")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)
        if not isinstance(scale, (int, float)) or isinstance(scale, bool) \
                or not 0 < scale <= 1:
            return _error(ErrorKind.NOT_ACTIONABLE,
                          "scale is the fraction of the window's size to return, "
                          f"above 0 and at most 1; got {scale!r}")
        if frame == "physical" and region is not None:
            scale = current().winapi.display_scale()
            region = {k: round(v / scale) for k, v in region.items()}

        CaptureError = current().CaptureError
        capture_window = current().capture_window

        # Every top-level window of the target and its tree, because the
        # window to *render* is the one that holds the match -- a modal is
        # its own top-level window, and rendering the main window cropped
        # to the modal's rectangle gives the pixels underneath the modal,
        # confidently and wrongly. Measured in the field before this.
        trees = self._trees(session, all_windows=True)
        if not trees:
            return _error(ErrorKind.NOT_FOUND,
                          f"pid {session.pid} has no windows on this desktop")
        main = self._trees(session, all_windows=False)
        target, crop = (main[0] if main else trees[0]), None
        # Set only for a located WindowNode -- the one case classifying it
        # costs nothing extra: `capture` already resolved exactly this node
        # and nothing else (D#63).
        pixel_judged_node: WindowNode | None = None

        if locator:
            try:
                matches = self._resolve(session, locator, True)
            except ValueError as exc:
                return _error(ErrorKind.NOT_FOUND, str(exc), locator=locator)
            if not matches:
                return _error(ErrorKind.NOT_FOUND,
                              f"nothing matched {locator!r}", locator=locator)
            if len(matches) > 1:
                return _error(
                    ErrorKind.AMBIGUOUS,
                    f"{len(matches)} elements matched {locator!r}; capture "
                    "needs exactly one. Add within= or index=.",
                    locator=locator,
                )
            match = matches[0]
            if not isinstance(match, AccessibleElement):
                pixel_judged_node = match
            holder = _top_level_holding(trees, match.handle)
            if holder is None:
                return _error(ErrorKind.NOT_FOUND,
                              f"{locator!r} matched a window no top-level window holds")
            # A region alongside a locator crops within the located window,
            # rather than being silently dropped (D67). Screen coordinates,
            # like every region, so a rect from find() is used as-is.
            if region:
                target, crop = holder, (region["left"], region["top"],
                                        region["right"], region["bottom"])
            else:
                target, crop = holder, match.rect
        elif region:
            crop = (region["left"], region["top"],
                    region["right"], region["bottom"])
            # The window the region lies in, by overlap: a region a caller
            # copied from find() is in screen coordinates, and only the
            # window it overlaps most can render it.
            holder = _top_level_overlapping(trees, crop)
            if holder is None:
                return _error(
                    ErrorKind.NOT_FOUND,
                    f"region {crop} (screen coordinates) overlaps no window of "
                    "the target; rects from find() and describe() are in screen "
                    "coordinates, so pass one of those")
            target = holder

        try:
            png, width, height = session.run(
                lambda: capture_window(target.handle, region=crop, scale=scale))
        except CaptureError as exc:
            return _error(ErrorKind.NOT_ACTIONABLE, str(exc))

        left, top, right, bottom = target.rect
        result = {
            "ok": True,
            "width": width,
            "height": height,
            "mime_type": "image/png",
            # The frame every rectangle in this tool uses, said so a region
            # copied out of one result is known to be valid in another.
            "frame": "screen",
            "rendered": {
                "class": target.class_name,
                "text": target.text,
                "pid": target.pid,
                "handle_ephemeral": f"0x{target.handle:08X}",
                "rect": {"left": left, "top": top, "right": right, "bottom": bottom},
                **_physical(target.rect),
            },
            "base64": base64.b64encode(png).decode("ascii"),
        }
        if pixel_judged_node is not None:
            surface = _judge_by_pixels(pixel_judged_node)
            if surface is not None:
                result["surface"] = surface
        if scale < 1:
            # Said in the result, because every other rect this tool reports
            # is still full size: a pixel here is at (x / scale, y / scale)
            # in those (#120).
            result["scale"] = scale
            result["scale_note"] = (
                "the image is the window at this fraction of its size; a pixel "
                "at (x, y) here is at (x / scale, y / scale) in the screen-"
                "coordinate rects the rest of this tool reports")
        if crop is not None:
            inside = (max(crop[0], left), max(crop[1], top),
                      min(crop[2], right), min(crop[3], bottom))
            if inside != tuple(crop):
                result["clipped_to_window"] = True
        result.update(self._frame_note())
        if save_as is not None:
            from ..operator import save_capture

            try:
                result["saved_to"] = str(save_capture(save_as, png))
            except (OSError, ValueError) as exc:
                result["saved_to"] = None
                result["save_error"] = str(exc)
        return result
