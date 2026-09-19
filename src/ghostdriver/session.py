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
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .consent import ConsentStore, StandingApprovals
from .ledger import Ledger
from .model.result import ErrorKind, GhostdriverError
from .policy import ConsentSource, Grant, Tier, denied, permits, tier_for
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
    #: The profile document's own id, when it declares one -- what a macro's
    #: provenance.recorded_against names, so replay can warn on a mismatch (#87).
    profile_id: str = ""
    denylist: tuple[str, ...] = ()
    #: Denied *places*: {"within": locator, "region": {left, top, right,
    #: bottom}, "note"?}, the rectangle in the client coordinates of the
    #: window `within` names -- the frame `at` and a capture of it use. A
    #: grid cell or a painted button has no caption and no identity, only a
    #: place (D72). Any actuation aimed inside one is refused.
    deny_regions: tuple[dict, ...] = ()
    sensitivity: Sensitivity = field(default_factory=Sensitivity)
    #: What phase 2 is permitted to actuate. Curated only.
    safe_controls: tuple[dict, ...] = ()
    #: How this target shows it is still working (D69): a locator that is
    #: present while busy ({"locator": ..., "all_windows"?}), or a region
    #: that renders ink while busy ({"region": {left,top,right,bottom},
    #: "ink_above": 0.02}). On a target whose grids fill seconds after the
    #: click that asked for them, an action's result is not the screen's.
    busy_indicator: dict | None = None
    #: Control classes (fnmatch patterns) whose click is the posted message
    #: only, never the UIA Invoke pattern (#122). For a plain HWND control
    #: the pattern rung is tried first; on a toolkit that answers Invoke
    #: slowly or not at all, that is seconds of waiting and then a second
    #: delivery of a click the posted message already made. A declared
    #: route beats a learned one (D35).
    posted_click_only: tuple[str, ...] = ()
    #: Control classes (fnmatch patterns) whose posted click is preceded by
    #: the VCL mouse-enter notification (#133): a control that acts on a
    #: click only while it believes the mouse is over it, a belief the
    #: application sets from the real cursor on idle and no posted pair can
    #: create. Declared, because the message is private to one toolkit.
    hover_before_click: tuple[str, ...] = ()
    #: What the operator knows about a control class that a session cannot
    #: measure: {class pattern: note}. Surfaced on every find match and
    #: click result for a matching class (#137). Declared knowledge (D35):
    #: "this bar is a mouse affordance for keys the editor binds; use
    #: send_keys on the edit box" is worth more than another hour of clicks.
    notes: dict[str, str] = field(default_factory=dict)

    def note_for(self, class_name: str | None) -> str | None:
        """The operator's note for this class, or None."""
        import fnmatch

        name = class_name or ""
        for pattern, note in self.notes.items():
            if fnmatch.fnmatchcase(name, pattern):
                return note
        return None

    def wants_hover(self, class_name: str | None) -> bool:
        """Whether `hover_before_click` names this class."""
        import fnmatch

        name = class_name or ""
        return any(fnmatch.fnmatchcase(name, p) for p in self.hover_before_click)

    def pins_to_posted(self, class_name: str | None) -> str | None:
        """The `posted_click_only` pattern that pins `class_name`, or None."""
        import fnmatch

        name = class_name or ""
        for pattern in self.posted_click_only:
            if fnmatch.fnmatchcase(name, pattern):
                return pattern
        return None

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
        names: list[str] = []
        regions: list[dict] = []
        for entry in document.get("denylist") or ():
            if isinstance(entry, str):
                names.append(entry)
                continue
            region = entry.get("region") if isinstance(entry, dict) else None
            if (not isinstance(entry, dict) or not entry.get("within")
                    or not isinstance(region, dict)
                    or any(k not in region for k in ("left", "top", "right", "bottom"))):
                raise GhostdriverError(
                    ErrorKind.DENIED_BY_POLICY,
                    f"profile {location} has an unreadable denylist entry {entry!r}: "
                    "a region entry is {\"within\": <locator>, \"region\": "
                    "{left, top, right, bottom}, \"note\"?}",
                )
            regions.append(entry)
        pinned = document.get("posted_click_only") or []
        if not isinstance(pinned, list) or not all(isinstance(c, str) and c for c in pinned):
            raise GhostdriverError(
                ErrorKind.DENIED_BY_POLICY,
                f"profile {location} has an unreadable posted_click_only: a list of "
                f"window-class patterns, e.g. [\"TsfCommandButton\"]; got {pinned!r}",
            )
        notes = document.get("notes") or {}
        if (not isinstance(notes, dict)
                or not all(isinstance(k, str) and k and isinstance(n, str) for k, n in notes.items())):
            raise GhostdriverError(
                ErrorKind.DENIED_BY_POLICY,
                f"profile {location} has an unreadable notes: an object of "
                f"{{\"<class pattern>\": \"<note>\"}}; got {notes!r}",
            )
        hovered = document.get("hover_before_click") or []
        if not isinstance(hovered, list) or not all(isinstance(c, str) and c for c in hovered):
            raise GhostdriverError(
                ErrorKind.DENIED_BY_POLICY,
                f"profile {location} has an unreadable hover_before_click: a list of "
                f"window-class patterns, e.g. [\"THtLeftPanel\"]; got {hovered!r}",
            )
        return cls(
            path=location,
            matched_profile=document.get("matched_profile", "unknown"),
            profile_id=str(document.get("profile_id", "")),
            denylist=tuple(names),
            deny_regions=tuple(regions),
            sensitivity=sensitivity,
            safe_controls=tuple(document.get("safe_controls") or ()),
            busy_indicator=document.get("busy_indicator") or None,
            posted_click_only=tuple(pinned),
            hover_before_click=tuple(hovered),
            notes=dict(notes),
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
    #: Whether this session may write the person's clipboard -- the grid
    #: copy route needs to, nothing else does (D70). Off unless asked for
    #: at attach.
    clipboard: bool = False
    #: How this session's backend calls reach the target. Normally None --
    #: the call runs on the calling thread. A hidden-desktop session sets a
    #: runner that marshals every target-touching call onto the one thread
    #: bound to that desktop, because a desktop is bound per thread and a
    #: call from anywhere else sees none of the target's windows. Kept as a
    #: plain callable so this module stays platform-neutral: it knows a
    #: session may route its calls, not how.
    runner: Callable[[Callable[[], Any]], Any] | None = None
    #: The window (a backend-opaque id) the operator consented to have driven
    #: *live*, on their own display -- the "operator-present live actuation"
    #: class (D#111). Non-zero only when the operator named a window that was
    #: already the foreground at attach, which is what lets an actuation take
    #: the real keyboard for an instant to commit a value a toolkit accepts
    #: no other way. 0 is the default and the safe case: no live input.
    live_window: int = 0

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
            "deny_regions": len(self.profile.deny_regions),
        }
        # Told, not left to be discovered. A session that has to learn this
        # learns it by tripping the target at machine speed, which is the
        # thing the note exists to prevent -- so it is said at attach, in
        # the summary every session reads first.
        known = self.profile.sensitivity.describe()
        if known:
            described["input_sensitivity"] = known
        if self.live_window:
            described["live_actuation"] = (
                f"granted for window {self.live_window:#x}: a value this "
                "session commits may take the real keyboard for an instant, "
                "aborting if the operator's foreground or pointer moves (D#111)"
            )
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


def _psutil_parent(pid: int) -> int | None:
    """The parent pid, or None at the root or for a pid that is gone.

    psutil refuses a parent whose creation time is later than the child's,
    which is what keeps a recycled pid from looking like an ancestor.
    """
    try:
        import psutil

        parent = psutil.Process(pid).parent()
        return parent.pid if parent is not None else None
    except Exception:
        return None


class SessionManager:
    """Open sessions, session-scoped consent, and the gate for every call.

    **Consent is about an application, and an application is a process
    tree.** A decision recorded for a pid applies to every process that
    descends from it: the file dialog a Chromium browser opens lives in a
    helper process with its own pid, and asking the operator again for it
    is asking them to approve the application they just approved. A
    decision about the pid itself still wins over an inherited one, in
    either direction, and a restriction inherits exactly as an approval
    does. `parent_of` is injectable so the walk is testable without
    processes.
    """

    def __init__(self, parent_of: Callable[[int], int | None] = _psutil_parent,
                 store: ConsentStore | None = None,
                 standing: StandingApprovals | None = None) -> None:
        self._sessions: dict[str, Session] = {}
        self._grants: dict[int, Grant] = {}
        self._parent_of = parent_of
        # Decisions kept for the life of their process, when an operator
        # directory is configured (R1a): a server restart is not a reason
        # to ask the person again about an application that has not changed.
        self._store = store if store is not None else ConsentStore.from_environment()
        for kept in self._store.load():
            self._grants[kept.pid] = kept
        # What the operator declared about executables, ahead of time and by
        # hand (D#125). Read only, and consulted last -- see `grant_for`.
        self._standing = (standing if standing is not None
                          else StandingApprovals.from_environment())
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
        self._store.save(grant)
        return grant

    def grant_for(self, pid: int, *,
                  parent_of: Callable[[int], int | None] | None = None) -> Grant | None:
        """The decision that applies to `pid`, in order of specificity:
        its own, else its nearest decided ancestor's marked as inherited,
        else the operator's standing declaration about its executable;
        None if none of the three answers.

        **That order is the decision D#125 settled, and it is here so it is
        in one place.** D35 says a declared note beats a learned one, which
        reads at first like the declaration should come first. It does not
        apply: both sides here are the person, not a person and a
        measurement. The pid decision is their *later and more specific*
        answer, about the process actually running, and a file edited last
        week must never overturn "leave that one alone" said a minute ago --
        in either direction. So the declaration answers only where nobody
        answered at all, which is the case it was asked for: a target that
        restarted while the operator was not looking.

        `parent_of` may be supplied for a bulk, informational use -- listing
        every target with its consent -- where one process snapshot answers
        for all of them and opening each process to check its creation
        time is a cost paid for nothing. The authorizing paths use the
        default, which does check.
        """
        own = self._grants.get(pid)
        if own is not None:
            return own
        if self._grants:
            walk = parent_of or self._parent_of
            seen = {pid}
            current = walk(pid)
            while current is not None and current not in seen:
                seen.add(current)
                ancestor = self._grants.get(current)
                if ancestor is not None:
                    return Grant(pid=pid, allowed=ancestor.allowed,
                                 source=ancestor.source, note=ancestor.note,
                                 inherited_from=current)
                current = walk(current)
        # Nobody has decided about this process or anything it descends
        # from. Costs nothing -- and opens no process -- unless the operator
        # declared something.
        return self._standing.decide(pid)

    def grants(self) -> list[Grant]:
        return list(self._grants.values())

    def consent_lifetime(self) -> str:
        """How long an approval given now will actually last, on this run.

        One sentence, and it has to be the *true* one. The prompt used to
        say "this lasts for this session only" whatever was configured,
        which stopped being true when R1a made approvals outlive the server
        run -- so half the time the sentence a person read before approving
        described a different thing from the one they were approving, and
        the other half it failed to say why they were being asked again
        (#62). Both halves are the same defect: the lifetime is knowable
        here, and was not being reported.
        """
        if self._store.enabled:
            return (
                "This lasts while that process keeps running, including "
                "across restarts of this server -- and no longer: if the "
                "application itself restarts, you are asked again."
            )
        from .operator import ENV_VAR

        return (
            "This lasts for this server run only, and will be asked again "
            "after a restart -- no operator directory is configured, so "
            f"there is nowhere to keep it. Set {ENV_VAR} to keep approvals "
            "for as long as the target process runs."
        )

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
        runner: Callable[[Callable[[], Any]], Any] | None = None,
        clipboard: bool = False,
        live_window: int = 0,
    ) -> Session:
        """Open a session against `pid`, if it has been consented to.

        Raises ConsentRequired when nobody has decided about this target
        yet, so the caller can ask rather than guess. Refusing outright
        would be wrong: not-yet-asked is a different state from refused,
        and only one of them is worth putting a question to a person about.
        """
        grant = self.grant_for(pid)
        if grant is None:
            problem = self._standing.problem
            raise ConsentRequired(
                pid,
                f"pid {pid} has not been approved for automation in this "
                "session. Ask the operator which targets to allow, then "
                f"record the answer with grant_targets. {self.consent_lifetime()}"
                + (f" Note: {problem}" if problem else ""),
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
            clipboard=clipboard,
            live_window=live_window,
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            from .trace import lost_session_hint

            hint = lost_session_hint(session_id)
            raise GhostdriverError(
                ErrorKind.NOT_FOUND,
                f"no open session {session_id!r}; attach first"
                + (f". {hint}" if hint else ""),
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
            needed = tier_for(tool)
            raise GhostdriverError(
                ErrorKind.DENIED_BY_POLICY,
                f"{tool!r} is not permitted at tier {session.tier.value!r}"
                + (f"; it needs tier {needed.value!r} -- attach with "
                   f"tier={needed.value!r}" if needed else ""),
            )
        # Consent can be withdrawn mid-session, and an open session must not
        # outlive it. Checked here rather than only at attach, so revoking a
        # target stops work already under way.
        grant = self.grant_for(session.pid)
        if grant is None or not grant.allowed:
            raise GhostdriverError(
                ErrorKind.DENIED_BY_POLICY, revoked_message(session.pid, grant))
        return session

    def check_caption(self, session_id: str, caption: str) -> None:
        """Refuse a control the profile's denylist names.

        Checked against the *resolved* caption rather than the locator, so a
        locator that happens to match a denied control is caught even when
        it was not written to name one.
        """
        self.check_identity(session_id, [caption])

    def check_identity(self, session_id: str, identities: list[str]) -> None:
        """Refuse an element the denylist names by any of its identities.

        A window has one identity, its caption. An element that is not a
        window has several -- caption, type-qualified caption, automation
        id, and type-and-position under its host -- because an unlabelled
        button has to be deniable by *what it is*, and a caption is the one
        thing it does not have.
        """
        session = self.get(session_id)
        for identity in identities:
            match = denied(identity, list(session.profile.denylist))
            if match is not None:
                raise GhostdriverError(
                    ErrorKind.DENIED_BY_POLICY,
                    f"refusing to act on {match.describe()}",
                )


def revoked_message(pid: int, grant: Grant | None) -> str:
    """Why an open session is refused, naming the decision that did it.

    A session that was approved when it opened and refused three seconds
    later read as consent evaporating -- until the trace showed a second
    chat, sharing the same server process, recording a restriction for a
    target it had merely been told to leave alone (D64). The refusal now
    says when and via what the restriction arrived, that another chat may
    have recorded it, and how the operator reverses it.
    """
    if grant is None:
        cause = "its approval was withdrawn"
    else:
        cause = f"it was restricted at {grant.when()} via {grant.source.value}"
        if grant.note:
            cause += f" with the note {grant.note!r}"
        if grant.inherited_from:
            cause += f" (through pid {grant.inherited_from}, its ancestor)"
    return (
        f"pid {pid} is no longer approved for automation in this session: "
        f"{cause}. One server can serve several chats at once, so a "
        "restriction recorded in another chat applies here too. If the "
        f"operator still approves this target, record allow=[{pid}] and this "
        "session continues."
    )
