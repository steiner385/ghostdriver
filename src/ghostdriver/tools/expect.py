"""How to tell an action worked: the postcondition an `expect` becomes (D67, D77)."""

from ..model.element import AccessibleElement
from ..model.locator import Locator
from .core import _ToolboxCore


class _ExpectCore(_ToolboxCore):
    """Turns a caller's `expect` into a re-checked condition."""

    def _expectation(self, session, expect: dict | str | None):
        """Turn a caller\'s `expect` into a condition, re-resolved each time.

        Re-resolved, not a held handle: the element that proves an action
        worked may not exist until it has. The locator is parsed here,
        before anything is sent, so a bad one is an error, not an unmet
        condition -- the two look identical outside and mean opposites.
        """
        if not expect:
            return None, None
        if isinstance(expect, str):
            # `expect` names how to tell the action worked. The common case
            # is "this locator is now present", and a bare string is the
            # natural way to say it -- the name invites a sentence, so at
            # least let a locator string through (D67).
            expect = {"locator": expect}

        from ..actuate import Condition
        from ..backends import current
        read_window_text = current().read_window_text

        if expect.get("changed"):
            # No control to name: the effect is the *surface* moving -- a
            # palette docking, a pane appearing -- seconds after a click on
            # an owner-drawn control that publishes no postcondition (D77).
            # The baseline is taken now, before the action; the condition
            # holds when the shape digest surfaces already computes moves.
            surfaces = self.surfaces  # type: ignore[attr-defined]
            all_windows = bool(expect.get("all_windows", False))
            baseline = surfaces(session.session_id, all_windows=all_windows).get("shape_digest")

            def moved() -> bool:
                return surfaces(session.session_id, all_windows=all_windows).get("shape_digest") != baseline

            return Condition(moved, "the target's surface changed"), "the target's surface changed"

        where = expect.get("locator")
        wanted = expect.get("text")
        selected = expect.get("selected")
        if not where:
            return None, None
        Locator.parse(where)  # raises ValueError, caught by the caller

        def text_of(found) -> str:
            # An element's text is its name, or its value when it has one;
            # a window's is what it answers to a text query.
            if isinstance(found, AccessibleElement):
                return found.value if found.value is not None else found.name
            return read_window_text(found.handle) or ""

        def holds() -> bool:
            found = self._resolve(session, where,
                                  expect.get("all_windows", False))
            if not found:
                return False
            if selected is not None:
                # Re-read from the surface, not from the walk that found
                # it: the state that proves a tab click worked is the one
                # after the click.
                from ..backends import current
                is_selected = current().is_selected

                if not all(isinstance(n, AccessibleElement)
                           and is_selected(n) == bool(selected) for n in found):
                    return False
            if wanted is None:
                return True
            return any(text_of(n) == wanted for n in found)

        described = f"{where} exists"
        if selected is not None:
            described = f"{where} is {'selected' if selected else 'not selected'}"
        if wanted is not None:
            described = f"{where} reads {wanted!r}"
        return Condition(holds, described), described
