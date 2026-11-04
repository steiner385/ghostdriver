"""How to tell an action worked: the postcondition an `expect` becomes (D67, D77)."""

from ..model.element import AccessibleElement
from ..model.locator import Locator
from .core import _ToolboxCore

#: Every key an `expect` may carry. Anything else is refused by name: an
#: expectation the tool cannot read must not quietly become no expectation,
#: because the result then reads `delivery_only` exactly as if the caller
#: had never asked (D#71).
EXPECT_KEYS = frozenset({"locator", "text", "selected", "changed", "timeout_s",
                         "all_windows", "absent"})


#: Why `changed` is refused on an action that enters text (#248). The shape
#: digest, the top-level windows and `blocked_by` are what `changed`
#: compares, and text painted inside a control that keeps its size moves
#: none of them. A `changed` there would report `delivered_no_effect` on
#: text that landed -- the caller retries and types it twice.
BLIND_TO_TEXT = (
    "`changed: true` cannot see text: it compares the surface's shape, its "
    "top-level windows and whether it is held, and typed text inside a "
    "control changes none of them, so it would read as no effect when the "
    "text landed. Name the result instead -- a `locator` with the `text` it "
    "will read, a control the text will make appear -- or verify with a "
    "capture. On send_keys, `changed` is accepted for named keys alone "
    "(enter, escape), whose effect can be a window opening or closing")


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
            "`text` or `selected`), or `changed: true` (the surface itself "
            f"moves), or `locator` with `absent: true` (it goes away); got "
            f"{sorted(expect)}")
    if expect.get("absent"):
        # "It is gone" is its own postcondition (#118): a dialog closing is
        # how a save is known to have taken. It names a locator and nothing
        # about it, since a control that is not there has no text or state.
        clashing = sorted(k for k in ("text", "selected", "changed") if k in expect)
        if not expect.get("locator") or clashing:
            raise ValueError(
                "`absent: true` takes a `locator` and nothing about it; "
                f"got {sorted(expect)}")
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

    def _expectation(self, session, expect: dict | str | None, *,
                     carries_text: bool = False):
        """Turn a caller\'s `expect` into a condition, re-resolved each time.

        Re-resolved, not a held handle: the element that proves an action
        worked may not exist until it has. The locator is parsed here,
        before anything is sent, so a bad one is an error, not an unmet
        condition -- the two look identical outside and mean opposites.

        `carries_text` is set by an action whose effect is text -- typing,
        setting a value, sending characters. `changed` cannot see text, so
        it is refused for those before anything is sent (#248).
        """
        expect = parse_expect(expect)  # raises ValueError, caught by the caller
        if expect is None:
            return None, None
        if carries_text and expect.get("changed"):
            raise ValueError(BLIND_TO_TEXT)
        if expect.get("absent"):
            return self._absence(session, expect)

        from ..actuate import Condition
        from ..backends import current

        if expect.get("changed"):
            # No control to name: the effect is the *surface* moving -- a
            # palette docking, a pane appearing -- seconds after a click on
            # an owner-drawn control that publishes no postcondition (D77).
            # The baseline is taken now, before the action; the condition
            # holds when the shape digest surfaces already computes moves.
            surfaces = self.surfaces  # type: ignore[attr-defined]
            all_windows = bool(expect.get("all_windows", False))
            snapshot = current().snapshot

            def look() -> tuple:
                # The shape digest is blind to a *new* top-level window: a
                # dialog is not part of the main window's shape. A click
                # that raised a validation error read as a flat failure
                # against {changed: true} (#194). So the top-level windows
                # and whether the target is held are part of "changed" too.
                digest = surfaces(session.session_id, all_windows=all_windows).get("shape_digest")
                seen = session.run(lambda: snapshot(session.pid))
                return (digest, frozenset(seen.windows), tuple(seen.blocked_by))

            baseline = look()

            def moved() -> bool:
                return look() != baseline

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
            return current().read_window_text(found.handle) or ""

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
        if holds():
            # Already so, before the action: a postcondition that cannot fail
            # proves nothing about the action, and a click that did nothing
            # read `verified: effect` against a tab strip that was always
            # there (#128). The mirror of the absent guard (D#118).
            raise ValueError(
                f"{described} already, before the action, so it cannot show that "
                "the action worked. Name what the action will make true -- a "
                "control that will appear, `text` or `selected` it will change "
                "to, `absent: true` for one that will go, or `changed: true` for "
                "the surface moving")
        return Condition(holds, described), described

    def _absence(self, session, expect: dict):
        """The postcondition "this is gone" (#118): holds once the locator no
        longer resolves in the expect's window scope.

        Checked to be *present first*. An absence is trivially true of a
        thing that was never there, and a postcondition that cannot fail is
        the false green D#71 refuses: it would read `verified: effect` on a
        dialog that never opened. So a locator that does not resolve before
        the action is refused by name, not quietly satisfied. Needs no
        backend of its own: the resolver is the whole of it.

        Every top-level window is searched unless the expect says
        `all_windows: false` (#250). What goes away is usually a dialog,
        which is a window of its own, and "gone" is a claim about
        everywhere: the wider scope only makes the condition harder to
        meet, never easier, so it cannot turn into a false green.
        """
        from ..actuate import Condition

        where = expect["locator"]
        Locator.parse(where)  # raises ValueError, caught by the caller
        all_windows = bool(expect.get("all_windows", True))
        if not self._resolve(session, where, all_windows):
            raise ValueError(
                f"absent: {where} does not resolve before the action, so its "
                "absence afterwards would prove nothing. Name something that is "
                "there now and should go away")

        def gone() -> bool:
            return not self._resolve(session, where, all_windows)

        described = f"{where} is gone"
        return Condition(gone, described), described
