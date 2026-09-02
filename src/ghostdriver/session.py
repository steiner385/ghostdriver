"""Target sessions: what is attached, at what tier, under whose policy.

Every tool call happens inside a session, and the session is where the two
questions that gate it are already answered: which environment this target
is connected to, and what this caller is permitted to do. Answering them at
attach rather than per call means a refusal happens once, loudly, at a
moment an operator is watching -- rather than midway through a run.

A session's tier is immutable. Raising it would mean the guarantee under
which earlier calls were made no longer describes the session, and a
caller inspecting a session afterwards could not tell what it had been
allowed to do at the time.
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .model.result import ErrorKind, GhostdriverError
from .policy import GuardResult, Tier, check_environment, denied, permits


@dataclass(frozen=True, slots=True)
class Profile:
    """The curated half of a profile document.

    The probe emits `denylist` and `environment_allowlist` empty, for a human
    to fill in. Everything else in the document is evidence; these two are
    policy, and they are the only parts this module reads.
    """

    path: Path | None = None
    matched_profile: str = "unknown"
    denylist: tuple[str, ...] = ()
    environment_allowlist: tuple[str, ...] = ()

    @classmethod
    def load(cls, path: str | Path) -> "Profile":
        """Read a profile document from disk.

        Missing policy fields are read as empty rather than as absent,
        because empty is what the probe emits and what the guard is built to
        refuse. A profile that fails to parse is an error rather than a
        default: silently falling back to an empty profile would turn a typo
        into an unguarded session.
        """
        location = Path(path)
        try:
            document = json.loads(location.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GhostdriverError(
                ErrorKind.DENIED_BY_ENVIRONMENT,
                f"profile {location} could not be read: {exc}",
            ) from exc
        return cls(
            path=location,
            matched_profile=document.get("matched_profile", "unknown"),
            denylist=tuple(document.get("denylist") or ()),
            environment_allowlist=tuple(
                document.get("environment_allowlist") or ()
            ),
        )

    @classmethod
    def unguarded(cls) -> "Profile":
        """A profile with no policy at all.

        Named so that a caller constructing one has to say what they are
        doing. The guard refuses everything under it, which is the point.
        """
        return cls()


@dataclass(frozen=True, slots=True)
class Session:
    session_id: str
    pid: int
    tier: Tier
    profile: Profile
    guard: GuardResult
    command_line: tuple[str, ...] = ()
    opened_at: float = field(default_factory=time.time)

    def summary(self) -> dict:
        return {
            "session_id": self.session_id,
            "pid": self.pid,
            "tier": self.tier.value,
            "matched_profile": self.profile.matched_profile,
            "profile_path": str(self.profile.path) if self.profile.path else None,
            "environment": {
                "verdict": self.guard.verdict.value,
                "overridden": self.guard.overridden,
                "endpoints": [e.normalized for e in self.guard.endpoints],
                "reason": self.guard.reason,
            },
            "denylist_patterns": len(self.profile.denylist),
        }


class SessionManager:
    """Open sessions, and the gate every tool call passes through."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def attach(
        self,
        pid: int,
        *,
        command_line: list[str],
        tier: Tier = Tier.READ_ONLY,
        profile: Profile | None = None,
        override_environment: bool = False,
    ) -> Session:
        """Open a session against `pid`, or refuse and say why.

        The environment guard runs here and nowhere else. Its verdict is
        kept on the session so that a later reader can see what was decided
        and whether a human overrode it -- an override that left no trace
        would defeat the purpose of having checked.
        """
        profile = profile or Profile.unguarded()
        guard = check_environment(
            command_line,
            list(profile.environment_allowlist),
            override=override_environment,
        )
        if not guard.ok:
            raise GhostdriverError(
                ErrorKind.DENIED_BY_ENVIRONMENT,
                f"refusing to attach to pid {pid}: {guard.reason}. "
                + (
                    "Add it to the profile's environment_allowlist, or "
                    "attach with override_environment to record a deliberate "
                    "exception."
                ),
            )

        session = Session(
            session_id=uuid.uuid4().hex[:12],
            pid=pid,
            tier=tier,
            profile=profile,
            guard=guard,
            command_line=tuple(command_line),
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise GhostdriverError(
                ErrorKind.NOT_FOUND,
                f"no open session {session_id!r}; attach first",
            )
        return session

    def release(self, session_id: str) -> None:
        # Releasing an already-released session is not an error. A caller
        # tidying up after a failure should not have to track whether it got
        # far enough to open one.
        self._sessions.pop(session_id, None)

    def open_sessions(self) -> list[Session]:
        return list(self._sessions.values())

    def authorize(self, session_id: str, tool: str) -> Session:
        """The gate. Returns the session, or raises saying which rule failed."""
        session = self.get(session_id)
        if not permits(session.tier, tool):
            raise GhostdriverError(
                ErrorKind.DENIED_BY_POLICY,
                f"{tool!r} is not permitted at tier {session.tier.value!r}",
            )
        return session

    def check_caption(self, session_id: str, caption: str) -> None:
        """Refuse a control the profile's denylist names.

        Checked against the *resolved* caption rather than the locator, so a
        locator that happens to match a denied control is caught even when
        it was not written to name one.
        """
        session = self.get(session_id)
        match = denied(caption, list(session.profile.denylist))
        if match is not None:
            raise GhostdriverError(
                ErrorKind.DENIED_BY_POLICY,
                f"refusing to act on {match.describe()}",
            )
