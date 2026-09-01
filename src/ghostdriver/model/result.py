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


@dataclass
class ActionResult:
    """Outcome of an action.

    `ok` is forced False when a declared postcondition did not verify. An
    action that cannot distinguish success from a no-op must not claim
    success (spec section 4.4).
    """

    ok: bool
    tier_used: int | None = None
    tiers_attempted: list[int] = field(default_factory=list)
    precondition_verified: bool | None = None
    postcondition_verified: bool | None = None
    elapsed_ms: int = 0
    error: dict | None = None

    def __post_init__(self) -> None:
        if self.postcondition_verified is False:
            self.ok = False
