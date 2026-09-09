"""How to tell an action worked: the postcondition an `expect` becomes (D67, D77)."""

from ..model.element import AccessibleElement
from ..model.locator import Locator
from .core import _ToolboxCore

#: Every key an `expect` may carry. Anything else is refused by name: an
#: expectation the tool cannot read must not quietly become no expectation,
#: because the result then reads `delivery_only` exactly as if the caller
#: had never asked (D#71).
EXPECT_KEYS = frozenset({"locator", "text", "selected", "changed", "timeout_s",
                         "all_windows"})


def parse_expect(expect: dict | str | None) -> dict | None:
    """The `expect` a caller sent, as the dict the tools read -- None for no
    expectation, or ValueError saying what is wrong with it.

    A bare string is a locator ("this is now present", D67). A string that
    looks like JSON is a dict a client serialised before sending, and is
    read as the dict it was. A dict is checked here, before anything is
    sent: unknown keys are refused by name, and a dict with neither
    `locator` nor `changed` is refused rather than ignored (D#71).
    """
    if expect is None or expect == "" or expect == {}:
        return None
    if isinstance(expect, str):
        stripped = expect.strip()
        if stripped.startswith("{"):
            import json
            try:
                expect = json.loads(stripped)
            except ValueError as exc:
                raise ValueError(f"looks like JSON but does not parse ({exc})") from None
        else:
            expect = {"locator": expect}
    if not isinstance(expect, dict):
        raise ValueError(
            f"must be a locator string or an object, not {type(expect).__name__}")
    unknown = sorted(k for k in expect if k not in EXPECT_KEYS)
    if unknown:
        raise ValueError(
            f"unknown key(s) {unknown}; an expect takes {sorted(EXPECT_KEYS)}")
    if not expect.get("changed") and not expect.get("locator"):
        raise ValueError(
            "needs `locator` (a control that will be present, with optional "
            "`text` or `selected`) or `changed: true` (the surface itself "
            f"moves); got {sorted(expect)}")
    return expect


def verify_window(expect: dict | str | None) -> float | None:
    """How long a postcondition is polled after this action, from the
    expect's `timeout_s`. None lets the actuator use its default (2s, D48).

    The bug this closes (#73): `timeout_s` was honored only for a
    `{changed}` expect, so a locator expect that named a dialog or menu
    slower than 2s to appear was declared failed while its own
    disturbances showed it had opened. Now any expect that carries
    `timeout_s` is given that window, and `{changed}` keeps its 6s default
    because a surface can dock seconds after the click (D77). A malformed
    expect returns None here; `_expectation` is what reports the error.
    """
    try:
        parsed = parse_expect(expect)
    except ValueError:
        return None
    if parsed is None:
        return None
    if "timeout_s" in parsed:
        return float(parsed["timeout_s"])
    if parsed.get("changed"):
        return 6.0
    return None


class _ExpectCore(_ToolboxCore):
    """Turns a caller's `expect` into a re-checked condition."""

    def _expectation(self, session, expect: dict | str | None):
        """Turn a caller\'s `expect` into a condition, re-resolved each time.

        Re-resolved, not a held handle: the element that proves an action
        worked may not exist until it has. The locator is parsed here,
        before anything is sent, so a bad one is an error, not an unmet
        condition -- the two look identical outside and mean opposites.
        """
        expect = parse_expect(expect)  # raises ValueError, caught by the caller
        if expect is None:
            return None, None

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

        where = expect["locator"]
        wanted = expect.get("text")
        selected = expect.get("selected")
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
