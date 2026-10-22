"""What to type at: the caller's choice, else what the profile knows.

Its own module because `acting.py` sits at the tool-module limit (D60).

Precedence, most specific first:

1. a cadence named on the call;
2. the profile's `cadence_for_class`, for the control's window class
   (#238) -- a rich-text editor that drops robot-speed keystrokes and takes
   human-paced ones is a fact about that class, not about the whole
   surface it sits in;
3. the profile's per-surface notes (D26), worked out only when some note
   actually distinguishes surfaces -- that costs a walk up the ancestor
   chain, and there is no reason to pay it on a target nobody annotated;
4. robot.

Never a retry at a slower cadence after a fast one failed: that would hide
which cadence worked, which is the thing worth recording (D45).
"""

from ..cadence import ROBOT, Cadence, by_name


def choose_cadence(session, handle: int, requested: str | None,
                   class_name: str | None = None) -> Cadence:
    if requested is not None:
        return by_name(requested)
    profile = session.profile
    if profile.cadence_for_class:
        from ..backends import current

        name = class_name if class_name is not None else current().winapi.class_name(handle)
        declared = profile.class_cadence(name)
        if declared is not None:
            return by_name(declared)
    notes = profile.sensitivity
    if not notes.notes:
        return ROBOT
    if all(n.surface == "*" for n in notes.notes):
        return notes.cadence_for()

    from ..backends import current

    return notes.cadence_for(current().surface_of(handle))
