"""Actuation: click, type_text, send_keys. (set_value is in set_value.py.)"""


from ..actuate import Tier
from ..model.element import AccessibleElement
from ..model.result import ErrorKind
from .acting import _ActingCore
from .core import (
    _error,
)
from .expect import verify_window
from .guidance import REQUIRE_ACTIVE_REFUSAL, TYPE_TEXT_MISS_HINT


class ActuationTools(_ActingCore):
    """Acting on one element under the tier ladder: click, type, send keys."""

    def click(
        self,
        session_id: str,
        locator: str,
        *,
        all_windows: bool = False,
        expect: dict | str | None = None,
        button: str = "left",
        modifiers: list[str] | None = None,
        at: dict | None = None,
        count: int = 1,
        frame: str = "logical",
        require_active: bool = False,
        hover: bool | None = None,
        menu_by_keyboard: bool | None = None,
    ) -> dict:
        """Actuate one control.

        `expect` names what should be true afterwards -- a locator (and
        text), or {changed: true} for a whole-surface effect (D77); without
        it the result claims only that the input was delivered. `at` is a
        point inside a region that paints its own rows. `count` 2
        double-clicks; `button` is left/right/middle (a right-click's menu
        is a new top-level, all_windows=true reaches it); `modifiers` (ctrl,
        shift) ride the message flags -- `expect` tells whether they landed.
        `require_active` refuses when the window is not active (D67).
        `hover` posts the VCL mouse-enter notification before the pair, for
        a control that acts on a click only while it believes the mouse is
        over it; None lets the profile's `hover_before_click` decide (#133).
        `menu_by_keyboard` chooses a popup-menu item through the menu's own
        keyboard route before the posted pair, for a menu that hit-tests the
        real pointer; None lets the profile's `menus_by_keyboard` decide (#189).
        """
        prepared, failure = self._prepared(
            session_id, "click", locator, all_windows, None
        )
        if failure is not None:
            return failure

        from ..backends import current
        verbs = current().verbs

        try:
            after, described = self._expectation(prepared.session, expect)
        except ValueError as exc:
            return _error(ErrorKind.NOT_FOUND, f"expect is unusable: {exc}")
        held = list(modifiers or [])
        try:
            from ..backends import current
            current().button_pair(button, held)
        except ValueError as exc:
            return _error(ErrorKind.NOT_ACTIONABLE, str(exc), locator=locator)
        if count not in (1, 2):
            return _error(ErrorKind.NOT_ACTIONABLE,
                          f"count must be 1 or 2, not {count!r}", locator=locator)
        point = None
        if frame not in ("logical", "physical"):
            return _error(ErrorKind.NOT_ACTIONABLE,
                          f"frame must be 'logical' or 'physical', not {frame!r}", locator=locator)
        if at is not None:
            try:
                point = (int(at["x"]), int(at["y"]))
            except (KeyError, TypeError, ValueError):
                return _error(ErrorKind.NOT_ACTIONABLE,
                              "at must be {x, y} in pixels inside the element", locator=locator)
            if frame == "physical":
                point = self._to_logical(point)
            if (refusal := self._denied_region(prepared.session, self._aim(prepared.node, point), locator)):
                return refusal
            left, top, right, bottom = prepared.node.rect
            width, height = right - left, bottom - top
            if not (0 <= point[0] < max(width, 1) and 0 <= point[1] < max(height, 1)):
                return _error(
                    ErrorKind.NOT_ACTIONABLE,
                    f"at={point} is outside the element, which is {width}x{height}",
                    locator=locator)
        node_class = getattr(prepared.node, "class_name", None)
        hover_on = (bool(hover) if hover is not None
                    else prepared.session.profile.wants_hover(node_class))
        keys_first = (bool(menu_by_keyboard) if menu_by_keyboard is not None
                      else prepared.session.profile.menus_by_keyboard)
        attempts = (verbs.click_element(prepared.node, button=button, modifiers=held,
                                        at=point, count=count, hover=hover_on,
                                        menu_by_keyboard=keys_first)
                    if isinstance(prepared.node, AccessibleElement)
                    else verbs.click(prepared.node.handle, button=button, modifiers=held,
                                     at=point, count=count, hover=hover_on))
        pinned = prepared.session.profile.pins_to_posted(node_class)
        if pinned is not None:
            # The profile says this class answers the posted click and
            # nothing else (#122): the pattern rung is not tried, so it
            # cannot cost its timeout or deliver a second click.
            attempts = [a for a in attempts if a.tier == Tier.WINDOW_MESSAGE]
        if require_active:
            before = self._focus_report(prepared)
            if before.get("target_window_active") is False:
                refusal = _error(ErrorKind.NOT_ACTIONABLE, REQUIRE_ACTIVE_REFUSAL,
                                 locator=locator)
                refusal["focus"] = before
                return refusal
        delivered = self._delivery(prepared, point)
        # A "changed" postcondition (the surface moving, not a named
        # control) can take longer than a control appearing -- a palette
        # docks a few seconds after the click (D77) -- so it gets a longer
        # verify window, the caller's timeout_s or six seconds.
        result = self._perform(prepared.session,
            attempts,
            expect_before=verbs.unblocked(prepared.node.handle),
            expect_after=after,
            verify_timeout_s=verify_window(expect),
        )
        self._remember(session_id, "click", locator, prepared, result)
        focus = self._focus_report(prepared)
        inactive = focus.get("target_window_active") is False
        verified = ("effect" if after is not None and result.ok
                    else "delivered_inactive" if inactive and result.ok
                    else "delivery_only")
        reported = self._reported(
            result, prepared, locator,
            verified=verified,
            expected=described,
            button=button, modifiers=held, at=point, count=count,
            focus=focus,
            **({"route_pinned": f"posted only: profile posted_click_only matches {pinned!r}"}
               if pinned is not None else {}),
            **({"hover": ("CM_MOUSEENTER posted before the click, "
                          + ("as asked" if hover is not None
                             else "because the profile's hover_before_click names "
                                  f"{node_class!r}"))}
               if hover_on else {}),
            **delivered,
        )
        note = prepared.session.profile.note_for(node_class)
        if note:
            reported["note"] = note
        acted = any(d.get("change") in ("window_appeared", "window_disappeared")
                    for d in result.disturbances)
        if inactive and after is None and result.ok and not acted:
            # ok:true (delivered), but a status-skimmer must see it (D67).
            # Suppressed when a window appeared or vanished around the click:
            # that is the click plainly having done something, so the
            # inactive-window caveat would be noise (D77).
            reported["warning"] = (
                "delivered to a window that is not its thread's active window: "
                "a focus-checking control will have ignored this, and nothing "
                "here confirms an effect. Pass expect (a locator, or "
                "{changed: true}), require_active=true, or hand it to "
                "await_human or a tool that activates windows."
            )
        return reported

    def type_text(
        self,
        session_id: str,
        locator: str,
        text: str,
        *,
        all_windows: bool = False,
        cadence: str | None = None,
        expect: dict | str | None = None,
    ) -> dict:
        """Type into a control at the caret, without clearing it first.

        `set_value` is what replaces a field. This appends, inserts, or
        types into something that is not a field at all -- a grid cell in
        edit mode, a search box that filters as it goes.
        """
        prepared, failure = self._prepared(
            session_id, "type_text", locator, all_windows, cadence
        )
        if failure is not None:
            return failure
        refusal = self._refuse_if_protected(prepared.node, "type into")
        if refusal is not None:
            return refusal

        from ..backends import current
        verbs = current().verbs

        try:
            after, described = self._expectation(prepared.session, expect)
        except ValueError as exc:
            return _error(ErrorKind.NOT_FOUND, f"expect is unusable: {exc}")
        attempts = (
            verbs.type_text_element(prepared.node, text, cadence=prepared.cadence)
            if isinstance(prepared.node, AccessibleElement) else
            verbs.send_keys(prepared.node.handle, list(text), cadence=prepared.cadence)
        )
        result = self._perform(prepared.session, attempts,
            expect_before=verbs.unblocked(prepared.node.handle),
            expect_after=after,
            verify_timeout_s=verify_window(expect),
        )
        self._remember(session_id, "type_text", locator, prepared, result)
        reported = self._reported(
            result, prepared, locator,
            verified=("effect" if after is not None and result.ok
                      else "delivery_only"),
            expected=described,
        )
        if not result.ok:
            reported["hint"] = TYPE_TEXT_MISS_HINT
        return reported

    def send_keys(
        self,
        session_id: str,
        locator: str,
        keys: list[str],
        *,
        all_windows: bool = False,
        cadence: str | None = None,
        expect: dict | str | None = None,
    ) -> dict:
        """Send named keys to a control.

        For keys whose meaning is the key rather than the character:
        `enter`, `tab`, `escape`, `backspace`, `delete`. On this class of
        target these often reach things the mouse cannot -- committing a
        grid row, dismissing a dialog whose buttons ignore clicks.
        """
        prepared, failure = self._prepared(
            session_id, "send_keys", locator, all_windows, cadence
        )
        if failure is not None:
            return failure
        from ..backends import current
        verbs = current().verbs
        from ..backends import current
        NAMED_KEYS = current().NAMED_KEYS

        # Named keys carry nothing, so `tab` out of a password field a
        # person has filled in is fine. A character is the credential.
        if any(len(k) == 1 for k in keys):
            refusal = self._refuse_if_protected(prepared.node,
                                                "send characters to")
            if refusal is not None:
                return refusal

        editing = current_edit_actions()
        unknown = [k for k in keys
                   if k.lower() not in NAMED_KEYS and k.lower() not in editing
                   and len(k) != 1]
        if unknown:
            combos = [k for k in unknown if "+" in k]
            return _error(
                ErrorKind.NOT_ACTIONABLE,
                f"unknown key name(s) {unknown}; expected a single character, "
                f"one of {sorted(NAMED_KEYS)}, or an editing action "
                f"{sorted(editing)}."
                + (" A posted keystroke carries no modifier state, so ctrl+ and "
                   "shift+ combinations cannot be sent; for an edit field use "
                   "select-all, paste, copy, cut or undo, which are the messages "
                   "those combinations become inside the control."
                   if combos else ""),
            )

        try:
            after, described = self._expectation(prepared.session, expect)
        except ValueError as exc:
            return _error(ErrorKind.NOT_FOUND, f"expect is unusable: {exc}")
        result = self._perform(prepared.session,
            (verbs.send_keys_element(prepared.node, keys, cadence=prepared.cadence)
             if isinstance(prepared.node, AccessibleElement) else
             verbs.send_keys(prepared.node.handle, keys,
                            cadence=prepared.cadence)),
            expect_before=verbs.unblocked(prepared.node.handle),
            expect_after=after,
            verify_timeout_s=verify_window(expect),
        )
        self._remember(session_id, "send_keys", locator, prepared, result)
        return self._reported(
            result, prepared, locator,
            verified=("effect" if after is not None and result.ok
                      else "delivery_only"),
            expected=described,
            keys=keys,
        )


def current_edit_actions() -> dict:
    from ..backends import current

    return dict(current().EDIT_ACTIONS)
