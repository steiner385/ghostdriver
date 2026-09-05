"""The protocol layer's dependency contract, checked without that dependency.

`tests/test_mcp_server.py` skips wholesale unless mcp 2.x is installed, which
is right for testing the server and wrong for testing what happens when it is
*absent or the wrong version*. That case needs a module with no such gate, or
the only machines that check it are the ones that cannot hit the bug.
"""

import sys

import pytest


def test_a_wrong_mcp_version_is_explained_not_traced(monkeypatch):
    """`pyproject` pins the `[server]` extra to mcp 2.x, because FastMCP was
    renamed to MCPServer at that boundary and 1.x and 2.x are not
    interchangeable.

    A 1.x install satisfies `import mcp` and then fails deep inside on
    `mcp.server.mcpserver`, so starting the server printed
    `ModuleNotFoundError: No module named 'mcp.server.mcpserver'` -- a module
    the reader has never heard of, and no mention of the version pin that
    explains it.

    Found by starting the server on a machine that happened to have 1.28.
    """
    from ghostdriver import mcp_server

    monkeypatch.setitem(sys.modules, "mcp.server.mcpserver", None)

    with pytest.raises(RuntimeError) as caught:
        mcp_server.build_server()

    message = str(caught.value)
    assert "2.1" in message, message
    assert "[server]" in message, message
    assert "mcpserver" not in message.replace("mcp.server.mcpserver", ""), message
