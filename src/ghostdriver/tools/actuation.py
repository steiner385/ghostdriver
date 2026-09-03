"""Actuation: click, set_value, type_text, send_keys."""


from ..model.element import AccessibleElement
from ..model.result import ErrorKind
from .core import (
    _error,
    _ToolboxCore,
)

ELEMENT_NO_VALUE = (
    "this element publishes no value to replace; to type at its caret use "
    "type_text, or name a field (type=Edit ...)"
)


class ActuationTools(_ToolboxCore):
    """Acting on one element under the tier ladder: click, set a value, type, send keys."""

    def click(
        self,
        session_id: str,
        locator: str,
        *,
        all_windows: bool = False,
        expect: dict | None = None,
    ) -> dict:
        """Actuate one control.

        `expect` names something that should be true afterwards -- a locator
        and the text it should then have. Without it the result reports that
        the input was delivered and claims nothing about its effect, because
        on this class of target those are genuinely different statements.
        """
        prepared, failure = self._prepared(
            session_id, "click", locator, all_windows, None
        )
        if failure is not None:
            return failure

        from ..backends.windows import verbs

        try:
            after, described = self._expectation(prepared.session, expect)
        except ValueError as exc:
            return _error(ErrorKind.NOT_FOUND, f"expect is unusable: {exc}")
        attempts = (verbs.click_element(prepared.node)
                    if isinstance(prepared.node, AccessibleElement)
                    else verbs.click(prepared.node.handle))
        result = self._perform(prepared.session,
            attempts,
            expect_before=verbs.unblocked(prepared.node.handle),
            expect_after=after,
        )
        self._remember(session_id, "click", locator, prepared, result)
        return self._reported(
            result, prepared, locator,
            verified=("effect" if after is not None and result.ok
                      else "delivery_only"),
            expected=described,
        )

    def set_value(
        self,
        session_id: str,
        locator: str,
        text: str,
        *,
        all_windows: bool = False,
        expect_text: str | None = None,
        expect: dict | None = None,
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
        value the application never received. Nothing here can see that --
        it shows up in a mirror label, a grid cell, a change log -- so
        `expect` is how a caller names where to look. Only then does the
        result say `verified: "committed"`.

        With `expect`, a pattern-based tier is offered first and falls
        through if it does not commit. Without it, this types and only
        types: an unverifiable shortcut whose failure is invisible is not
        worth the milliseconds it saves.
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
        from ..backends.windows import verbs
        from ..backends.windows.text import read_window_text

        handle = prepared.node.handle
        wanted = text if expect_text is None else expect_text
        element = prepared.node if isinstance(prepared.node, AccessibleElement) else None
        if element is not None and "Value" not in element.patterns:
            return _error(ErrorKind.NOT_ACTIONABLE, ELEMENT_NO_VALUE, locator=locator)

        def current_display() -> str | None:
            # An element's display is its value on the surface, re-read; a
            # window's is what it answers to a text query.
            if element is not None:
                from ..backends.windows.elements import _current_value
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
                "it should end up showing"
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
        expect: dict | None = None,
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

        from ..backends.windows import verbs

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
        expect: dict | None = None,
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
        from ..backends.windows import verbs
        from ..backends.windows.input import NAMED_KEYS

        # Named keys carry nothing, so `tab` out of a password field a
        # person has filled in is fine. A character is the credential.
        if any(len(k) == 1 for k in keys):
            refusal = self._refuse_if_protected(prepared.node,
                                                "send characters to")
            if refusal is not None:
                return refusal

        unknown = [k for k in keys
                   if k.lower() not in NAMED_KEYS and len(k) != 1]
        if unknown:
            return _error(
                ErrorKind.NOT_ACTIONABLE,
                f"unknown key name(s) {unknown}; expected a single character "
                f"or one of {sorted(NAMED_KEYS)}",
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
