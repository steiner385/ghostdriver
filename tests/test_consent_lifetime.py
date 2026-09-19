"""The approval prompt states the lifetime it actually has (#62).

The field report behind #62 read as two bugs -- the approval happened in
chat rather than a dialog, and it did not survive a restart. #125's
re-measurement a week later showed the second was not a bug: D65's store
had held a grant for seven days; the run in #62 simply had no operator
directory. What is left, and what these check, is that the difference
was never *said*.

Two sentences asserted a lifetime the server does not always have:
`attach`'s elicitation prompt ("This lasts for this session only") and
the server instructions the agent plans from ("Approvals last for this
server run"). Both predate R1a. When a store is configured they are
wrong; when one is not, they fail to say why the person is being asked
again. The lifetime is knowable at the moment of asking, so it is
reported at the moment of asking.

Platform-neutral, and by construction rather than by luck (D#39). Most
of these take the `SessionManager` seam. The two that do go through the
`attach` tool aim it at this test process: an undecided pid is refused
after reading a command line and before anything is enumerated, so no
backend is reached on any platform.
"""

import pytest

from ghostdriver.consent import ConsentStore, StandingApprovals
from ghostdriver.operator import ENV_VAR
from ghostdriver.session import ConsentRequired, SessionManager


def manager(folder):
    return SessionManager(parent_of=lambda pid: None,
                          store=ConsentStore(folder),
                          standing=StandingApprovals(None))


def test_without_an_operator_directory_the_prompt_says_one_server_run(tmp_path):
    lifetime = manager(None).consent_lifetime()

    assert "this server run only" in lifetime
    assert ENV_VAR in lifetime, "and how to get the longer one"


def test_with_a_store_the_prompt_says_as_long_as_the_process_runs(tmp_path):
    lifetime = manager(tmp_path / "consent").consent_lifetime()

    assert "while that process keeps running" in lifetime
    assert "across restarts of this server" in lifetime


def test_the_longer_lifetime_still_ends_when_the_application_restarts(tmp_path):
    """R1a kept a decision for the life of the *process*. A person told
    only "it is kept" would reasonably read that as "it is remembered",
    which is the reading #125 had to go and correct in the field."""
    lifetime = manager(tmp_path / "consent").consent_lifetime()

    assert "if the application itself restarts, you are asked again" in lifetime


@pytest.mark.parametrize("folder", [None, "consent"])
def test_the_request_for_consent_carries_the_lifetime(tmp_path, folder):
    m = manager(tmp_path / folder if folder else None)

    with pytest.raises(ConsentRequired) as raised:
        m.attach(999_999, command_line=["something"])

    assert m.consent_lifetime() in raised.value.message


def test_the_attach_tool_carries_the_lifetime_out_to_the_caller():
    """The manager holding the sentence is no use if the tool drops it: an
    agent relaying the question in chat reads the *result*.

    Its target is this test process. `attach` on an undecided pid reads a
    command line and raises before it enumerates anything, so nothing here
    reaches a backend -- the same reason the refusals in
    `test_lifecycle_policy.py` run everywhere (D#39). A Windows copy with
    a real GUI target lives in `test_field_feedback.py`, where the field
    report it came from is written up.
    """
    import os

    from ghostdriver.tools import Toolbox

    sessions = manager(None)
    result = Toolbox(sessions).attach(os.getpid())

    assert result["needs_consent"]
    assert result["lifetime"] == sessions.consent_lifetime()
    assert sessions.consent_lifetime() in result["error"]["message"]


def test_the_target_names_the_image_a_declaration_would_have_to_match(tmp_path):
    """An operator declaring a standing approval (D#125) has to spell the
    path the way the process reports it, which is not always the one they
    would have guessed -- a virtualenv interpreter being the example
    nearest to hand. So the question that prompts them carries it.

    Checked by using it: the promise is not that `exe` equals any
    particular spelling, but that copying it into the file is enough.
    """
    import json
    import os

    from ghostdriver.consent import STANDING_FILE
    from ghostdriver.tools import Toolbox

    result = Toolbox(manager(None)).attach(os.getpid())
    declared = result["target"]["exe"]
    assert os.path.isabs(declared)

    path = tmp_path / STANDING_FILE
    path.write_text(json.dumps({"allow": [declared]}), encoding="utf-8")

    assert StandingApprovals.load(path).decide(os.getpid()).allowed


def test_the_server_instructions_do_not_assert_a_lifetime():
    """The agent plans from these and cannot see the configuration, so an
    instruction naming a lifetime is one that is wrong half the time. It
    is told to quote the result instead."""
    from ghostdriver.mcp_server import SERVER_INSTRUCTIONS

    assert "Approvals last for this server run" not in SERVER_INSTRUCTIONS
    assert "lifetime" in SERVER_INSTRUCTIONS
