"""Actuation: click, set_value, type_text, send_keys."""


from ..model.element import AccessibleElement
from ..model.result import ErrorKind
from .acting import _ActingCore
from .core import (
    _error,
)

ELEMENT_NO_VALUE = (
    "this element publishes no value to replace; to type at its caret use "
    "type_text, or name a field (type=Edit ...)"
)


class ActuationTools(_ActingCore):
    """Acting on one element under the tier ladder: click, set a value, type, send keys."""

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
    ) -> dict:
        """Actuate one control.

        `expect` names something that should be true afterwards -- a locator
        and the text it should then have. Without it the result reports that
        the input was delivered and claims nothing about its effect, because
        on this class of target those are genuinely different statements.

        `at` is a point {x, y} inside the element, for a region that paints
        its own rows: a capture shows where the row is, this clicks there,
        nothing is activated. `count` 2 double-clicks; `button` is left,
        right or middle (a right-click's context menu is a new top-level
        window, all_windows=true reaches it); `modifiers` (ctrl, shift)
        ride the message's own flags, which a target that reads them sees
        and one that asks the keyboard does not -- `expect` tells which.
        `require_active` refuses when the window is not active rather than
        delivering a click a focus-checking control would drop.
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
            left, top, right, bottom = prepared.node.rect
            width, height = right - left, bottom - top
            if not (0 <= point[0] < max(width, 1) and 0 <= point[1] < max(height, 1)):
                return _error(
                    ErrorKind.NOT_ACTIONABLE,
                    f"at={point} is outside the element, which is {width}x{height}",
                    locator=locator)
        attempts = (verbs.click_element(prepared.node, button=button, modifiers=held,
                                        at=point, count=count)
                    if isinstance(prepared.node, AccessibleElement)
                    else verbs.click(prepared.node.handle, button=button, modifiers=held,
                                     at=point, count=count))
        if require_active:
            before = self._focus_report(prepared)
            if before.get("target_window_active") is False:
                refusal = _error(
                    ErrorKind.NOT_ACTIONABLE,
                    "require_active: the target's window is not active, so a "
                    "focus-checking control would ignore this click; nothing "
                    "delivered. Hand it to a person (await_human) or a tool that "
                    "activates windows, or drop require_active.", locator=locator)
                refusal["focus"] = before
                return refusal
        delivered = self._delivery(prepared, point)
        result = self._perform(prepared.session,
            attempts,
            expect_before=verbs.unblocked(prepared.node.handle),
            expect_after=after,
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
            **delivered,
        )
        if inactive and after is None and result.ok:
            # ok:true (delivered), but a status-skimmer must see it (D67).
            reported["warning"] = (
                "delivered to a window that is not its thread's active window: "
                "a control that checks focus will have ignored this click, and "
                "nothing here confirms an effect. Pass expect to confirm one, "
                "require_active=true to refuse instead of delivering blind, or "
                "hand the step to a person (await_human) or to a tool that "
                "activates windows, with the coordinates found here."
            )
        return reported

    def set_value(
        self,
        session_id: str,
        locator: str,
        text: str,
        *,
        all_windows: bool = False,
        expect_text: str | None = None,
        expect: dict | str | None = None,
        cadence: str | None = None,
    ) -> dict:
        """Replace a field\'s contents, and check what actually landed.

        Two different things can go wrong here and both are silent, so both
        are checked rather than assumed.

        **The field may not have taken all of it.** Typing goes through the
        control\'s own input handling, so a length limit or a mask applies
        exactly as it would to a person -- measured at about twenty
        characters on a field whose declared limit was thirty thousand. The
        display is therefore always read back and compared. A field that
        reformats what it is given (a date mask turning 01012026 into
        01/01/2026) will fail that comparison the first time; pass
        `expect_text` with the reformatted value and the reformatting
        becomes something asserted rather than something skimmed past.

        **The application may not have accepted it.** A field can display a
        value the application never received -- it shows in a mirror label,
        a grid cell, a change log -- so `expect` names where to look, and
        only then is the result `verified: "committed"`. With `expect` a
        pattern tier is tried first; without it this only types, an
        unverifiable shortcut not worth the milliseconds.
        """
        prepared, failure = self._prepared(
            session_id, "set_value", locator, all_windows, cadence
        )
        if failure is not None:
            return failure
        refusal = self._refuse_if_protected(prepared.node, "type into")
        if refusal is not None:
            return refusal

        from ..actuate import Condition
        from ..backends import current
        verbs = current().verbs
        from ..backends import current
        read_window_text = current().read_window_text

        handle = prepared.node.handle
        wanted = text if expect_text is None else expect_text
        element = prepared.node if isinstance(prepared.node, AccessibleElement) else None
        if element is not None and "Value" not in element.patterns:
            return _error(ErrorKind.NOT_ACTIONABLE, ELEMENT_NO_VALUE, locator=locator)

        def current_display() -> str | None:
            # An element's display is its value on the surface, re-read; a
            # window's is what it answers to a text query.
            if element is not None:
                from ..backends import current
                _current_value = current()._current_value
                return prepared.session.run(lambda: _current_value(element))
            return read_window_text(handle)

        shows = lambda: (current_display() or "") == wanted  # noqa: E731

        try:
            commit, described = self._expectation(prepared.session, expect)
        except ValueError as exc:
            return _error(ErrorKind.NOT_FOUND, f"expect is unusable: {exc}")
        if commit is None:
            after = Condition(shows, f"the field shows {wanted!r}")
        else:
            after = Condition(
                lambda: shows() and commit.check(),
                f"the field shows {wanted!r} and {commit.description}",
            )

        attempts = (
            verbs.set_text_element(element, text, cadence=prepared.cadence,
                                   allow_pattern=commit is not None)
            if element is not None else
            verbs.set_text(handle, text, cadence=prepared.cadence,
                           allow_pattern=commit is not None)
        )
        result = self._perform(prepared.session, attempts,
            expect_before=verbs.unblocked(handle),
            expect_after=after,
        )

        self._remember(session_id, "set_value", locator, prepared, result)
        shown = current_display()
        reported = self._reported(
            result, prepared, locator,
            verified=("committed" if commit is not None and result.ok
                      else "display" if result.ok else "none"),
            display=shown,
            expected=described,
        )
        if not result.ok and shown is not None and shown != wanted:
            reported["error"]["message"] += (
                f"; the field shows {shown!r}, not {wanted!r}. If the control "
                "reformats what it is given, pass expect_text with the value "
                "it should end up showing. If characters went missing, typing "
                "and then inserting the value whole were both tried; a target that drops typed "
                "characters is worth recording with record_input_sensitivity"
            )
            if shown == "" and wanted and self._renders_content(prepared):
                reported["read_unreliable"] = True
                reported["error"]["message"] += (
                    ". The control answers empty to a text query but renders "
                    "content, so the value may well have landed and the read "
                    "path be the failure: verify by capture, or through the "
                    "value's effect elsewhere, before retrying"
                )
            elif shown == "" and wanted:
                appeared = [d.get("class") or d.get("kind") for d in result.disturbances
                            if isinstance(d, dict)]
                seen = f" (a window appeared while typing: {appeared[:3]})" if appeared else ""
                reported["error"]["message"] += (
                    ". The field is now EMPTY: the clear took and the text did "
                    f"not{seen}. A field with an autocomplete or history list "
                    "often behaves so, the list taking the keystrokes. Try click "
                    "then type_text, which does not clear first, and check with "
                    "read"
                )
        if commit is None and result.ok:
            reported["unverified"] = (
                "the field displays this value; whether the application "
                "accepted it was not checked. Pass expect naming where the "
                "committed value appears to check it"
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
        )
        self._remember(session_id, "type_text", locator, prepared, result)
        return self._reported(
            result, prepared, locator,
            verified=("effect" if after is not None and result.ok
                      else "delivery_only"),
            expected=described,
        )

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
