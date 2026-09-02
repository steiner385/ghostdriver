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

pytest.importorskip("mcp", reason="protocol layer is the [server] extra")

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TOOLS = {
    "list_targets", "attach", "release", "grant_targets",
    "describe", "find", "read", "capture", "wait_for",
    "probe", "surfaces", "modals", "restore",
}


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
