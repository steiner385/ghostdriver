"""Structured outcomes. Spec section 9."""

from dataclasses import dataclass, field
from enum import Enum


class ErrorKind(str, Enum):
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    STALE = "stale"
    NOT_ACTIONABLE = "not_actionable"
    DENIED_BY_POLICY = "denied_by_policy"
    DENIED_BY_ENVIRONMENT = "denied_by_environment"
    TIER_EXHAUSTED = "tier_exhausted"
    POSTCONDITION_FAILED = "postcondition_failed"
    TIMEOUT = "timeout"


class GhostdriverError(Exception):
    def __init__(self, kind: ErrorKind, message: str, locator: str | None = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.locator = locator

    def to_dict(self) -> dict:
        return {"kind": self.kind.value, "message": self.message,
                "locator": self.locator}


@dataclass(frozen=True)
class ActionResult:
    """Outcome of an action.

    Immutable once constructed. `ok` is forced False when a declared
    postcondition did not verify. An action that cannot distinguish success
    from a no-op must not claim success (spec section 4.4).

    `disturbances` never affects `ok`. A dialog appearing may be the
    application rejecting what was typed, or the confirmation the action was
    supposed to raise; the tool cannot tell, and a result that guessed would
    be wrong in whichever direction it guessed.
    """

    ok: bool
    tier_used: int | None = None
    #: Which attempt on the tier delivered -- "typed" or "pasted" at tier 3
    #: -- when the verb named its attempts. A tier number alone cannot say.
    route_used: str | None = None
    tiers_attempted: list[int] = field(default_factory=list)
    precondition_verified: bool | None = None
    postcondition_verified: bool | None = None
    elapsed_ms: int = 0
    error: dict | None = None
    #: What else happened while the action ran -- a dialog that appeared,
    #: the application becoming held, the target taking the foreground.
    #: Evidence, never a verdict: the postcondition says whether the action
    #: worked, and this says what the postcondition was never going to
    #: mention. Empty when nothing was watched or nothing changed.
    disturbances: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.postcondition_verified is False:
            object.__setattr__(self, "ok", False)
