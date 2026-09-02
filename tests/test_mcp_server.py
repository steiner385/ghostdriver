"""The protocol binding.

These go through the server's own dispatch rather than calling `Toolbox`
directly, which is what makes them worth having separately: a tool that is
registered but unreachable, or whose schema rejects an argument the
implementation accepts, fails here and nowhere else.

The binding is meant to be dull. Anything here that tests *behaviour* rather
than *wiring* belongs in test_tools.py, and its presence here would mean a
decision had leaked into the adapter.
"""

import asyncio

import pytest

from ghostdriver.session import SessionManager
from tests.conftest import on_windows

mcp = pytest.importorskip(
    "mcp", reason="the protocol layer is an optional extra: pip install -e .[server]"
)

READ_TOOLS = {
    "list_targets", "attach", "release", "grant_targets",
    "describe", "find", "read", "capture", "wait_for",
    "probe", "surfaces", "modals", "restore",
}

#: Reachable only from a session opened at the interactive tier. Registered
#: unconditionally -- the tier check happens per call, against the session,
#: because a server cannot know at startup which tier a caller will open.
ACTUATION_TOOLS = {"click", "type_text", "set_value", "send_keys"}

#: Same tier, but it curates rather than actuates -- so it is not
#: expected to carry the non-idempotent annotation the others do.
CURATION_TOOLS = {"record_input_sensitivity"}

EXPECTED_TOOLS = READ_TOOLS | ACTUATION_TOOLS | CURATION_TOOLS


@pytest.fixture
def server():
    from ghostdriver.mcp_server import build_server

    return build_server(SessionManager())


def call(server, name, **arguments):
    """Invoke a tool the way a client does, through the server's dispatch.

    Returns the structured content rather than the text rendering: that is
    what a client with structured-output support receives, and asserting on
    it proves the output schema is actually populated.
    """
    result = asyncio.run(server.call_tool(name, arguments))
    return result.structured_content


def listed(server):
    return {t.name: t for t in asyncio.run(server.list_tools())}


# --- wiring --------------------------------------------------------------

def test_every_tool_is_registered(server):
    assert set(listed(server)) == EXPECTED_TOOLS


def test_actuation_is_annotated_as_changing_things(server):
    """The annotations are how a client decides how much ceremony a call
    deserves, so getting them wrong is a safety problem rather than a
    cosmetic one.

    Not idempotent, and that is the load-bearing part: clicking twice is two
    clicks, and a client that retried on a timeout would submit twice.
    """
    tools = listed(server)

    for name in ACTUATION_TOOLS:
        annotations = tools[name].annotations
        assert annotations.read_only_hint is False, name
        assert annotations.idempotent_hint is False, name


def test_reads_are_still_annotated_as_reads(server):
    """Adding actuation must not quietly relabel everything else."""
    tools = listed(server)
    unmarked = [
        name for name in READ_TOOLS
        # `attach` and `restore` are deliberately not read-only: one records
        # a decision, the other changes what is on screen.
        if name not in ("attach", "restore", "grant_targets", "release")
        and tools[name].annotations.read_only_hint is not True
    ]

    assert unmarked == []


def test_nothing_launches_a_process(server):
    """Still true, and still worth asserting. Starting an application is a
    different kind of authority from driving one already running, and
    nothing here has been given it."""
    assert "launch" not in set(listed(server))


def test_every_tool_carries_a_description(server):
    """The description is the interface. An agent that does not know menus
    are separate windows will search one and conclude a control is absent."""
    for name, tool in listed(server).items():
        assert tool.description, f"{name} has no description"
        assert len(tool.description) > 40, f"{name}'s description says little"


def test_the_server_explains_the_target_class_up_front(server):
    """Four facts an agent cannot infer from the tool list alone."""
    # Normalized, because the text is wrapped and a sentence that spans a
    # line break would fail a naive substring check.
    instructions = " ".join(server.instructions.split())
    assert "separate top-level windows" in instructions
    assert "modal dialog disables the window" in instructions
    # What an agent most needs told, because the tool list cannot say it:
    # delivering input and having an effect are different on this class of
    # target, and a result only claims the second when asked to check.
    assert "Delivering input is not the same" in instructions
    assert "interactive" in instructions, "the tier actuation needs"


def test_required_arguments_are_marked_required(server):
    tools = listed(server)
    assert "pid" in tools["attach"].input_schema["required"]
    for name in ("find", "read", "wait_for"):
        required = tools[name].input_schema["required"]
        assert {"session_id", "locator"} <= set(required), name


def test_optional_arguments_are_genuinely_optional(server):
    """A client that omits them must not be rejected by the schema."""
    tools = listed(server)
    assert "all_windows" not in tools["find"].input_schema.get("required", [])
    assert "tier" not in tools["attach"].input_schema.get("required", [])


# --- dispatch ------------------------------------------------------------

def test_a_tool_reached_through_dispatch_returns_its_result(server):
    payload = call(server, "list_targets")
    assert payload.get("ok") is True
    assert "targets" in payload


def test_an_error_comes_back_as_a_result_not_an_exception(server):
    """An agent has to be able to read a refusal and change course. A
    protocol-level exception gives it nothing to act on."""
    payload = call(server, "describe", session_id="no-such-session")

    assert payload.get("ok") is False
    assert payload["error"]["kind"] == "not_found"


def test_an_unknown_tool_is_rejected(server):
    with pytest.raises(Exception):
        call(server, "delete_everything")


@on_windows
def test_a_full_session_works_end_to_end_through_the_protocol(
    server, win32_target
):
    """attach, describe, find, read, release -- the read-only tier's whole
    arc, driven the way a client drives it."""
    call(server, "grant_targets", allow=[win32_target], note="test")
    attached = call(server, "attach", pid=win32_target)
    assert attached["ok"], attached
    session = attached["session_id"]

    described = call(server, "describe", session_id=session)
    assert described["ok"]
    assert "GhostdriverTestWindow" in described["windows"][0]["tree"]

    found = call(server, "find", session_id=session,
                 locator='class=Button text="Expand All"')
    assert found["match_count"] == 1

    values = call(server, "read", session_id=session,
                  locator="class=Edit")
    assert values["ok"] and values["unanswered"] == 0

    released = call(server, "release", session_id=session)
    assert released["ok"]

    after = call(server, "describe", session_id=session)
    assert after["ok"] is False, "the session is gone"


@on_windows
def test_an_undecided_target_asks_through_the_protocol(server, win32_target):
    """Consent is the gate, and an agent meets it here.

    This client cannot be elicited from, so the result carries what the
    agent needs in order to ask a person and record the answer.
    """
    refused = call(server, "attach", pid=win32_target)

    assert refused["ok"] is False
    assert refused["needs_consent"] is True
    assert "grant_targets" in refused["error"]["message"]


def test_read_tools_are_annotated_read_only(server):
    """So a client can decide how much ceremony a call deserves rather than
    treating every tool as potentially destructive."""
    tools = listed(server)
    for name in ("describe", "find", "read", "capture", "surfaces", "modals"):
        assert tools[name].annotations.read_only_hint is True, name
    # restore changes what is on screen, even though it changes no
    # application state, so it is deliberately not marked read-only.
    assert tools["restore"].annotations.read_only_hint is False
