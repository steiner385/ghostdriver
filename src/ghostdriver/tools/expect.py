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
        loc = Locator.parse(where)  # raises ValueError, caught by the caller

        # A dialog like a browser's file-picker is a new top-level in a
        # helper process, so a main-window postcondition never sees it and
        # reports the same `postcondition_failed` whether it opened or not
        # (#60). But it opens *as the foreground window*, and that is
        # readable without touching anything. So when the expectation is
        # purely "a window of this class is up" -- no text, selected, index,
        # handle or scope, which a class alone cannot vouch for -- a
        # target-owned foreground window of that class counts as the effect
        # landing. Scoped to the target's own process tree, so an unrelated
        # same-class dialog the operator has focused does not read as a pass.
        corroborate_class = (
            loc.class_name if (
                loc.class_name is not None and not loc.is_element
                and wanted is None and selected is None
                and loc.index is None and loc.handle is None
                and loc.within is None and loc.visible is not False
            ) else None
        )

        def foreground_is_target_owned() -> bool:
            if corroborate_class is None:
                return False
            import fnmatch

            winapi = current().winapi

            def read() -> bool:
                fg = winapi.foreground_window()
                if not fg or not fnmatch.fnmatchcase(
                        winapi.class_name(fg), corroborate_class):
                    return False
                return winapi.window_pid(fg) in self._tree_pids(session)

            return session.run(read)

        def text_of(found) -> str:
            # An element's text is its name, or its value when it has one;
            # a window's is what it answers to a text query.
            if isinstance(found, AccessibleElement):
                return found.value if found.value is not None else found.name
            return read_window_text(found.handle) or ""

        def holds() -> bool:
            # The cheap corroboration first: when it applies it settles the
            # common "a dialog appeared" case without enumerating the tree.
            if foreground_is_target_owned():
                return True
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
