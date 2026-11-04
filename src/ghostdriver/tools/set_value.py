"""set_value: replace a field's contents and check what actually landed.

Its own module because it carries the most machinery of any single verb --
the two silent-failure checks (the field takes a short value; the
application shows one it never received), and the tier-4 live-commit path
(D#111) that is the only way a value reaches a toolkit like wxGTK3. Kept out
of `actuation.py` so both stay under the tool-module limit (D60).
"""

from ..actuate import Condition
from ..model.element import AccessibleElement
from ..model.result import ErrorKind
from .acting import _ActingCore
from .core import _error
from .expect import verify_window

ELEMENT_NO_VALUE = (
    "this element publishes no value to replace; to type at its caret use "
    "type_text, or name a field (type=Edit ...)"
)


class SetValueTools(_ActingCore):
    """Replacing a field's value, with a check that it landed and committed."""

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

        Two silent failures, both checked. **The field may not take all of
        it:** typing goes through the control's own input handling, so a
        length limit or a mask applies as it would to a person (measured at
        ~20 chars on a field declaring 30000). The display is read back; a
        field that reformats (a date mask) fails the first compare -- pass
        `expect_text` with the reformatted value. **The application may not
        accept it:** a field can show a value it never received (the truth
        is in a mirror label, a grid cell, a change log), so `expect` names
        where to look, and only then is it `verified: "committed"`.
        """
        prepared, failure = self._prepared(
            session_id, "set_value", locator, all_windows, cadence
        )
        if failure is not None:
            return failure
        refusal = self._refuse_if_protected(prepared.node, "type into")
        if refusal is not None:
            return refusal

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

        # Whether the field shows the wanted value.
        #
        # An *element* publishes its own value, so it is compared directly --
        # `confirms_value` takes a window handle and an element's handle is
        # its *host* window, which holds different text (this is what broke
        # the web set_value path). A *window* field is asked through
        # `confirms_value`, which compares inside the backend and returns a
        # yes/no: that is what lets a withheld field (D#34b, D#105) verify at
        # all, where reading `current_display()` would answer None and report
        # every successful write as a failure.
        def shows() -> bool:
            if element is not None:
                return (current_display() or "") == wanted
            confirms_value = current().confirms_value
            return prepared.session.run(
                lambda: confirms_value(handle, wanted)) is True

        try:
            commit, described = self._expectation(prepared.session, expect,
                                                  carries_text=True)
        except ValueError as exc:
            return _error(ErrorKind.NOT_FOUND, f"expect is unusable: {exc}")
        if commit is None:
            after = Condition(shows, f"the field shows {wanted!r}")
        else:
            after = Condition(
                lambda: shows() and commit.check(),
                f"the field shows {wanted!r} and {commit.description}",
            )

        # A live session may commit on the operator's own display -- the
        # real-Enter path a toolkit like wxGTK3 needs (D#111) -- which is
        # tier 4, off the default ladder. The interference watch is armed
        # around it, so a foreground or pointer move the synchronous guard
        # misses is still reported (D28).
        live = prepared.session.live_window
        live_kw = {"live_window": live} if live else {}
        tiers = None
        if live:
            from ..actuate import Tier
            tiers = (Tier.UIA_PATTERN, Tier.SYNTHETIC_INPUT)

        insert_first = prepared.session.profile.inserts_first(
            getattr(prepared.node, "class_name", None))
        attempts = (
            verbs.set_text_element(element, text, cadence=prepared.cadence,
                                   allow_pattern=commit is not None,
                                   insert_first=insert_first, **live_kw)
            if element is not None else
            verbs.set_text(handle, text, cadence=prepared.cadence,
                           allow_pattern=commit is not None,
                           insert_first=insert_first, **live_kw)
        )

        watch = None
        if live:
            from ..backends import current as _backend
            watch = _backend().InterferenceWatch(
                prepared.session.pid,
                family=lambda: self._tree_pids(prepared.session))
            prepared.session.run(watch.start)
        try:
            result = self._perform(prepared.session, attempts,
                expect_before=verbs.unblocked(handle),
                expect_after=after,
                verify_timeout_s=verify_window(expect),
                tiers=tiers,
            )
        finally:
            if watch is not None:
                watch.stop()

        self._remember(session_id, "set_value", locator, prepared, result)
        shown = current_display()
        reported = self._reported(
            result, prepared, locator,
            verified=("committed" if commit is not None and result.ok
                      else "display" if result.ok else "none"),
            display=shown,
            expected=described,
        )
        if watch is not None:
            events = watch.events()
            if events:
                reported["disturbances"] = list(reported.get("disturbances") or []) + events
                if not result.ok:
                    reported["live_aborted"] = (
                        "the operator's foreground or pointer moved while "
                        "committing, so the live action was stopped and nothing "
                        "was committed (D#111). Nothing was forced onto their "
                        "desktop; retry when the target is settled in front.")
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

