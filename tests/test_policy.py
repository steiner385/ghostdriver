"""The safety rules, tested where they can be tested: everywhere.

A rule that only runs against a live desktop is a rule that will not be
exercised, which is the opposite of what a safety rule is for.
"""

import pytest

from ghostdriver.policy import (
    GuardVerdict,
    Tier,
    check_environment,
    denied,
    extract_endpoints,
    permits,
    tools_for,
)

# The shape a real target's command line takes: the endpoint sits among
# unrelated switches, and a file share it reads a certificate from sits
# there too.
REAL_CMDLINE = [
    r"C:\Program Files (x86)\Vendor\Client\App.Exe",
    "/od",
    "http://devhost:8183/devenv/gateway",
    "/xc",
    "/cl",
    r"\\fileshare\Applications\certs\Root.p7b",
    "-oi",
    "SOME_CONFIG",
]


# --- endpoint extraction -------------------------------------------------

def test_the_endpoint_is_found_among_unrelated_arguments():
    endpoints = extract_endpoints(REAL_CMDLINE)

    assert len(endpoints) == 1
    e = endpoints[0]
    assert (e.scheme, e.host, e.port, e.path) == (
        "http", "devhost", 8183, "/devenv/gateway"
    )


def test_a_file_share_is_not_an_endpoint():
    """A certificate path is not the environment the target is driving.

    Treating it as one makes operators allowlist things that carry no risk,
    which is how an allowlist ends up written as "*".
    """
    assert extract_endpoints([r"\\fileshare\certs\Root.p7b"]) == []


def test_normalization_survives_copy_and_paste():
    """The refusal message prints the endpoint so an operator can paste it
    into the allowlist. That round trip has to match."""
    pasted = extract_endpoints(["HTTP://DevHost:8183/DevEnv/Gateway/"])[0]
    assert pasted.normalized == "http://devhost:8183/devenv/gateway"

    result = check_environment(REAL_CMDLINE, [pasted.normalized])
    assert result.verdict is GuardVerdict.ALLOWED


def test_several_endpoints_are_all_returned():
    found = extract_endpoints(["https://a.example/one", "http://b.example:9/two"])
    assert [e.host for e in found] == ["a.example", "b.example"]


# --- the guard -----------------------------------------------------------

def test_an_allowlisted_endpoint_is_allowed():
    result = check_environment(REAL_CMDLINE, ["http://devhost:8183/*"])

    assert result.verdict is GuardVerdict.ALLOWED
    assert result.ok


def test_an_endpoint_outside_the_allowlist_is_refused():
    result = check_environment(REAL_CMDLINE, ["http://prodhost:8183/*"])

    assert result.verdict is GuardVerdict.REFUSED
    assert not result.ok


def test_the_refusal_names_the_endpoint_it_refused():
    """Otherwise curating the allowlist is guesswork."""
    result = check_environment(REAL_CMDLINE, ["http://prodhost/*"])

    assert "http://devhost:8183/devenv/gateway" in result.reason


def test_an_empty_allowlist_refuses_rather_than_permits():
    """The probe emits environment_allowlist empty, for curation. Until
    somebody curates it, nothing has been approved -- and an empty list
    read as "no restrictions" would make every freshly probed application
    automatable against production by default."""
    result = check_environment(REAL_CMDLINE, [])

    assert result.verdict is GuardVerdict.REFUSED
    assert "empty" in result.reason


def test_an_unextractable_endpoint_is_indeterminate_not_refused():
    """Distinct verdicts because the remedies differ: one needs the
    allowlist widened, the other needs a human to say what this target is
    talking to."""
    result = check_environment([r"C:\App.exe", "/flag"], ["http://devhost/*"])

    assert result.verdict is GuardVerdict.INDETERMINATE
    assert not result.ok


def test_every_endpoint_must_match_not_merely_one():
    """A target connected to an approved server and an unknown one is not
    partially safe to drive."""
    both = ["http://devhost:8183/env/gateway", "http://elsewhere:9/x"]
    result = check_environment(both, ["http://devhost:8183/*"])

    assert result.verdict is GuardVerdict.REFUSED
    assert "elsewhere" in result.reason


def test_an_override_records_the_verdict_it_overrode():
    """An override that erased the finding would leave nothing to audit."""
    result = check_environment(REAL_CMDLINE, ["http://prodhost/*"], override=True)

    assert result.ok, "the override permits it"
    assert result.verdict is GuardVerdict.REFUSED, "and the verdict still stands"
    assert result.overridden


def test_a_pattern_cannot_match_by_accident_across_a_host_boundary():
    """`devhost` must not admit `devhost.evil.example`."""
    result = check_environment(
        ["http://devhost.evil.example/gateway"], ["http://devhost/*"]
    )
    assert result.verdict is GuardVerdict.REFUSED


# --- tiers ---------------------------------------------------------------

def test_read_only_permits_reading_and_nothing_else():
    assert permits(Tier.READ_ONLY, "describe")
    assert permits(Tier.READ_ONLY, "read")
    assert not permits(Tier.READ_ONLY, "click")
    assert not permits(Tier.READ_ONLY, "type_text")


def test_tiers_are_cumulative():
    """Reading TIER_TOOLS directly would give an interactive session no read
    tools at all, which is the bug this function exists to prevent."""
    assert permits(Tier.INTERACTIVE, "describe")
    assert permits(Tier.INTERACTIVE, "click")
    assert permits(Tier.FULL, "describe")
    assert permits(Tier.FULL, "click")
    assert permits(Tier.FULL, "probe_phase2")
    assert not permits(Tier.INTERACTIVE, "probe_phase2")


def test_restore_is_available_to_a_read_only_session():
    """It changes what is on screen but no application state, and without
    it read_only cannot function against a minimized target -- which is the
    state a target is most often found in."""
    assert permits(Tier.READ_ONLY, "restore")


def test_an_unknown_tool_is_permitted_by_nothing():
    for tier in Tier:
        assert not permits(tier, "rm_minus_rf")


def test_every_tool_named_in_any_tier_is_reachable_at_full():
    """A tool nobody can ever call is a bug, not a safety feature."""
    from ghostdriver.policy import TIER_TOOLS

    every = set().union(*TIER_TOOLS.values())
    assert every == set(tools_for(Tier.FULL))


# --- denylist ------------------------------------------------------------

def test_a_denied_caption_is_matched_case_insensitively():
    match = denied("Confirm Delete Record", ["*delete*"])

    assert match is not None
    assert match.pattern == "*delete*"


def test_an_allowed_caption_passes():
    assert denied("Expand All", ["*delete*", "*submit*"]) is None


def test_the_match_explains_itself():
    """It ends up in a refusal an operator has to act on."""
    described = denied("Complete Task", ["*complete*"]).describe()
    assert "Complete Task" in described and "*complete*" in described


def test_an_empty_denylist_denies_nothing():
    assert denied("Delete Everything", []) is None
