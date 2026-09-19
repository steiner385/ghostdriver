"""The protocol layer's dependency contract, checked without that dependency.

`tests/test_mcp_server.py` skips wholesale unless mcp 2.x is installed, which
is right for testing the server and wrong for testing what happens when it is
*absent or the wrong version*. That case needs a module with no such gate, or
the only machines that check it are the ones that cannot hit the bug.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import (
    MCP_MINIMUM,
    protocol_layer_refusal,
    refuse_unusable_protocol_layer,
)

REPO = Path(__file__).resolve().parents[1]


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


# --- the gate's own report, per D#53's other half (#159) ----------------------
#
# `protocol_layer_refusal` is fed a version rather than asked to inspect the
# environment, so these run everywhere and need no broken install. That is the
# same move CLAUDE.md prescribes for a guard whose condition is hard to stage:
# make the subject fail on purpose rather than gate the test on the failure.


def test_a_new_enough_distribution_is_not_refused():
    assert protocol_layer_refusal("2.1.1") is None


def test_the_minimum_itself_is_not_refused():
    """The pin is `>=2.1`, so 2.1 exactly is usable. An off-by-one here
    refuses every correct install, which is the loudest possible way to be
    wrong and still worth a test."""
    assert protocol_layer_refusal(MCP_MINIMUM) is None


def test_a_prerelease_of_the_minimum_is_not_refused():
    """`_version_tuple` stops at the first non-integer component, so 2.1.0rc1
    compares as (2, 1, 0). Recorded because the alternative -- refusing it --
    would be a silent environment-specific refusal."""
    assert protocol_layer_refusal("2.1.0rc1") is None


def test_an_absent_distribution_is_refused_with_the_remedy():
    reason = protocol_layer_refusal(None)

    assert reason is not None
    assert "[server]" in reason, reason


def test_a_too_old_distribution_is_refused_saying_what_it_found():
    """The failure this replaces said `allow_module_level` and never named
    mcp at all. The refusal has to carry both numbers or the reader is back
    to guessing which of the two is wrong."""
    reason = protocol_layer_refusal("1.28.0")

    assert reason is not None
    assert "1.28.0" in reason, reason
    assert MCP_MINIMUM in reason, reason


def test_the_refusal_is_a_usage_error_not_a_skip():
    """A skip at module level is what produced the misleading report: pytest
    turns it into a collection error and explains its own API instead of the
    dependency. `UsageError` is reported as a plain message with no
    traceback, which is what this is."""
    with pytest.raises(pytest.UsageError) as caught:
        refuse_unusable_protocol_layer(None)

    assert "[server]" in str(caught.value)


def test_a_usable_protocol_layer_is_not_refused():
    refuse_unusable_protocol_layer("2.1.1")


def test_a_refusal_stops_the_run_before_any_test_executes(tmp_path):
    """The end-to-end promise: not "the module is skipped" but "nothing ran".

    The inner test writes a file, so its absence is positive evidence that no
    test body executed -- rather than an exit code, which a collection error
    would also produce.
    """
    (tmp_path / "conftest.py").write_text(
        f"""
import sys

sys.path.insert(0, {str(REPO)!r})

from tests.conftest import refuse_unusable_protocol_layer


def pytest_configure(config):
    refuse_unusable_protocol_layer(None)
""",
        encoding="utf-8",
    )
    (tmp_path / "test_inner.py").write_text(
        """
def test_inner():
    with open("ran.txt", "w") as handle:
        handle.write("yes")
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )

    assert not (tmp_path / "ran.txt").exists(), result.stdout
    assert result.returncode != 0
    assert "[server]" in result.stdout + result.stderr, result.stdout
