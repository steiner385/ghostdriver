"""The contract every tool honours, checked by enumeration rather than by hand.

The audit found tool coverage uneven: `describe` exercised in seven files,
`find` in one, and the gate tests listing tools by hand -- so a new tool
could ship without its refusal paths ever being asked for. These tests
derive the tool list from the Toolbox itself. A tool added tomorrow is in
every parametrisation the moment it exists, and a tool whose required
arguments this file cannot guess fails loudly (KeyError on PLACEHOLDER)
rather than being skipped.

Three promises, each over every tool:

- an unknown or released session is refused before anything else happens;
- a session opened at a lower tier cannot call a higher tier's tool;
- the tool surface and the policy's tier table name the same tools, so a
  tool cannot exist that no tier permits, or be permitted that does not
  exist.
"""

import inspect

import pytest

from ghostdriver.model.result import ErrorKind
from ghostdriver.policy import TIER_TOOLS, ConsentSource, Tier, tools_for
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox
from tests.conftest import on_windows

#: A value for every required parameter any session tool has. Extending
#: this table is the whole cost of adding a required parameter to a tool.
PLACEHOLDER = {
    "locator": "class=X",
    "text": "x",
    "keys": "a",
    "ask": "please",
}


def _session_tools() -> dict[str, object]:
    """Public Toolbox methods whose first argument is a session id."""
    found = {}
    for name, fn in inspect.getmembers(Toolbox, inspect.isfunction):
        if name.startswith("_"):
            continue
        params = list(inspect.signature(fn).parameters)[1:]
        if params and params[0] == "session_id":
            found[name] = fn
    return found


def _minimal_args(fn) -> dict:
    args = {}
    for p in list(inspect.signature(fn).parameters.values())[1:]:
        if p.name == "session_id" or p.default is not p.empty:
            continue
        args[p.name] = PLACEHOLDER[p.name]
    return args


SESSION_TOOLS = _session_tools()
ABOVE_READ_ONLY = sorted(n for n in SESSION_TOOLS if n not in tools_for(Tier.READ_ONLY))
FULL_ONLY = sorted(n for n in SESSION_TOOLS if n in TIER_TOOLS[Tier.FULL])


@pytest.fixture
def box():
    return Toolbox(SessionManager())


def _attached(box, pid, tier):
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    result = box.attach(pid, tier=tier)
    assert result["ok"], result
    return result["session_id"]


# --- the session gate ----------------------------------------------------

def test_the_enumeration_found_the_tools():
    """If this ever shrinks, the tests below are proving less than they say."""
    assert len(SESSION_TOOLS) >= 18
    assert "click" in SESSION_TOOLS and "describe" in SESSION_TOOLS


@pytest.mark.parametrize("name", sorted(n for n in SESSION_TOOLS if n != "release"))
def test_every_session_tool_refuses_an_unknown_session(box, name):
    fn = SESSION_TOOLS[name]
    result = fn(box, "nope", **_minimal_args(fn))

    assert result["ok"] is False
    assert result["error"]["kind"] == ErrorKind.NOT_FOUND.value


def test_release_is_the_one_exception_and_is_idempotent(box):
    """Releasing a session that is not open is not an error: a caller
    tidying up after a failure should not have to track whether it got far
    enough to open one. The exemption above exists for this reason only."""
    result = box.release("nope")

    assert result["ok"] is True


@on_windows
@pytest.mark.parametrize("name", sorted(n for n in SESSION_TOOLS if n != "release"))
def test_every_session_tool_refuses_a_released_session(box, win32_target, name):
    session = _attached(box, win32_target, "full")
    box.release(session)

    fn = SESSION_TOOLS[name]
    result = fn(box, session, **_minimal_args(fn))

    assert result["ok"] is False
    assert result["error"]["kind"] == ErrorKind.NOT_FOUND.value


# --- the tier gate -------------------------------------------------------

@on_windows
@pytest.mark.parametrize("name", ABOVE_READ_ONLY)
def test_every_tool_above_read_only_is_refused_by_a_read_only_session(
        box, win32_target, name):
    """The tier is the promise the session was opened under. Checked before
    the locator is even looked at, so a placeholder locator is enough."""
    session = _attached(box, win32_target, "read_only")

    fn = SESSION_TOOLS[name]
    result = fn(box, session, **_minimal_args(fn))

    assert result["ok"] is False
    assert result["error"]["kind"] == ErrorKind.DENIED_BY_POLICY.value


@on_windows
@pytest.mark.parametrize("name", FULL_ONLY)
def test_every_full_tier_tool_is_refused_by_an_interactive_session(
        box, win32_target, name):
    session = _attached(box, win32_target, "interactive")

    fn = SESSION_TOOLS[name]
    result = fn(box, session, **_minimal_args(fn))

    assert result["ok"] is False
    assert result["error"]["kind"] == ErrorKind.DENIED_BY_POLICY.value


# --- the surface and the table agree -------------------------------------

def test_the_tool_surface_and_the_tier_table_name_the_same_tools():
    """A tool no tier permits can never run; a tier naming a tool that does
    not exist is a promise about nothing. Both are drift, and both fail here."""
    surface = {
        name for name, fn in inspect.getmembers(Toolbox, inspect.isfunction)
        if not name.startswith("_")
    }
    named = set(tools_for(Tier.FULL))

    # grant_launch is the protocol layer's own: consent bookkeeping over the
    # session manager, with no Toolbox method behind it.
    assert named - surface == {"grant_launch"}
    assert surface - named == set(), "tools no tier permits"
