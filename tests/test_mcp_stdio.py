"""The server as a client actually meets it: a subprocess over stdio.

Everything else exercises the server in-process. This is the only test that
proves the installed entry point starts, speaks the protocol, and survives a
real initialize handshake -- the failure mode being a server that works
perfectly when imported and does not run when launched.

Slow by nature (it spawns an interpreter), so it stays deliberately small:
one handshake, one listing, one call.
"""

import asyncio
import sys

import pytest

from tests.conftest import on_windows

pytest.importorskip("mcp", reason="protocol layer is the [server] extra")

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

READ_TOOLS = {
    "list_targets", "attach", "release", "grant_targets",
    "describe", "find", "read", "capture", "wait_for",
    "probe", "surfaces", "modals", "restore", "await_human",
}

#: Reachable only from a session opened at the interactive tier. Registered
#: unconditionally -- the tier check happens per call, against the session,
#: because a server cannot know at startup which tier a caller will open.
ACTUATION_TOOLS = {"click", "type_text", "set_value", "send_keys"}

#: Same tier, but it curates rather than actuates -- so it is not
#: expected to carry the non-idempotent annotation the others do.
CURATION_TOOLS = {"record_input_sensitivity"}

EXPECTED_TOOLS = READ_TOOLS | ACTUATION_TOOLS | CURATION_TOOLS


async def _drive_uia(pid: int):
    """Attach to a real window and call a tool that walks the UIA tree.

    The point is the *transport*, not the tool. A stdio server speaks
    JSON-RPC over stdout, so anything else writing there corrupts the
    stream and kills the connection -- and the accessibility path pulls in
    COM machinery that emits diagnostics of its own. `list_targets` never
    touches any of it, so the one tool proven over the wire was the one
    that could not have hit the hazard.
    """
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ghostdriver.mcp_server"],
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool("grant_targets", {"allow": [pid],
                                                      "note": "stdio test"})
            attached = await session.call_tool("attach", {"pid": pid})
            session_id = attached.structured_content["session_id"]
            surfaces = await session.call_tool(
                "surfaces", {"session_id": session_id}
            )
            # A second call after the UIA walk: if the stream had been
            # corrupted, this is what would fail.
            still_alive = await session.call_tool(
                "modals", {"session_id": session_id}
            )
            return surfaces.structured_content, still_alive.structured_content


async def _drive():
    # Launched by module rather than by console script, so the test does not
    # depend on the entry point having been installed into PATH -- while
    # still going through exactly the `main()` that entry point calls.
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ghostdriver.mcp_server"],
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool("list_targets", {})
            return initialized, tools, result


def test_a_client_can_initialize_list_and_call_over_stdio():
    initialized, tools, result = asyncio.run(_drive())

    assert initialized.server_info.name == "ghostdriver"
    assert initialized.instructions, "the target-class briefing reaches clients"

    assert {t.name for t in tools.tools} == EXPECTED_TOOLS

    payload = result.structured_content
    assert payload is not None, "structured output survives the transport"
    assert payload["ok"] is True
    assert "targets" in payload


@on_windows
def test_a_uia_walking_tool_survives_the_transport(win32_target):
    """The gap the first version of this test left open.

    `surfaces` walks the accessibility tree, which loads COM machinery that
    logs on first use. Those messages go to stderr -- checked -- but the
    check is worth nothing unless something actually exercises the path
    over a real stdio connection, and nothing did.
    """
    surfaces, still_alive = asyncio.run(_drive_uia(win32_target))

    assert surfaces is not None, "structured output survived the walk"
    assert surfaces["ok"] is True
    assert surfaces["kinds"], "the tool did real work, not an early return"

    # The connection is the actual subject. A corrupted stream would have
    # failed this call, or hung.
    assert still_alive is not None
    assert still_alive["ok"] is True
