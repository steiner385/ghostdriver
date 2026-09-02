"""How fast typed input arrives, and why that is a choice.

Posted keystrokes land about 0.6ms apart, which is a rate no person types
at, and some applications look. Where one does, the driver has to type the
way a fast person would -- not because the messages change, but because the
gaps between them do.

This is the pure part: given text and a cadence, the pauses. The backend
sleeps through them. Nothing here touches a window, so the shape of a
cadence can be tested without one.
"""

import random
from dataclasses import dataclass

#: Characters after which a person pauses a little longer: the end of a
#: word, or of a clause. A fast typist's rhythm is not uniform, and a
#: uniform rhythm is its own tell.
WORD_BOUNDARIES = frozenset(" \t\n.,;:!?-/")


@dataclass(frozen=True, slots=True)
class Cadence:
    """The rhythm of typed input.

    `mean_ms` is the typical gap between keystrokes, `jitter_ms` how far
    either side of it a gap may fall, and `word_pause_ms` what gets added
    after a word boundary. All zero is a robot.
    """

    name: str
    mean_ms: float
    jitter_ms: float = 0.0
    word_pause_ms: float = 0.0

    @property
    def is_robot(self) -> bool:
        return self.mean_ms == 0 and self.word_pause_ms == 0

    def delays(self, text: str, rng: random.Random | None = None) -> list[float]:
        """The pause, in seconds, *before* each character of `text`.

        The first is always zero: nothing precedes the first keystroke.
        """
        if not text or self.is_robot:
            return [0.0] * len(text)
        rng = rng or random.Random()
        pauses = [0.0]
        for previous in text[:-1]:
            gap = self.mean_ms + rng.uniform(-self.jitter_ms, self.jitter_ms)
            if previous in WORD_BOUNDARIES:
                gap += self.word_pause_ms
            pauses.append(max(gap, 0.0) / 1000.0)
        return pauses

    def estimate_ms(self, text: str) -> int:
        """Roughly how long `text` takes at this cadence, before jitter.

        For telling a caller what a long field will cost before they commit
        to it: a human-paced memo is minutes, and that is worth knowing in
        advance rather than discovering from a timeout.
        """
        if len(text) < 2 or self.is_robot:
            return 0
        boundaries = sum(1 for c in text[:-1] if c in WORD_BOUNDARIES)
        return int((len(text) - 1) * self.mean_ms
                   + boundaries * self.word_pause_ms)


#: As fast as the message queue takes them. The default, because most
#: targets do not look, and the ones that do are recorded per target.
ROBOT = Cadence("robot", 0.0)

#: A fast typist: around 100 words a minute, uneven, slower at the ends of
#: words. Roughly 80ms a character, so a twenty-character field takes a
#: second and a half, and a memo takes minutes -- which is why this is
#: chosen per target and per surface rather than being the default.
FAST_HUMAN = Cadence("fast_human", 80.0, jitter_ms=30.0, word_pause_ms=90.0)

CADENCES: dict[str, Cadence] = {c.name: c for c in (ROBOT, FAST_HUMAN)}


def by_name(name: str) -> Cadence:
    """Look a cadence up, failing loudly on a name nobody defined.

    Silently falling back to robot is the wrong default here: a caller who
    asked for a human cadence and got a robot would find out from the
    target, which is the one place they did not want to.
    """
    try:
        return CADENCES[name]
    except KeyError:
        raise ValueError(
            f"unknown cadence {name!r}; expected one of {sorted(CADENCES)}"
        ) from None
