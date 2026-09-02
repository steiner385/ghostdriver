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
from dataclasses import dataclass
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
        "probe", "surfaces", "modals", "restore",
        # Asks a person to do something and watches for them to have done
        # it. It changes nothing itself, and a read-only session has as much
        # need of it as any other -- "please sign in so I can see the
        # screen" is the commonest case there is. The person decides whether
        # to act; this only ever asks, and the ask is shown to them as
        # written.
        "await_human",
    }),
    Tier.INTERACTIVE: frozenset({
        "click", "type_text", "set_value", "send_keys",
        # Curation rather than actuation, but it belongs to this tier: the
        # evidence it writes can only be produced by a session that acted.
        "record_input_sensitivity",
    }),
    Tier.FULL: frozenset({"probe_phase2"}),
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

    def describe(self) -> str:
        verdict = "allowed" if self.allowed else "restricted"
        detail = f" ({self.note})" if self.note else ""
        return f"pid {self.pid} {verdict} via {self.source.value}{detail}"


# --- endpoints, for informing a decision rather than making one ----------

#: A URL-shaped argument. Deliberately not matched against bare host:port or
#: UNC paths: a file share a target reads a certificate from is not the
#: environment it is driving, and showing it as one is noise in the question
#: a person is being asked.
_URL = re.compile(r"\b([a-z][a-z0-9+.-]*)://([^\s\"']+)", re.IGNORECASE)


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


def extract_endpoints(command_line: list[str]) -> list[Endpoint]:
    """Every URL-shaped argument in `command_line`, in order.

    Best effort by design. A target that names its server some other way —
    a DSN, a bare host:port, a config file — yields nothing here, and the
    person deciding simply sees no endpoint rather than a wrong one.
    """
    found: list[Endpoint] = []
    for argument in command_line:
        for match in _URL.finditer(argument):
            scheme, rest = match.group(1).lower(), match.group(2)
            authority, _, path = rest.partition("/")
            host, _, port_text = authority.partition(":")
            try:
                port = int(port_text) if port_text else None
            except ValueError:
                port = None
            found.append(
                Endpoint(
                    raw=match.group(0),
                    scheme=scheme,
                    host=host.lower(),
                    port=port,
                    path=f"/{path}" if path else "",
                )
            )
    return found


def describe_target(name: str, pid: int, endpoints: list[Endpoint]) -> str:
    """One line naming a target and where it is pointed.

    This is the sentence a person is shown when asked whether to allow
    automation, so it says the two things that decide the answer: which
    application, and which environment.
    """
    where = (
        ", ".join(e.normalized for e in endpoints)
        if endpoints
        else "no endpoint found in its command line"
    )
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
