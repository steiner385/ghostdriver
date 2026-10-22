"""What this session actually saw an action do.

`Source.LEARNED` is supposed to mean the differential held -- the same
action failed at robot cadence and succeeded at a human one. Something has
to be able to check that, and the honest answer is not to take the caller's
word for it: an agent recording a note is the party that most wants the note
recorded, and an assertion it makes about its own history cannot be
distinguished from a guess.

So the server keeps its own record of what it ran, and the differential is
read out of that. The evidence for a learned note is then something the
server observed rather than something it was told, which is the only kind of
evidence worth writing to a file that later sessions will trust.

Deliberately small and in memory: this is working evidence for one session,
not history. It answers exactly one question and forgets everything else.
"""

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

#: How many outcomes to keep per session. Generous for the question being
#: asked -- the two attempts of a differential are usually seconds apart --
#: and small enough that a long session cannot grow it without bound.
MAX_ENTRIES = 200


@dataclass(frozen=True, slots=True)
class Outcome:
    """One action, and how it went."""

    locator: str
    tool: str
    cadence: str
    ok: bool
    #: Where the element sat, so a note can be recorded against the surface
    #: rather than the whole target.
    surface: str = "native"
    #: What exactly was sent -- for a click, its button, count and point --
    #: so "the same action again" is told from a different action on the
    #: same control (#240).
    action: str = ""


@dataclass(frozen=True, slots=True)
class Differential:
    """Evidence that a target refused machine-speed input and accepted
    human-paced input for the same action."""

    locator: str
    tool: str
    surface: str

    def describe(self) -> str:
        return f"{self.tool} on {self.locator}"


class Ledger:
    """Recent outcomes, per session."""

    def __init__(self, max_entries: int = MAX_ENTRIES) -> None:
        self._entries: dict[str, deque[Outcome]] = {}
        self._max = max_entries

    def record(self, session_id: str, outcome: Outcome) -> None:
        self._entries.setdefault(
            session_id, deque(maxlen=self._max)
        ).append(outcome)

    def outcomes(self, session_id: str) -> list[Outcome]:
        return list(self._entries.get(session_id, ()))

    def forget(self, session_id: str) -> None:
        self._entries.pop(session_id, None)

    def differential(
        self, session_id: str, locator: str | None = None
    ) -> Differential | None:
        """The strongest differential this session can show, if any.

        Both halves have to be the *same* action on the *same* element:
        "something failed and something else worked" is not evidence about
        input speed, it is two unrelated facts. Requiring the tool to match
        as well keeps a failed `click` from vouching for a `set_value`.

        The robot failure may come before or after the human success. An
        agent that hits the wall, retries paced, and only then records is
        the ordinary case, but one that reads a note, works paced, and later
        confirms by trying robot is running the same experiment backwards --
        and it produces the same evidence.
        """
        entries = self.outcomes(session_id)
        if locator is not None:
            entries = [e for e in entries if e.locator == locator]

        for entry in reversed(entries):
            if entry.ok or entry.cadence != "robot":
                continue
            paced = [
                e for e in entries
                if e.locator == entry.locator
                and e.tool == entry.tool
                and e.cadence != "robot"
                and e.ok
            ]
            if paced:
                return Differential(locator=entry.locator, tool=entry.tool,
                                    surface=paced[-1].surface)
        return None

    def why_not(self, session_id: str, locator: str | None = None) -> str:
        """What is missing, for a caller who asked to record and cannot.

        A bare refusal here would be unhelpful in a specific way: the caller
        believes it saw something, and needs to know which half of the
        evidence the server does not have.
        """
        entries = self.outcomes(session_id)
        if locator is not None:
            entries = [e for e in entries if e.locator == locator]
        if not entries:
            return (
                "this session has not run that action, so there is nothing "
                "to draw evidence from"
            )
        failed_robot = [e for e in entries if not e.ok and e.cadence == "robot"]
        paced_ok = [e for e in entries if e.ok and e.cadence != "robot"]
        if not failed_robot and not paced_ok:
            return (
                "nothing in this session failed at robot cadence and then "
                "succeeded when paced"
            )
        if not failed_robot:
            return (
                "the paced attempt succeeded, but nothing failed at robot "
                "cadence first -- without that, there is no evidence the "
                "pacing is what made the difference"
            )
        return (
            "an attempt failed at robot cadence, but the same action has not "
            "since succeeded at a human cadence -- retry it with "
            "cadence=fast_human, and record it if that works"
        )


def surfaces_seen(outcomes: Iterable[Outcome]) -> set[str]:
    return {o.surface for o in outcomes}
