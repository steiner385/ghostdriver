"""Target sessions, and the consent that has to exist before one opens.

Which targets may be automated is decided *during* a chat session, by the
person running it, at the moment the question arises — not by configuration
written in advance. That is the only model that matches how the question
actually comes up: a person doing a task knows which application they want
touched and which they need left alone, and they know it then rather than
when the server was installed.

So consent lives here, in memory, for the life of this server process. For a
stdio server that process *is* the chat session, which means grants expire
exactly when they should and nothing has to be cleaned up or persisted.

A session's tier is immutable. Raising it would mean the guarantee under
which earlier calls were made no longer describes the session.
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .model.result import ErrorKind, GhostdriverError
from .ledger import Ledger
from .policy import ConsentSource, Grant, Tier, denied, permits
from .sensitivity import Sensitivity


@dataclass(frozen=True, slots=True)
class Profile:
    """The curated half of a profile document.

    Two things are read. `denylist`: which controls may never be actuated.
    `sensitivity`: how this target wants to be typed at. Which *targets* may
    be driven is a session-time decision, not a file -- consent has to be
    asked for, and a file cannot be asked.

    A cadence note is different in kind from consent, which is why it can
    live here. It carries no authority and gets nobody access to anything;
    it is a fact about the target, like its toolkit. And it has to be
    durable, because the alternative is every new session rediscovering it
    the only way it can be discovered -- by tripping it.
    """

    path: Path | None = None
    matched_profile: str = "unknown"
    denylist: tuple[str, ...] = ()
    sensitivity: Sensitivity = field(default_factory=Sensitivity)
    #: What phase 2 is permitted to actuate. Curated only.
    safe_controls: tuple[dict, ...] = ()

    @classmethod
    def load(cls, path: str | Path) -> "Profile":
        """Read a profile document from disk.

        A profile that fails to parse is an error rather than a default:
        falling back silently would turn a typo in a path into a session
        with no denylist.
        """
        location = Path(path)
        try:
            document = json.loads(location.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GhostdriverError(
                ErrorKind.DENIED_BY_POLICY,
                f"profile {location} could not be read: {exc}",
            ) from exc
        try:
            sensitivity = Sensitivity.from_list(
                document.get("input_sensitivity")
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GhostdriverError(
                ErrorKind.DENIED_BY_POLICY,
                f"profile {location} has an unreadable input_sensitivity "
                f"section: {exc}",
            ) from exc
        return cls(
            path=location,
            matched_profile=document.get("matched_profile", "unknown"),
            denylist=tuple(document.get("denylist") or ()),
            sensitivity=sensitivity,
            safe_controls=tuple(document.get("safe_controls") or ()),
        )

    @classmethod
    def none(cls) -> "Profile":
        return cls()


@dataclass(frozen=True, slots=True)
class Session:
    session_id: str
    pid: int
    tier: Tier
    profile: Profile
    grant: Grant
    command_line: tuple[str, ...] = ()
    opened_at: float = field(default_factory=time.time)
    #: How this session's backend calls reach the target. Normally None --
    #: the call runs on the calling thread. A hidden-desktop session sets a
    #: runner that marshals every target-touching call onto the one thread
    #: bound to that desktop, because a desktop is bound per thread and a
    #: call from anywhere else sees none of the target's windows. Kept as a
    #: plain callable so this module stays platform-neutral: it knows a
    #: session may route its calls, not how.
    runner: object = None

    def run(self, fn):
        """Execute `fn` where this session's target can be seen.

        A plain call for an ordinary session; for a hidden-desktop one, on
        the desktop-bound thread. Everything in the tool layer that touches
        the backend goes through here, so one seam covers every tool.
        """
        return self.runner(fn) if self.runner is not None else fn()

    def summary(self) -> dict:
        described = {
            "session_id": self.session_id,
            "pid": self.pid,
            "tier": self.tier.value,
            "matched_profile": self.profile.matched_profile,
            "consent": {
                "source": self.grant.source.value,
                "note": self.grant.note,
            },
            "denylist_patterns": len(self.profile.denylist),
        }
        # Told, not left to be discovered. A session that has to learn this
        # learns it by tripping the target at machine speed, which is the
        # thing the note exists to prevent -- so it is said at attach, in
        # the summary every session reads first.
        known = self.profile.sensitivity.describe()
        if known:
            described["input_sensitivity"] = known
        return described


class ConsentRequired(GhostdriverError):
    """Raised when a target has not been decided on yet.

    Carries the pid so the caller can ask about that specific target. This
    is not a failure to be retried; it is a question that has not been put
    to anyone yet.
    """

    def __init__(self, pid: int, message: str):
        super().__init__(ErrorKind.DENIED_BY_POLICY, message)
        self.pid = pid


class SessionManager:
    """Open sessions, session-scoped consent, and the gate for every call."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._grants: dict[int, Grant] = {}
        # Approval to *launch* a command, keyed by the command itself --
        # there is no pid to key on until after the launch. Separate from
        # pid grants because launching is a distinct authority from driving
        # something already running.
        self._launch_grants: dict[tuple[str, ...], bool] = {}
        self._launch_notes: dict[tuple[str, ...], str] = {}
        # What this server saw its own actions do. The evidence a learned
        # sensitivity note rests on, kept here rather than taken on trust
        # from whoever asks to record one.
        self.ledger = Ledger()

    # --- consent ---------------------------------------------------------

    def record_grant(
        self,
        pid: int,
        *,
        allowed: bool,
        source: ConsentSource,
        note: str = "",
    ) -> Grant:
        """Record a decision about one target for this session.

        A later decision replaces an earlier one, so a person can change
        their mind mid-task — restrict something they had allowed, or the
        reverse — without restarting anything.
        """
        grant = Grant(pid=pid, allowed=allowed, source=source, note=note)
        self._grants[pid] = grant
        return grant

    def grant_for(self, pid: int) -> Grant | None:
        return self._grants.get(pid)

    def grants(self) -> list[Grant]:
        return list(self._grants.values())

    def record_launch_grant(self, command: list[str], *, allowed: bool,
                            note: str = "") -> None:
        """Record the operator's decision about launching one command.

        Keyed by the exact command, because that is what a person approves:
        not "may launch" in general, but "may launch this". A later decision
        replaces an earlier one, as with target grants.
        """
        key = tuple(command)
        self._launch_grants[key] = allowed
        self._launch_notes[key] = note

    def launch_grant_for(self, command: list[str]):
        """The launch decision for `command`, or None if never asked.

        Returns a small object with `.allowed` and `.note`, or None. None is
        a question not yet put to anyone, distinct from a recorded refusal.
        """
        key = tuple(command)
        if key not in self._launch_grants:
            return None
        from types import SimpleNamespace
        return SimpleNamespace(allowed=self._launch_grants[key],
                               note=self._launch_notes.get(key, ""))

    # --- sessions --------------------------------------------------------

    def attach(
        self,
        pid: int,
        *,
        command_line: list[str],
        tier: Tier = Tier.READ_ONLY,
        profile: Profile | None = None,
        runner: object = None,
    ) -> Session:
        """Open a session against `pid`, if it has been consented to.

        Raises ConsentRequired when nobody has decided about this target
        yet, so the caller can ask rather than guess. Refusing outright
        would be wrong: not-yet-asked is a different state from refused,
        and only one of them is worth putting a question to a person about.
        """
        grant = self._grants.get(pid)
        if grant is None:
            raise ConsentRequired(
                pid,
                f"pid {pid} has not been approved for automation in this "
                "session. Ask the operator which targets to allow, then "
                "record the answer with grant_targets.",
            )
        if not grant.allowed:
            note = f" ({grant.note})" if grant.note else ""
            raise GhostdriverError(
                ErrorKind.DENIED_BY_POLICY,
                f"pid {pid} was restricted for this session{note}. It must "
                "not be automated; ask the operator if that has changed.",
            )

        session = Session(
            session_id=uuid.uuid4().hex[:12],
            pid=pid,
            tier=tier,
            profile=profile or Profile.none(),
            grant=grant,
            command_line=tuple(command_line),
            runner=runner,
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
        # Its observations go with it: they were evidence about one
        # session's work, and a later session did not see them.
        self.ledger.forget(session_id)

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
        # Consent can be withdrawn mid-session, and an open session must not
        # outlive it. Checked here rather than only at attach, so revoking a
        # target stops work already under way.
        grant = self._grants.get(session.pid)
        if grant is None or not grant.allowed:
            raise GhostdriverError(
                ErrorKind.DENIED_BY_POLICY,
                f"pid {session.pid} is no longer approved for automation in "
                "this session",
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
