"""Verbs, as ladders of attempts the actuator can run.

Each function returns the tiers that implement one verb against one window,
ordered by the actuator rather than here. Nothing in this module decides
whether an action worked; it decides what to try.

The ordering within a verb is the interesting part, and `set_text` is where
it matters most -- including one rung that is present or absent depending on
the cadence asked for.
"""

from ...actuate import Attempt, Condition, Tier
from ...cadence import ROBOT, Cadence
from ...model.element import AccessibleElement
from . import elements, modality, winapi
from . import input as win_input


def click(hwnd: int, *, button: str = "left", modifiers=(), at=None,
          count: int = 1, hover: bool = False) -> list[Attempt]:
    """Actuate a control.

    Tier 1 first because a target that publishes an Invoke pattern should be
    driven through it -- that is the surface it supports, and it survives a
    control moving or resizing. Tier 3 is where a Profile L1 target is
    actually reached. A pattern has no notion of a right button or a held
    modifier, so anything but a plain left click is tier 3 alone.

    `hover` posts the VCL mouse-enter notification before the pair (#133):
    a control that acts on a click only while it believes the mouse is over
    it never sees the posted pair alone, because that belief is set from
    the real cursor on idle, not from mouse messages. Still a posted route:
    no pointer, no foreground.
    """
    posted = Attempt(Tier.WINDOW_MESSAGE,
                     lambda: win_input.click(hwnd, button=button, modifiers=modifiers,
                                             at=at, count=count, hover=hover),
                     name="posted+hover" if hover else "")
    if button != "left" or modifiers or at is not None or count != 1:
        # A pattern has no button, no modifier, no point and no double.
        return [posted]
    return [
        Attempt(Tier.UIA_PATTERN, lambda: win_input.invoke_via_uia(hwnd)),
        posted,
    ]


def click_element(element: AccessibleElement, *, button: str = "left",
                  modifiers=(), at=None, count: int = 1,
                  hover: bool = False,
                  menu_by_keyboard: bool = False) -> list[Attempt]:
    """Actuate an element that is not a window.

    **The posted click goes first, and the pattern is the fallback.** That
    inverts the ladder, on a measurement. Selecting a tab item through its
    SelectionItem pattern marks it selected -- and the application's page
    never switches, because programmatic selection on a Win32 tab control
    sends no change notification, so the handler a person's click would run
    does not run. It is the Value-pattern split (D21) again: the surface
    changes, the application does not know. The button pair posted to the
    *host* window at the element's own rectangle goes through the control's
    own mouse handling, which notifies the application exactly as a
    person's click would -- and it is also the only route on a Profile L1
    target, whose elements publish nothing at all.

    The pattern stays on the ladder for the host that does not answer a
    posted click -- a provider that draws its elements itself and reads the
    real input queue -- where Invoke or Select is the surface it supports.
    """
    posted = Attempt(Tier.WINDOW_MESSAGE,
                     lambda: elements.click_posted(element, button=button,
                                                   modifiers=modifiers, at=at,
                                                   count=count, hover=hover),
                     name="posted+hover" if hover else "")
    if button != "left" or modifiers or at is not None or count != 1:
        return [posted]
    if element.class_name == winapi.POPUP_MENU_CLASS:
        # Two routes into a popup-menu item, and which goes first is a fact
        # about the target (#189). An ordinary Win32 menu answers the posted
        # pair, and that is the default: it was stable for weeks, where the
        # keyboard route put first for everyone (D#135) failed about one CI
        # run in three for a reason not yet found (#190). A menu whose loop
        # hit-tests the real pointer closes on the posted pair instead; for
        # that target the keyboard route goes first, when asked.
        keys = Attempt(Tier.WINDOW_MESSAGE, lambda: elements.menu_choose(element),
                       rank=0 if menu_by_keyboard else 1, name="menu_keys")
        pair = Attempt(Tier.WINDOW_MESSAGE, posted.run,
                       rank=1 if menu_by_keyboard else 0, name="posted")
        return [keys, pair]
    return [
        posted,
        Attempt(Tier.UIA_PATTERN, lambda: elements.act_via_pattern(element),
                rank=1),
    ]


def set_text(hwnd: int, text: str, *,
             cadence: Cadence = ROBOT,
             allow_pattern: bool = True,
             live_window: int = 0,
             insert_first: bool = False) -> list[Attempt]:
    """Replace a control's text.

    **`live_window` is accepted and ignored here.** It is the Linux
    live-actuation gate (D#111), where a value only commits through a real
    keystroke on the operator's own display. Windows never needs it -- a
    posted message reaches a background control without taking the
    operator's focus -- so the parameter exists for the shared contract's
    shape and changes nothing on this platform.

    **Typing is the only way this sets text, and the ladder is short.** The
    spec left this open; the fixture settled it. A programmatic write --
    `WM_SETTEXT`, or a Value pattern -- replaces what a control *displays*
    without the toolkit's keyboard path ever running, so a data-bound field
    ends up showing one value while the application still holds another, and
    a caller who reads the display back cannot tell. Typing traverses the
    same path a person's keystrokes would, so whatever the toolkit does on
    input happens.

    **Tier 1 carries that hazard too, so it runs only when it is checked.**
    Measured: the HWND-to-UIA bridge synthesises a Value pattern for
    anything derived from a native EDIT, and `SetValue` on it splits display
    from bound value exactly as `WM_SETTEXT` did. Nothing distinguishes that
    from a real Value pattern at the point of calling it -- both answer, and
    only one commits.

    So `allow_pattern` is the caller saying a failure here would be caught:
    a postcondition that names the *committed* value, at which point tier 1
    delivering nothing useful simply falls through to typing, and a target
    that publishes a real pattern is driven through the surface it supports.
    Without such a postcondition it is a coin flip whose losing side is
    silent, and the caller should pass False.

    A non-robot cadence drops it regardless. A caller asking for human
    pacing is saying this target watches its input, and a pattern call
    produces *no input events at all* -- it is the most detectable thing
    available here. Offering it would defeat the request silently, which is
    the one failure mode a cadence must not have.

    Without a postcondition nothing is claimed either way:
    `postcondition_verified` stays unset, which is the result saying it does
    not know.
    """
    typed = Attempt(
        Tier.WINDOW_MESSAGE,
        lambda: win_input.set_text_by_typing(hwnd, text, cadence=cadence),
        name="typed",
    )
    # After typing, the insert: the field is read back after every rung, so
    # a typed value that arrived short falls through to a value delivered
    # whole through the control's own edit path (EM_REPLACESEL, D70) --
    # no clipboard. Measured need: an address field that dropped
    # characters at both cadences. Typing stays first because it is the
    # toolkit's own keyboard path, which is what a bound field commits on.
    inserted = Attempt(Tier.WINDOW_MESSAGE,
                       lambda: win_input.insert_text(hwnd, text), rank=1, name="inserted")
    if insert_first:
        # The profile says this class swallows typing (#207): the insert
        # goes first, typing stays as the fallback.
        typed.rank, inserted.rank = 1, 0
    if not cadence.is_robot or not allow_pattern:
        return [typed, inserted]
    return [
        Attempt(Tier.UIA_PATTERN,
                lambda: win_input.set_value_via_uia(hwnd, text), name="pattern"),
        typed,
        inserted,
    ]


def send_keys(hwnd: int, keys: list[str], *,
              cadence: Cadence = ROBOT) -> list[Attempt]:
    """Send raw keystrokes.

    No tier 1: there is no accessibility pattern for "press these keys", and
    pretending otherwise would put a rung on the ladder that always
    declines. Which also means cadence is the only thing that varies here.
    """
    return [
        Attempt(
            Tier.WINDOW_MESSAGE,
            lambda: win_input.send_keys(hwnd, keys, cadence=cadence),
        ),
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


def set_text_element(element: AccessibleElement, text: str, *,
                     cadence: Cadence = ROBOT,
                     allow_pattern: bool = True,
                     live_window: int = 0,
                     insert_first: bool = False) -> list[Attempt]:
    """Replace an element's value: the same ladder and the same rule as
    `set_text`. Typing through the host is what runs the page's own input
    handling; the Value pattern is offered first only when a commit
    expectation would catch it not committing (D30). On Chromium it does
    commit -- measured -- but the rule does not depend on that.

    `live_window` is accepted and ignored, as in `set_text`: it is the Linux
    live gate (D#111) and Windows has no need of it."""
    del live_window, insert_first  # an element has one typed route; nothing to reorder
    typed = Attempt(
        Tier.WINDOW_MESSAGE,
        lambda: elements.replace_value(element, text, cadence=cadence),
    )
    if not cadence.is_robot or not allow_pattern:
        return [typed]
    return [
        Attempt(Tier.UIA_PATTERN,
                lambda: elements.set_value_via_pattern(element, text)),
        typed,
    ]


def type_text_element(element: AccessibleElement, text: str, *,
                      cadence: Cadence = ROBOT) -> list[Attempt]:
    return [Attempt(Tier.WINDOW_MESSAGE,
                    lambda: elements.type_into(element, text, cadence=cadence))]


def send_keys_element(element: AccessibleElement, keys: list[str], *,
                      cadence: Cadence = ROBOT) -> list[Attempt]:
    return [Attempt(Tier.WINDOW_MESSAGE,
                    lambda: elements.send_keys_into(element, keys, cadence=cadence))]
