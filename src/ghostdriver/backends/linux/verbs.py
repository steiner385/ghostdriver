"""Verbs, as ladders of attempts the actuator can run.

Same contract as the Windows module: each function returns the tiers that
implement one verb, and nothing here decides whether an action worked.

**Every ladder in this file is one rung long, or empty.** That is the shape
D#11 forced: tier 3 does not exist on GTK4/X11, and tier 4 has no isolation
to run inside until #40 slice 5b builds `HiddenDesktop`. Where the Windows
module offers a pattern *and* a posted message and lets the actuator choose,
this offers tier 1 or nothing.

An empty ladder is deliberate and is not a bug. The actuator turns it into
`TIER_EXHAUSTED` -- a result that names what the verb offered and what the
actuator allowed -- which is a target the strategy cannot fit, reported as
such rather than worked around (D53, D10).
"""

from __future__ import annotations

from ...actuate import Attempt, Condition, Tier
from ...cadence import ROBOT, Cadence
from ...model.element import AccessibleElement
from . import input as linux_input
from . import modality


def click(handle: int, *, button: str = "left", modifiers=(), at=None,
          live_window: int = 0, real_input: tuple[int, int] | None = None,
          count: int = 1) -> list[Attempt]:
    """Actuate a control through its Action interface.

    Anything but a plain left click returns an **empty** ladder. On Windows
    those variants fall to tier 3, which posts a real button pair and so has
    a notion of which button, which modifiers and where. An AT-SPI action has
    none of that -- `do_action` takes an index and nothing else -- and there
    is no rung underneath to carry the difference (D#11).

    Offering tier 1 anyway would be worse than refusing: a right-click that
    silently performed a left-click is a wrong action reported as a
    successful one, which is the failure mode this ladder exists to prevent.
    """
    if button != "left" or modifiers or at is not None or count != 1:
        return []
    return [
        Attempt(Tier.UIA_PATTERN, lambda: linux_input.act_via_action(handle)),
    ]


def set_text(handle: int, text: str, *,
             cadence: Cadence = ROBOT,
             allow_pattern: bool = True,
             live_window: int = 0) -> list[Attempt]:
    """Replace a control's text, through `EditableText`.

    **`live_window` chooses the ladder, because the commit differs by
    toolkit.** With no live window (the default and the safe case) this is
    the tier-1 `EditableText` write only: on GTK4 that commits (D#10), and
    on a toolkit where it does not -- wxGTK3 -- it changes the display and
    the caller learns from the postcondition that nothing was accepted. With
    a live window consented (D#111), the ladder is a single **tier-4** rung
    that writes the value and presses a real Enter to commit it, guarded so
    any movement of the operator's desktop aborts it. The write alone is not
    offered there, because on wxGTK3 it never commits and would report a
    display-only success that stops before the Enter.

    **`allow_pattern` is accepted and deliberately ignored, and that is the
    decision.** On Windows the flag exists because the API-level write is the
    *hazardous* path: it splits what a control displays from what its binding
    holds (D21), so it is offered only when a caller has a postcondition that
    would catch it not committing.

    Here it is the opposite. D#10 measured `set_text_contents` going through
    `GtkEditable`, firing the widget's own `changed` signal, with **no split
    at all** -- and there is no typing path to fall back to, because tier 3
    does not exist (D#11). So refusing tier 1 when `allow_pattern` is False
    would leave no way to set text whatsoever, turning a caller's caution
    about a Windows hazard into a total loss of the verb on a platform that
    does not have that hazard.

    The parameter stays in the signature because the contract is shared and
    a caller should not have to know which backend it is talking to.

    **Cadence cannot be honoured, and that is worth a caller knowing.** A
    non-robot cadence means "this target watches its input, pace it like a
    person" -- and an AT-SPI write produces no input events at all, so there
    is nothing to pace. On Windows that is why a human cadence *drops* the
    pattern rung and types instead. Here dropping it would leave nothing, so
    the write goes ahead unpaced. A target that watches its input will see a
    value appear without keystrokes.
    """
    del cadence, allow_pattern  # accepted for contract shape; see the docstring
    if live_window:
        from . import live

        return [
            Attempt(Tier.SYNTHETIC_INPUT,
                    lambda: live.commit_value(handle, text, live_window=live_window),
                    name="live-commit"),
        ]
    return [
        Attempt(Tier.UIA_PATTERN,
                lambda: linux_input.set_text_via_editable(handle, text),
                name="editable"),
    ]


def send_keys(handle: int, keys: list[str], *,
              cadence: Cadence = ROBOT) -> list[Attempt]:
    """Send raw keystrokes. **Nothing implements this on Linux yet.**

    There is no accessibility pattern for "press these keys" -- the Windows
    module says the same, and puts the verb on tier 3 instead. Tier 3 does
    not exist here (D#11), and tier 4 would take the operator's real keyboard
    unless it runs inside the nested X server, which is not built (#40 slice
    5b).

    So this returns an empty ladder rather than a rung that always declines.
    The difference matters: a rung that declines reports "tried and failed",
    which invites a caller to retry. An empty ladder reports that no
    permitted tier implements the verb at all, which is the true statement
    and the one that stops a retry loop.
    """
    del keys, cadence
    return []


def unblocked(handle: int) -> Condition:
    """A precondition: nothing modal is holding the window this control is in.

    The Windows version explains itself by saying posted messages do not
    respect modality, so a driver can drive a window the user cannot touch.
    There are no posted messages here -- tier 1 is a bus call into the
    application's own process -- and **whether that call respects modality is
    a separate question with its own answer.**

    It is checked for the same reason regardless. A modal that appears
    between reconnaissance and actuation is the case that matters, and
    checking at act time rather than reading a tree is what catches it.

    The description does not mention a disabled window, because on this
    platform there is never one: `blocking_ancestor` answers by looking for
    something *modal transient-for* the frame instead (D#12).
    """
    return Condition(
        check=lambda: modality.blocking_ancestor(handle) is None,
        description=(
            f"nothing modal is holding the window containing {handle} "
            "(a modal dialog is the usual cause)"
        ),
    )


def set_text_element(element: AccessibleElement, text: str, *,
                     cadence: Cadence = ROBOT,
                     allow_pattern: bool = True,
                     live_window: int = 0) -> list[Attempt]:
    """The element form of `set_text`.

    On Windows an element is something inside a web document, reached
    through a host window, and the two forms differ because the host is
    driven differently from the control. Here every control *is* an
    accessible already -- the tree is AT-SPI all the way down -- so an
    element and a window control take the same route (D#104), including the
    live-commit ladder.
    """
    return set_text(element.handle, text, cadence=cadence,
                    allow_pattern=allow_pattern, live_window=live_window)


def click_element(element: AccessibleElement, *, button: str = "left",
                  live_window: int = 0, real_input: tuple[int, int] | None = None,
                  modifiers=(), at=None, count: int = 1) -> list[Attempt]:
    """The element form of `click`, and the same refusal for the variants."""
    return click(element.handle, button=button, modifiers=modifiers,
                 at=at, count=count)


def type_text_element(element: AccessibleElement, text: str, *,
                      cadence: Cadence = ROBOT) -> list[Attempt]:
    """Typing, specifically -- as opposed to setting a value.

    Empty for the same reason as `send_keys`: typing means input events, and
    the only rung that produces them is tier 4 (D#11, #40 slice 5b). A caller
    asking to *type* rather than to *set* is usually asking for the toolkit's
    keyboard path to run, and answering with an API write would satisfy the
    call while defeating the request.
    """
    del text, cadence
    return []


def send_keys_element(element: AccessibleElement, keys: list[str], *,
                      cadence: Cadence = ROBOT) -> list[Attempt]:
    """Empty, as `send_keys`."""
    return send_keys(element.handle, keys, cadence=cadence)
