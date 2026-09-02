"""What else happened while an action ran.

An `ActionResult` says whether its own expectation held. That is not the
same as saying nothing else occurred: a click that succeeds and raises a
dialog, logs the session out, or pulls the target to the front has done
something the caller needs to know about, and the postcondition it declared
will not mention any of it.

This is the evidence layer, and it is deliberately not a verdict. Nothing
here decides that a target detected automation, or that an action was
rejected -- every observation has a benign twin, and picking between them
needs context only the caller has. What it does is make the observations
available, so the caller is forming a hypothesis from something rather than
from silence.

Pure comparison: two snapshots in, a list of differences out. The backend
takes the snapshots.
"""

from dataclasses import dataclass, field
from enum import Enum


class Change(str, Enum):
    """A kind of thing that happened alongside an action."""

    #: A top-level window that was not there before. The most common one
    #: worth seeing: confirmations, validation errors, session timeouts.
    WINDOW_APPEARED = "window_appeared"
    #: A top-level window that was there before and is not now.
    WINDOW_DISAPPEARED = "window_disappeared"
    #: The target became modally blocked, or stopped being.
    BLOCKED = "blocked"
    UNBLOCKED = "unblocked"
    #: The target took the foreground. Never caused by anything this tool
    #: sends, so it is always the application's own doing -- worth saying,
    #: because the person at the machine just had their desktop changed.
    TOOK_FOREGROUND = "took_foreground"
    #: The target stopped answering, or went away entirely.
    TARGET_GONE = "target_gone"


@dataclass(frozen=True, slots=True)
class Disturbance:
    """One observed change, with enough detail to act on."""

    change: Change
    detail: str = ""

    def to_dict(self) -> dict:
        return {"change": self.change.value, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class Snapshot:
    """The state an action is compared against.

    Only what is cheap to collect. A full tree walk before and after every
    action would cost more than the action, and the questions worth asking
    here are all answerable from the top-level windows.
    """

    #: handle -> caption, for every top-level window of the target.
    windows: dict[int, str] = field(default_factory=dict)
    blocked_by: tuple[str, ...] = ()
    foreground: int = 0
    alive: bool = True


def compare(before: Snapshot, after: Snapshot) -> list[Disturbance]:
    """Everything that changed between two snapshots.

    Order is by significance rather than by discovery: a caller reading only
    the first entry should get the one that matters most.
    """
    if not after.alive:
        return [Disturbance(Change.TARGET_GONE,
                            "the target stopped owning windows")]

    found: list[Disturbance] = []

    gained = set(after.blocked_by) - set(before.blocked_by)
    if gained:
        found.append(Disturbance(
            Change.BLOCKED,
            "the application is now held by: " + ", ".join(sorted(gained)),
        ))

    appeared = set(after.windows) - set(before.windows)
    for handle in sorted(appeared):
        caption = after.windows[handle] or "(untitled)"
        found.append(Disturbance(Change.WINDOW_APPEARED, caption))

    released = set(before.blocked_by) - set(after.blocked_by)
    if released and not gained:
        found.append(Disturbance(
            Change.UNBLOCKED,
            "no longer held by: " + ", ".join(sorted(released)),
        ))

    if after.foreground != before.foreground and after.foreground in after.windows:
        found.append(Disturbance(
            Change.TOOK_FOREGROUND,
            after.windows[after.foreground] or "(untitled)",
        ))

    vanished = set(before.windows) - set(after.windows)
    for handle in sorted(vanished):
        caption = before.windows[handle] or "(untitled)"
        found.append(Disturbance(Change.WINDOW_DISAPPEARED, caption))

    return found


#: What to tell a caller whose action failed and who has disturbances to
#: look at. Deliberately a suggestion rather than a conclusion: the tool
#: cannot tell a target that rejects automated input apart from one that
#: rejected the *value*, and guessing would be worse than asking.
INPUT_SENSITIVE_HINT = (
    "if this target may reject machine-speed input, the same action at "
    "cadence=fast_human is the experiment that tells that apart from an "
    "ordinary validation failure"
)
