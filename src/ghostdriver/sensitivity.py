"""What a target is known to be sensitive about, and how sure anyone is.

A cadence is useless if every session has to rediscover it, because the
discovery happens *by tripping the thing* -- at robot speed, on a target
that may already have noticed the last session. So the fact belongs
somewhere durable and gets told to each session rather than learned by it.

Two kinds of note, and the difference matters more than it looks:

- **declared** by an operator who already knows. The only kind that helps on
  a first encounter, which is the encounter that counts. One failure mode
  here is invisible -- a target can accept the input and flag the account
  server-side -- and nothing observable will ever reveal it. Only a person
  can say so in advance.
- **learned** by a session that ran the differential: robot failed, human
  succeeded, same action. That is the one observation that separates input
  sensitivity from an ordinary validation failure, and it is worth keeping.

Keyed by target *and surface kind*, because a native shell hosting web
content is two different detectors in one window and they will not agree.

Nothing here decides anything at act time. It carries what is known, says
where each belief came from, and lets the caller see the difference.
"""

import time
from dataclasses import dataclass, field
from enum import Enum

from .cadence import ROBOT, Cadence, by_name


class Source(str, Enum):
    """Where a note came from, which is how much it is worth."""

    #: An operator said so. Believed on sight, including before any session
    #: has touched the target.
    DECLARED = "declared"
    #: A session measured it: the same action failed at robot cadence and
    #: succeeded at a human one.
    LEARNED = "learned"


@dataclass(frozen=True, slots=True)
class Note:
    """One belief about how a target wants to be typed at."""

    cadence: str
    source: Source
    #: Which part of the target. "*" is the whole thing; otherwise a surface
    #: kind from the surface map, because a native shell hosting web content
    #: is two detectors and they do not agree.
    surface: str = "*"
    #: What was seen, or what the operator said. Ends up in front of a
    #: person deciding whether to trust it.
    evidence: str = ""
    recorded: str = ""

    def applies_to(self, surface: str) -> bool:
        return self.surface == "*" or self.surface == surface

    def to_dict(self) -> dict:
        return {
            "cadence": self.cadence,
            "source": self.source.value,
            "surface": self.surface,
            "evidence": self.evidence,
            "recorded": self.recorded,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Note":
        return cls(
            cadence=raw["cadence"],
            source=Source(raw.get("source", Source.DECLARED.value)),
            surface=raw.get("surface", "*"),
            evidence=raw.get("evidence", ""),
            recorded=raw.get("recorded", ""),
        )


@dataclass
class Sensitivity:
    """Every note about one target."""

    notes: list[Note] = field(default_factory=list)

    def cadence_for(self, surface: str = "*") -> Cadence:
        """What to type at, for this part of the target.

        A specific surface beats a blanket note: "human cadence on web
        regions" should not be widened to the whole application by a later
        catch-all, and a catch-all should not be narrowed away by one.

        Declared beats learned at equal specificity, because a person who
        said so knows something a measurement cannot reach.
        """
        applicable = [n for n in self.notes if n.applies_to(surface)]
        if not applicable:
            return ROBOT
        best = min(
            applicable,
            key=lambda n: (n.surface == "*", n.source is not Source.DECLARED),
        )
        try:
            return by_name(best.cadence)
        except ValueError:
            # A hand-edited file with a typo in it. Falling back to robot
            # would be the silent wrong answer this module exists to avoid.
            raise

    def record(self, note: Note) -> None:
        """Add a note, replacing any earlier one for the same surface.

        Replacing rather than accumulating: two beliefs about the same
        surface is not richer information, it is an unresolved contradiction
        that the next reader has to arbitrate.
        """
        self.notes = [n for n in self.notes if n.surface != note.surface]
        self.notes.append(note)

    def describe(self) -> str:
        """One line for a session that is being told what is known.

        Empty when nothing is known, so a caller can tell "no notes" from
        "notes that say robot" -- the first is ignorance and the second is a
        decision.
        """
        if not self.notes:
            return ""
        parts = []
        for note in sorted(self.notes, key=lambda n: n.surface):
            where = "everywhere" if note.surface == "*" else note.surface
            parts.append(f"{where}: {note.cadence} ({note.source.value})")
        return "input cadence -- " + "; ".join(parts)

    def to_list(self) -> list[dict]:
        return [n.to_dict() for n in self.notes]

    @classmethod
    def from_list(cls, raw: list[dict] | None) -> "Sensitivity":
        return cls(notes=[Note.from_dict(r) for r in (raw or [])])


def learned_from_differential(
    surface: str, action: str, *, now: float | None = None
) -> Note:
    """The note a session writes after running the experiment.

    Only called when the differential actually held -- robot failed, human
    succeeded, same action, same field. A note written on anything weaker
    would be a guess wearing the word "learned".
    """
    when = time.strftime("%Y-%m-%d", time.localtime(now or time.time()))
    return Note(
        cadence="fast_human",
        source=Source.LEARNED,
        surface=surface,
        evidence=(
            f"{action} failed at robot cadence and succeeded at fast_human"
        ),
        recorded=when,
    )
