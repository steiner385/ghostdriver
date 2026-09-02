"""What a session is allowed to do, and against which environment.

Two rules live here, both of which exist to convert operator discipline into
something the tool enforces.

The **environment guard** answers "is this target pointed at somewhere I am
allowed to drive". A client's own command line commonly carries the server
endpoint it connected to, which is evidence the target supplies for free and
cannot easily misreport. Checking it turns "never automate against
production" from a thing someone remembers into a thing that fails.

The **capability tier** answers "is this session allowed to do that at all",
and the **denylist** answers "is this specific control one nobody may touch".

All of it is pure. A safety rule that can only be tested against a live
desktop is a safety rule that will not be tested.
"""

import fnmatch
import re
from dataclasses import dataclass, field
from enum import Enum


class Tier(str, Enum):
    """What a session may do. Set at attach, immutable for its lifetime."""

    READ_ONLY = "read_only"
    INTERACTIVE = "interactive"
    FULL = "full"


#: What each tier permits, by tool name.
#:
#: `restore` is the one entry here that changes what is on screen, and it sits
#: at read_only deliberately. The tier's promise is about the target's
#: *application state* -- its data, its workflow -- and restoring a window
#: touches none of that. Excluding it would make read_only useless against a
#: minimized target, which is the state a target is most often found in and
#: the one where nothing can be read at all. It is also the one operation
#: measured not to take the foreground.
TIER_TOOLS: dict[Tier, frozenset[str]] = {
    Tier.READ_ONLY: frozenset({
        "list_targets", "attach", "release",
        "describe", "find", "read", "capture", "wait_for",
        "probe", "surfaces", "modals", "restore",
    }),
    Tier.INTERACTIVE: frozenset({
        "click", "type_text", "set_value", "send_keys", "await_human",
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


# --- environment guard ---------------------------------------------------

#: A URL-shaped argument. Deliberately not matched against bare host:port or
#: UNC paths: a file share a target reads a certificate from is not the
#: environment it is driving, and treating it as one would make operators
#: allowlist things that carry no risk -- which is how allowlists end up
#: written as "*".
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
        """The form an allowlist pattern is matched against.

        Lowercased and with any trailing slash removed, so that an operator
        copying an endpoint out of an error message and pasting it into the
        allowlist gets a match rather than a near-miss.
        """
        port = f":{self.port}" if self.port else ""
        return f"{self.scheme}://{self.host}{port}{self.path}".rstrip("/").lower()


def extract_endpoints(command_line: list[str]) -> list[Endpoint]:
    """Every URL-shaped argument in `command_line`, in order."""
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


class GuardVerdict(str, Enum):
    ALLOWED = "allowed"
    #: An endpoint was found and does not match the allowlist.
    REFUSED = "refused"
    #: No endpoint could be extracted, so the question was never answered.
    #: Distinct from REFUSED because the remedy differs: one needs the
    #: allowlist widened, the other needs a human to say what this target is
    #: actually talking to.
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True, slots=True)
class GuardResult:
    verdict: GuardVerdict
    endpoints: tuple[Endpoint, ...] = ()
    allowlist: tuple[str, ...] = ()
    overridden: bool = False
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.verdict is GuardVerdict.ALLOWED or self.overridden


def check_environment(
    command_line: list[str],
    allowlist: list[str],
    *,
    override: bool = False,
) -> GuardResult:
    """Decide whether a target may be driven, from its own command line.

    Fails closed in both directions that matter. An endpoint that matches
    nothing is refused, and a target whose endpoint cannot be determined at
    all is refused too -- the spec is explicit that an unanswerable question
    is not the same as a yes.

    **Every** endpoint must match. A target connected to an allowed server
    and an unknown one is not partially safe to drive.

    `override` does not skip the check; it records that a human overrode a
    stated verdict, which is what makes the decision auditable afterwards.
    """
    endpoints = tuple(extract_endpoints(command_line))
    patterns = tuple(allowlist)

    if not endpoints:
        return GuardResult(
            verdict=GuardVerdict.INDETERMINATE,
            allowlist=patterns,
            overridden=override,
            reason=(
                "no endpoint could be extracted from the target's command "
                "line, so which environment it is connected to is unknown"
            ),
        )

    if not patterns:
        return GuardResult(
            verdict=GuardVerdict.REFUSED,
            endpoints=endpoints,
            overridden=override,
            reason=(
                "the profile's environment_allowlist is empty, so no "
                "environment has been approved for automation"
            ),
        )

    unmatched = [
        e for e in endpoints
        if not any(fnmatch.fnmatch(e.normalized, p.lower()) for p in patterns)
    ]
    if unmatched:
        return GuardResult(
            verdict=GuardVerdict.REFUSED,
            endpoints=endpoints,
            allowlist=patterns,
            overridden=override,
            reason=(
                "not in environment_allowlist: "
                + ", ".join(e.normalized for e in unmatched)
            ),
        )

    return GuardResult(
        verdict=GuardVerdict.ALLOWED,
        endpoints=endpoints,
        allowlist=patterns,
        reason="every endpoint matches the profile's environment_allowlist",
    )


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
    fnmatch, so an operator writes `*Delete*` rather than a regex -- the
    people who curate this list are not necessarily the people who wrote
    the tool.
    """
    lowered = caption.lower()
    for pattern in denylist:
        if fnmatch.fnmatch(lowered, pattern.lower()):
            return DenyMatch(caption=caption, pattern=pattern)
    return None
