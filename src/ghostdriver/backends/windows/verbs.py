"""Verbs, as ladders of attempts the actuator can run.

Each function returns the tiers that implement one verb against one window,
ordered by the actuator rather than here. Nothing in this module decides
whether an action worked; it decides what to try.

The ordering within a verb is the interesting part, and `set_text` is where
it matters most.
"""

from ...actuate import Attempt, Condition, Tier
from . import input as win_input
from . import modality


def click(hwnd: int) -> list[Attempt]:
    """Actuate a control.

    Tier 1 first because a target that publishes an Invoke pattern should be
    driven through it -- that is the surface it supports, and it survives a
    control moving or resizing. Tier 3 is where a Profile L1 target is
    actually reached.
    """
    return [
        Attempt(Tier.UIA_PATTERN, lambda: win_input.invoke_via_uia(hwnd)),
        Attempt(Tier.WINDOW_MESSAGE, lambda: win_input.click(hwnd)),
    ]


def set_text(hwnd: int, text: str, *, fast_path: bool = False) -> list[Attempt]:
    """Replace a control's text.

    **The typed sequence is the tier-3 default, and `WM_SETTEXT` is not.**
    The spec recorded this as unverified; the fixture settles it. `WM_SETTEXT`
    replaces what a control displays without the toolkit's keyboard path ever
    running, so a data-bound field ends up showing one value while the
    application still holds another -- and a caller who reads the display
    back cannot tell. Typing traverses the same path a person's keystrokes
    would, so whatever the toolkit does on input happens.

    `fast_path` offers `WM_SETTEXT` *ahead* of typing for the many controls
    with nothing bound behind them, where it is far quicker. It is opt-in
    because the failure it risks is silent, and a silent wrong value in a
    field is worse than a slow correct one. Even then it is not the only
    rung: if a postcondition checks the committed value, the fast path
    delivers, fails verification and gives way to typing on its own.

    **Tier 1 carries the same hazard, and it is not opt-in.** Measured
    against the fixture: the HWND-to-UIA bridge synthesises a Value pattern
    for anything derived from a native EDIT, and `SetValue` on it changes
    the display without the keyboard path running, exactly as `WM_SETTEXT`
    does -- so a superclassed field ends up displaying one value while the
    application holds another. It stays first because on a target that
    publishes a real Value pattern that is the surface to use, and because
    the ladder recovers: with a postcondition on the committed value, tier 1
    delivers, fails verification, and typing runs behind it. Without one,
    nothing is claimed -- `postcondition_verified` stays unset, which is the
    result saying it does not know.
    """
    typed = Attempt(Tier.WINDOW_MESSAGE,
                    lambda: win_input.set_text_by_typing(hwnd, text))
    if not fast_path:
        return [
            Attempt(Tier.UIA_PATTERN,
                    lambda: win_input.set_value_via_uia(hwnd, text)),
            typed,
        ]
    # Both live at tier 3, and the actuator runs a tier's attempts in the
    # order given, so the fast path simply goes first.
    return [
        Attempt(Tier.UIA_PATTERN,
                lambda: win_input.set_value_via_uia(hwnd, text)),
        Attempt(Tier.WINDOW_MESSAGE,
                lambda: win_input.set_text_by_message(hwnd, text)),
        typed,
    ]


def send_keys(hwnd: int, keys: list[str]) -> list[Attempt]:
    """Send raw keystrokes.

    No tier 1: there is no accessibility pattern for "press these keys", and
    pretending otherwise would put a rung on the ladder that always
    declines.
    """
    return [
        Attempt(Tier.WINDOW_MESSAGE, lambda: win_input.send_keys(hwnd, keys)),
    ]


def unblocked(hwnd: int) -> Condition:
    """A precondition: nothing modal stands between `hwnd` and the user.

    Worth stating explicitly because posted messages do not respect
    modality. Real input to a held application is swallowed by the system
    before the control ever sees it; a posted message is delivered straight
    to the window procedure, so a driver can drive a window the user cannot
    touch and never notice. Whether the control then acts is up to the
    control -- which means the observable outcome varies by class, and a
    driver that relies on it is relying on an accident.

    Checked at act time rather than read from a tree: a modal that appears
    between reconnaissance and actuation is the case that matters.
    """
    return Condition(
        check=lambda: modality.blocking_ancestor(hwnd) is None,
        description=(
            f"no disabled window blocks {hwnd} "
            "(a modal dialog is the usual cause)"
        ),
    )
