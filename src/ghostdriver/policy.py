"""What a session may do, and which targets it has been allowed to touch.

Three separate rules live here.

**Consent** decides which targets may be driven at all. It is granted per
chat session, at the moment it is needed, by the person running the session
— not by configuration written in advance and not by the agent. Nothing is
automatable until someone says so, and the answer dies with the session.

**Capability tier** decides what a session may do once attached.

**The denylist** decides which individual controls nobody may actuate,
whatever the tier.

Endpoint extraction also lives here, but it no longer decides anything. It
exists so that whoever is being asked "may I drive this?" can see what the
target is connected to before answering. A target's own command line
commonly carries its server endpoint, which is evidence it supplies for free
and cannot easily misreport — useful for informing a decision, and too
narrow to make one.
"""

import fnmatch
import re
import time
from dataclasses import dataclass, field
from enum import Enum


class Tier(str, Enum):
    """What a session may do. Set at attach, immutable for its lifetime."""

    READ_ONLY = "read_only"
    INTERACTIVE = "interactive"
    FULL = "full"


#: What each tier permits, by tool name.
#:
#: `restore` is the one entry here that changes what is on screen, and it
#: sits at read_only deliberately. The tier's promise is about the target's
#: *application state* — its data, its workflow — and restoring a window
#: touches none of that. Excluding it would make read_only useless against a
#: minimized target, which is the state a target is most often found in.
TIER_TOOLS: dict[Tier, frozenset[str]] = {
    Tier.READ_ONLY: frozenset({
        "list_targets", "attach", "release", "grant_targets",
        "describe", "find", "read", "capture", "wait_for",
        "probe", "surfaces", "modals", "restore", "hit_targets", "wait_idle",
        # Asks a person to do something and watches for them to have done
        # it. It changes nothing itself, and a read-only session has as much
        # need of it as any other -- "please sign in so I can see the
        # screen" is the commonest case there is. The person decides whether
        # to act; this only ever asks, and the ask is shown to them as
        # written.
        "await_human",
        # Recording a launch decision is consent bookkeeping, like
        # grant_targets -- available at every tier.
        "grant_launch",
    }),
    Tier.INTERACTIVE: frozenset({
        "click", "type_text", "set_value", "send_keys",
        # Brings a window forward on request. Interactive, because it
        # interrupts the operator; never automatic (D73).
        "foreground",
        # Reads the system clipboard: the result of a target's own Copy
        # command, which on some targets is the only exact read a grid has.
        # Interactive rather than read-only because the clipboard is the
        # person's as much as the target's.
        "read_clipboard",
        # Curation rather than actuation, but it belongs to this tier: the
        # evidence it writes can only be produced by a session that acted.
        "record_input_sensitivity",
    }),
    Tier.FULL: frozenset({
        "probe_phase2", "probe_grid", "grid_seek",
        # Launching a process is the widest authority the tool has, so it
        # sits at the top tier even though the session it opens may be
        # read-only.
        "launch_isolated",
    }),
}


def tools_for(tier: Tier) -> frozenset[str]:
    """Everything `tier` permits, including what lower tiers permit.

    The tiers are cumulative, so this is the only correct way to ask.
    Reading TIER_TOOLS directly gives an `interactive` session no read tools
    at all.
    """
    permitted = set(TIER_TOOLS[Tier.READ_ONLY])
    if tier in (Tier.INTERACTIVE, Tier.FULL):
        permitted |= TIER_TOOLS[Tier.INTERACTIVE]
    if tier is Tier.FULL:
        permitted |= TIER_TOOLS[Tier.FULL]
    return frozenset(permitted)


def permits(tier: Tier, tool: str) -> bool:
    return tool in tools_for(tier)


def tier_for(tool: str) -> Tier | None:
    """The lowest tier at which `tool` is permitted; None for no such tool.
    A refusal that names it is one round trip shorter than one that does
    not (D65)."""
    for tier in (Tier.READ_ONLY, Tier.INTERACTIVE, Tier.FULL):
        if tool in TIER_TOOLS[tier]:
            return tier
    return None


# --- consent -------------------------------------------------------------

class ConsentSource(str, Enum):
    """How a decision about a target was obtained.

    Recorded rather than collapsed to a boolean, because the two carry
    different weight. `elicited` means the server asked and the person
    answered through their own client, which the agent cannot forge.
    `operator_tool` means the agent called `grant_targets` claiming to relay
    an answer — true in practice, since the client shows the call before it
    runs, but an assertion rather than a signature.
    """

    ELICITED = "elicited"
    OPERATOR_TOOL = "operator_tool"


@dataclass(frozen=True, slots=True)
class Grant:
    """A decision about one target, for the life of one session."""

    pid: int
    allowed: bool
    source: ConsentSource
    note: str = ""
    #: Set when this decision was made about an ancestor process and applies
    #: to `pid` because it descends from that one. An application is a
    #: process tree, not a pid: the dialog a browser opens in a helper
    #: process is the same application the operator approved.
    inherited_from: int | None = None
    #: When the decision was recorded. A session refused because its target
    #: was restricted after it opened needs to say by which decision, and
    #: one server can be serving several chats at once (D64).
    at: float = field(default_factory=time.time)
    #: Read back from the consent store: made in an earlier server run about
    #: a process that is still running (R1a).
    restored: bool = False

    def describe(self) -> str:
        verdict = "allowed" if self.allowed else "restricted"
        detail = f" ({self.note})" if self.note else ""
        via = (f"via pid {self.inherited_from}, its parent" if self.inherited_from
               else f"via {self.source.value}")
        kept = " [kept from an earlier server run]" if self.restored else ""
        return f"pid {self.pid} {verdict} {via}{detail}{kept}"

    def when(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.at))


# --- endpoints, for informing a decision rather than making one ----------

#: A URL-shaped argument. Deliberately not matched against bare host:port or
#: UNC paths: a file share a target reads a certificate from is not the
#: environment it is driving, and showing it as one is noise in the question
#: a person is being asked.
#:
#: Stopping at a comma and a semicolon as well as whitespace, because
#: list-valued switches are common and a policy allowlist run together
#: produced a single "endpoint" whose host was eleven hosts joined by
#: commas. Measured across 147 window-owning processes on one machine.
_URL = re.compile(r"\b([a-z][a-z0-9+.-]*)://([^\s\"',;]+)", re.IGNORECASE)

#: Schemes that name a server a target talks to. Everything else is some
#: other kind of URL entirely -- `chrome-extension://` identifies a loaded
#: extension, `file://` a local path, `ms-appx://` a packaged resource --
#: and none of them answers "which environment is this pointed at". Showing
#: one as if it did is worse than showing nothing, because this line is what
#: a person reads when deciding whether to allow automation.
NETWORK_SCHEMES: frozenset[str] = frozenset({"http", "https", "ws", "wss"})

#: How many endpoints to name before summarising. A browser process can
#: carry a dozen; a consent prompt that runs off the line is one nobody
#: reads.
MAX_DESCRIBED = 3


@dataclass(frozen=True, slots=True)
class Endpoint:
    """A server location a target appears to be connected to."""

    raw: str
    scheme: str
    host: str
    port: int | None
    path: str

    @property
    def normalized(self) -> str:
        port = f":{self.port}" if self.port else ""
        return f"{self.scheme}://{self.host}{port}{self.path}".rstrip("/").lower()


def _plausible_host(host: str) -> bool:
    """Whether this looks like somewhere a target could actually connect.

    Cheap structural checks, not validation. What they exclude is the
    wreckage of a mis-parse -- an empty authority, a wildcard pattern out of
    a policy list -- rather than any host that merely looks unusual.
    """
    if not host or host.startswith(("*", "[")):
        return False
    return all(c.isalnum() or c in ".-_" for c in host)


def extract_endpoints(command_line: list[str]) -> list[Endpoint]:
    """Network endpoints named in `command_line`, in order, without repeats.

    Best effort by design. A target that names its server some other way --
    a DSN, a bare host:port, a config file -- yields nothing here, and the
    person deciding simply sees no endpoint rather than a wrong one.

    "Rather than a wrong one" is the part that had to be earned. Measured
    across 147 window-owning processes: 10 yielded something, and most of
    those somethings were not endpoints at all -- extension identifiers, a
    crash-reporting URL, a policy allowlist mangled into one host. Under R1
    this line informs a person's consent decision, so a confident wrong
    answer costs more than a blank.
    """
    found: list[Endpoint] = []
    seen: set[str] = set()
    for argument in command_line:
        for match in _URL.finditer(argument):
            scheme, rest = match.group(1).lower(), match.group(2)
            if scheme not in NETWORK_SCHEMES:
                continue
            authority, _, path = rest.partition("/")
            host, _, port_text = authority.partition(":")
            if not _plausible_host(host):
                continue
            try:
                port = int(port_text) if port_text else None
            except ValueError:
                port = None
            endpoint = Endpoint(
                raw=match.group(0),
                scheme=scheme,
                host=host.lower(),
                port=port,
                path=f"/{path}" if path else "",
            )
            # The same server named twice in one command line is one
            # server. Repeating it pads the consent line without adding
            # anything to decide on.
            if endpoint.normalized in seen:
                continue
            seen.add(endpoint.normalized)
            found.append(endpoint)
    return found


def describe_target(name: str, pid: int, endpoints: list[Endpoint]) -> str:
    """One line naming a target and where it is pointed.

    This is the sentence a person is shown when asked whether to allow
    automation, so it says the two things that decide the answer: which
    application, and which environment.
    """
    if not endpoints:
        where = "no endpoint found in its command line"
    else:
        shown = [e.normalized for e in endpoints[:MAX_DESCRIBED]]
        extra = len(endpoints) - len(shown)
        where = ", ".join(shown)
        if extra:
            where += f", and {extra} more"
    return f"{name} (pid {pid}) -- {where}"


# --- denylist ------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DenyMatch:
    caption: str
    pattern: str

    def describe(self) -> str:
        return f"{self.caption!r} matches denylist pattern {self.pattern!r}"


def denied(caption: str, denylist: list[str]) -> DenyMatch | None:
    """Whether a control's caption is one no session may actuate.

    Matched case-insensitively against the whole caption. Patterns are
    fnmatch, so an operator writes `*Delete*` rather than a regex — the
    people who curate this list are not necessarily the people who wrote
    the tool.
    """
    lowered = caption.lower()
    for pattern in denylist:
        if fnmatch.fnmatch(lowered, pattern.lower()):
            return DenyMatch(caption=caption, pattern=pattern)
    return None
