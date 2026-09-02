"""The rules, tested where they can be tested: everywhere.

A rule that only runs against a live desktop is a rule that will not be
exercised, which is the opposite of what a safety rule is for.
"""

from ghostdriver.policy import (
    MAX_DESCRIBED,
    ConsentSource,
    Grant,
    Tier,
    denied,
    describe_target,
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


# --- endpoints, which inform a decision rather than making one -----------

def test_the_endpoint_is_found_among_unrelated_arguments():
    endpoints = extract_endpoints(REAL_CMDLINE)

    assert len(endpoints) == 1
    e = endpoints[0]
    assert (e.scheme, e.host, e.port, e.path) == (
        "http", "devhost", 8183, "/devenv/gateway"
    )


def test_a_file_share_is_not_an_endpoint():
    """A certificate path is not the environment the target is driving, and
    showing it as one is noise in the question a person is being asked."""
    assert extract_endpoints([r"\\fileshare\certs\Root.p7b"]) == []


def test_endpoints_are_normalized_for_display():
    pasted = extract_endpoints(["HTTP://DevHost:8183/DevEnv/Gateway/"])[0]
    assert pasted.normalized == "http://devhost:8183/devenv/gateway"


def test_several_endpoints_are_all_returned():
    found = extract_endpoints(["https://a.example/one", "http://b.example:9/two"])
    assert [e.host for e in found] == ["a.example", "b.example"]


def test_a_target_with_no_endpoint_yields_nothing_rather_than_a_guess():
    """Best effort by design. A target that names its server another way
    leaves the person deciding with no endpoint rather than a wrong one."""
    assert extract_endpoints([r"C:\App.exe", "/flag", "--db=mydsn"]) == []


# --- the sentence a person is shown -------------------------------------

def test_the_description_says_which_application_and_where_it_points():
    """These are the two things that decide the answer."""
    line = describe_target("App.Exe", 1234, extract_endpoints(REAL_CMDLINE))

    assert "App.Exe" in line
    assert "1234" in line
    assert "http://devhost:8183/devenv/gateway" in line


def test_a_target_with_no_endpoint_says_so_plainly():
    """Silence would read as "nothing to worry about"."""
    line = describe_target("App.Exe", 1234, [])

    assert "no endpoint found" in line


# --- consent -------------------------------------------------------------

def test_a_grant_describes_itself_for_a_transcript():
    allowed = Grant(pid=1, allowed=True, source=ConsentSource.ELICITED)
    restricted = Grant(pid=2, allowed=False,
                       source=ConsentSource.OPERATOR_TOOL, note="production")

    assert "allowed" in allowed.describe() and "elicited" in allowed.describe()
    assert "restricted" in restricted.describe()
    assert "production" in restricted.describe()


def test_the_source_of_consent_is_kept_rather_than_collapsed():
    """The two carry different weight. `elicited` means the person answered
    through their own client, which the agent cannot forge; `operator_tool`
    means the agent claimed to relay an answer."""
    assert ConsentSource.ELICITED != ConsentSource.OPERATOR_TOOL


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
    it read_only cannot function against a minimized target."""
    assert permits(Tier.READ_ONLY, "restore")


def test_granting_targets_is_available_at_every_tier():
    """A person must be able to restrict a target from any session."""
    for tier in Tier:
        assert permits(tier, "grant_targets")


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


# --- endpoints inform a person's decision, so precision matters ----------

def test_a_non_network_scheme_is_not_an_endpoint():
    """Measured across 147 window-owning processes: most of what the old
    pattern found were not endpoints at all.

    `chrome-extension://` names a loaded extension, `file://` a local path.
    Neither answers "which environment is this pointed at", and under R1
    that line is what a person reads when deciding whether to allow
    automation -- so a confident wrong answer costs more than a blank.
    """
    found = extract_endpoints([
        "app.exe",
        "chrome-extension://fcoeoabgfenejglbffodgkkbkcdhcgfn",
        "file://C:/certs/client.pem",
        "ms-appx://microsoft.example/resources",
    ])

    assert found == []


def test_a_comma_separated_list_is_not_one_endpoint():
    """A policy allowlist run together produced a single endpoint whose host
    was eleven hosts joined by commas -- unreadable, and wrong."""
    found = extract_endpoints([
        "--allow=https://one.example.test,https://two.example.test",
    ])

    assert [e.host for e in found] == ["one.example.test", "two.example.test"]


def test_a_wildcard_pattern_is_not_a_host():
    """The wreckage of a mis-parsed policy entry, not somewhere a target
    connects."""
    found = extract_endpoints(["--policy=https://[*.]example.test/"])

    assert found == []


def test_the_same_server_twice_is_one_endpoint():
    """Repeating it pads the consent line without adding anything to decide
    on."""
    found = extract_endpoints([
        "--gateway=https://server.example.test/app",
        "--fallback=https://server.example.test/app/",
    ])

    assert len(found) == 1


def test_an_ordinary_gateway_still_extracts():
    """The case the whole thing exists for, and the shape a real target of
    this class uses: its server as a URL in its own command line."""
    found = extract_endpoints([
        "client.exe", "-OI", "http://host.example.test:8183/env/gateway",
    ])

    assert len(found) == 1
    assert found[0].host == "host.example.test"
    assert found[0].port == 8183
    assert found[0].normalized == "http://host.example.test:8183/env/gateway"


def test_a_long_list_is_summarised_rather_than_run_off_the_line():
    """A browser process can carry a dozen. A consent prompt that runs off
    the line is one nobody reads, and this is the sentence the decision
    rests on."""
    endpoints = extract_endpoints([
        f"--x=https://host{n}.example.test" for n in range(8)
    ])
    described = describe_target("app.exe", 42, endpoints)

    assert "host0.example.test" in described
    assert "and 5 more" in described
    assert described.count("example.test") == MAX_DESCRIBED


def test_no_endpoint_says_so_plainly():
    """A target that names its server another way is not suspicious; the
    person just gets one less thing to go on."""
    assert "no endpoint found" in describe_target("app.exe", 42, [])
