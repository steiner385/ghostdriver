"""The server as a client actually meets it: a subprocess over stdio.

Everything else exercises the server in-process. This is the only test that
proves the installed entry point starts, speaks the protocol, and survives a
real initialize handshake -- the failure mode being a server that works
perfectly when imported and does not run when launched.

Slow by nature (it spawns an interpreter), so it stays deliberately small:
one handshake, one listing, one call.
"""

import asyncio
import os
import sys

import pytest

from tests.conftest import mcp_or_skip, on_windows

# See conftest.mcp_or_skip: gated on the distribution version, because the
# module does not always carry a `__version__` to gate on (#53).
mcp_or_skip()

# Imported after the gate on purpose, which is why these carry a noqa: on a
# 1.x install `mcp.client.stdio` does not exist, so importing it at the top
# of the file would raise the ModuleNotFoundError the gate exists to turn
# into a skip. ruff waives E402 after `pytest.importorskip` by name; it
# cannot know this call does the same job.
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

pytestmark = pytest.mark.slow

READ_TOOLS = {
    "list_targets", "attach", "release", "grant_targets",
    "describe", "find", "read", "capture", "wait_for",
    "probe", "surfaces", "modals", "restore", "foreground", "await_human",
    "hit_targets", "read_clipboard", "wait_idle",
}

#: Reachable only from a session opened at the interactive tier. Registered
#: unconditionally -- the tier check happens per call, against the session,
#: because a server cannot know at startup which tier a caller will open.
ACTUATION_TOOLS = {"click", "type_text", "set_value", "send_keys"}

#: Same tier, but it curates rather than actuates -- so it is not
#: expected to carry the non-idempotent annotation the others do.
CURATION_TOOLS = {"record_input_sensitivity"}

#: The `full` tier, which nothing grants by default. It actuates
#: controls an operator listed, to learn how they respond.
LEARNING_TOOLS = {"probe_phase2", "probe_grid", "grid_seek"}

#: Session-creating / consent tools for the launch path. Gated by
#: command approval, not by a session tier.
LAUNCH_TOOLS = {"launch_isolated", "grant_launch"}

EXPECTED_TOOLS = (READ_TOOLS | ACTUATION_TOOLS | CURATION_TOOLS
                  | LEARNING_TOOLS | LAUNCH_TOOLS)


def _server_parameters() -> StdioServerParameters:
    """How to spawn the server, with an environment it can actually run in.

    `StdioServerParameters` passes **no environment through by default**, so
    a child spawned from a source checkout could not import `ghostdriver` at
    all and died with `ModuleNotFoundError` before speaking a word of the
    protocol. The client then saw only "Connection closed", which names the
    symptom and hides the cause entirely.

    Invisible until now because this module was skipping in its entirety on
    a bad version gate (#53). Carrying `PYTHONPATH` explicitly keeps it
    working from a checkout as well as from an installed package.
    """
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "ghostdriver.mcp_server"],
        env={**os.environ, "PYTHONPATH": os.environ.get("PYTHONPATH", "src")},
    )


async def _drive_uia(pid: int):
    """Attach to a real window and call a tool that walks the UIA tree.

    The point is the *transport*, not the tool. A stdio server speaks
    JSON-RPC over stdout, so anything else writing there corrupts the
    stream and kills the connection -- and the accessibility path pulls in
    COM machinery that emits diagnostics of its own. `list_targets` never
    touches any of it, so the one tool proven over the wire was the one
    that could not have hit the hazard.
    """
    parameters = _server_parameters()
    async with (stdio_client(parameters) as (read, write),
                ClientSession(read, write) as session):
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
    parameters = _server_parameters()
    async with (stdio_client(parameters) as (read, write),
                ClientSession(read, write) as session):
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

    # A result, not a successful one. The subject is the transport, and a
    # machine with no accessibility service is entitled to answer "not
    # actionable" -- requiring a desktop here would fail on any headless box
    # while the transport worked perfectly (#39).
    #
    # A refusal crossing the wire intact is arguably the better proof: it is
    # a nested structure the server built, serialised, and handed back.
    assert "ok" in payload, payload
    if payload["ok"]:
        assert "targets" in payload
    else:
        assert payload["error"]["kind"] == "not_actionable", payload


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
