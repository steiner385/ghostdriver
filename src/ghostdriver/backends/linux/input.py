"""Tier 1 actuation: the accessibility API, and nothing below it.

**The ladder here has one rung, and that is a measurement rather than an
omission.** D#11 measured `XSendEvent` ignored by GTK 4.14.5 in every
configuration tried -- focused, unfocused, key, button, with a passing
control behind each experiment -- so tier 3, the rung that drives a chosen
window without taking the operator's focus or pointer, **does not exist on
this platform.** The only rung below tier 1 is tier 4, real synthetic input,
which takes the actual focus and pointer and is therefore acceptable only
where the input being taken is not the operator's -- i.e. inside the nested
X server. `hidden_desktop.py` builds that (#40 slice 5b), but these ladders
do not yet route through it: routing tier 4 through a hidden desktop's
claim is its own follow-on, not done by slice 5b building the desktop
itself, so tier 4 is still not offered here.

The consequence is worth stating plainly rather than discovering: **a control
that tier 1 cannot reach cannot currently be actuated at all on Linux.** D#10
measured exactly such a control -- the fixture's owner-drawn `DrawingArea`
has an accessible *role* and no Action interface behind it, so it is
nameable and not drivable. That is reported as an unfitted target (D53), not
worked around.

Everything here goes through the deadline. AT-SPI will not bound a call
against a hung application, so the caller has to (D#9).
"""

from __future__ import annotations

import contextlib
from functools import partial
from typing import Any

from .deadline import call_with_deadline
from .tree import _accessible

#: Named keys a caller can send, mapped to X keysym names (`XK.string_to_
#: keysym`). Deliberately small and the same set the Windows table names, so
#: the contract reads identically: every one is a key whose *effect* the
#: toolkit implements, which is what makes it worth sending as a key rather
#: than a character. There is no tier-3 posted-key path here (D#11), so
#: these travel XTest -- tier 4, inside a live session only (D#111).
NAMED_KEYS: dict[str, str] = {
    "enter": "Return", "return": "Return", "tab": "Tab",
    "escape": "Escape", "esc": "Escape",
    "backspace": "BackSpace", "delete": "Delete",
    "home": "Home", "end": "End", "left": "Left", "up": "Up",
    "right": "Right", "down": "Down", "pageup": "Prior", "pagedown": "Next",
    "insert": "Insert",
}

#: Editing actions a control performs on a keystroke, named so `send_keys`
#: can offer them where a raw modifier chord cannot be posted. On X these
#: are real Ctrl-chords through XTest, unlike Windows' edit messages, so the
#: mapping is to the keysym pair; the value is the letter pressed with Ctrl.
EDIT_ACTIONS: dict[str, str] = {
    "paste": "v", "copy": "c", "cut": "x", "undo": "z", "select-all": "a",
}


def button_pair(button: str = "left", modifiers=()) -> tuple[int, ...]:
    """Validate a click's button and modifiers, refusing what cannot be sent.

    The Windows counterpart returns the four message/flag values a posted
    pair needs; here there is nothing to post -- a click is `Action.do_action`
    (D#40e), which takes no button or modifier -- so this exists only to
    refuse `button=right` or a modifier *by name*, the way the Windows one
    does, rather than let a caller believe a right-click was sent. The
    return value is unused; raising is the whole job.
    """
    if button not in ("left",):
        raise ValueError(
            f"only a plain left click is available on this platform: an "
            f"AT-SPI action takes no button, and there is no tier-3 posted "
            f"pair to carry {button!r} (D#11, D#40e)")
    if modifiers:
        raise ValueError(
            f"a modifier click cannot be sent: an AT-SPI action carries no "
            f"modifier state, and there is no posted pair to put {list(modifiers)} "
            f"on (D#11)")
    return ()


def deepest_child_at(handle: int, x: int, y: int) -> tuple[int, int, int]:
    """The counterpart of the Win32 hit test, and it does not apply here.

    On Windows a posted click can be dropped by a parent over a windowed
    child, so the innermost window under the point is found first (D66).
    Here a control is an accessible, not a window, and actuation is a direct
    `do_action` on the node the locator already resolved -- there is no point
    to hit-test and no child window to miss. `AccessibleElement` also cannot
    supply a screen position through AT-SPI reliably for this purpose (D#40d
    found position unusable). So this returns the handle unchanged, which is
    the Windows contract's "nothing else is under the point" answer.
    """
    return handle, x, y


def _atspi() -> Any:
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    return Atspi


def action_names(handle: int) -> list[str]:
    """What this control says it can be told to do.

    Empty is a real answer and the important one: D#10 found the owner-drawn
    control reports `actions=[]` and raises when asked to act. There is no
    Action interface behind it at all -- a role does not imply an
    implementation.
    """
    node = _accessible(handle)
    atspi = _atspi()
    count = call_with_deadline(partial(atspi.Action.get_n_actions, node)) or 0
    names = []
    for index in range(count):
        got = call_with_deadline(
            partial(atspi.Action.get_action_name, node, index)
        )
        if got:
            names.append(got)
    return names


def act_via_action(handle: int) -> bool:
    """Run the control's first action -- the tier 1 click.

    `do_action(node, 0)` rather than a named lookup: D#10 measured a real
    `Gtk.Button` reporting `actions=['click']`, and the first action is the
    default one by AT-SPI convention. Returning False rather than raising is
    what lets the actuator fall through the ladder (D10), and on this
    platform there is nothing below to fall through *to* -- so a False here
    becomes a reported refusal rather than a silent retry.
    """
    node = _accessible(handle)
    atspi = _atspi()
    with contextlib.suppress(Exception):
        return bool(call_with_deadline(partial(atspi.Action.do_action, node, 0)))
    return False


def set_text_via_editable(handle: int, text: str) -> bool:
    """Write a value through `EditableText`, which is the *preferred* path here.

    **This inverts the Windows conclusion, on a measurement.** There, a
    programmatic write goes around the toolkit: the control displays the new
    text while the binding never hears of it, so display and committed value
    disagree until something forces a commit. That is D21, and it is why
    `WM_SETTEXT` was deleted rather than kept as a fast path (D25), and why
    the Windows `set_text` offers its pattern rung only when a postcondition
    would catch it not committing.

    `set_text_contents` goes *through* `GtkEditable`, so the widget's own
    `changed` signal fires and a binding sees the write. D#10 measured no
    split at all. Tier 1 is stronger here than on Windows, and inheriting the
    Windows caution would have meant preferring a typing path that does not
    exist on this platform anyway.

    **One intermediate state a caller has to know about.** The call clears
    and re-inserts, so `changed` fires **twice** and the first carries an
    *empty* value nobody wrote. Harmless against a mirror; not harmless
    against a field that rejects empty, or one that runs a lookup per change.
    Recorded rather than smoothed over, because it is not something this
    module can hide -- it is what the toolkit does.
    """
    node = _accessible(handle)
    atspi = _atspi()
    with contextlib.suppress(Exception):
        return bool(
            call_with_deadline(
                partial(atspi.EditableText.set_text_contents, node, text)
            )
        )
    return False


def focus_via_component(handle: int) -> bool:
    """Ask the toolkit to focus a control. **It does not work here.**

    D#10 measured `Atspi.Component.grab_focus` raising on the fixture's
    bound entry. Kept as a named function that honestly returns False rather
    than deleted, because its absence is load-bearing: tier 4 needs the
    target focused (D#11), and focus therefore has to come from the window
    manager and keyboard navigation rather than from the accessibility API.
    Anything building tier 4 later will look for this and needs to find the
    answer, not silence.
    """
    node = _accessible(handle)
    atspi = _atspi()
    with contextlib.suppress(Exception):
        return bool(
            call_with_deadline(partial(atspi.Component.grab_focus, node))
        )
    return False
