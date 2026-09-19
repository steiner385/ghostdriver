"""The operator's standing declaration, and where it sits in the order (D#125).

Issue #125 asked one question: may an operator declare, per executable,
an approval that survives the target restarting -- at the cost of D65's
"that application, running" promise? The answer is yes, under two
constraints, and both are checked here rather than described:

1. **No tool writes the file.** That is the only thing separating a
   declaration the operator made from one the agent would like them to
   have made, and it is what R1 bought by eliciting in the first place.
2. **It answers last.** A declaration never overturns a decision anyone
   made about the running process, in either direction.

Platform-neutral by construction (D#39): the executable lookup is
injected, so nothing here starts a process or touches a backend. The
`_exe` names are written in POSIX form and compared through
`os.path.normcase`, which is the identity here and case-folding on
Windows -- so the same assertions hold on both.
"""

import json
import os

from ghostdriver.consent import STANDING_FILE, ConsentStore, StandingApprovals
from ghostdriver.policy import ConsentSource
from ghostdriver.session import SessionManager

CLIENT = os.path.join(os.sep, "opt", "vendorapp", "VendorApp")
OTHER = os.path.join(os.sep, "opt", "other", "Other")


def declaration(tmp_path, document) -> StandingApprovals:
    path = tmp_path / STANDING_FILE
    path.write_text(json.dumps(document), encoding="utf-8")
    return StandingApprovals.load(path, exe_of=lambda pid: {
        100: CLIENT, 200: OTHER}.get(pid))


def manager(standing: StandingApprovals, parent_of=lambda pid: None):
    """A manager with no consent store: the per-pid store is D65's and is
    not what these tests are about."""
    return SessionManager(parent_of=parent_of, store=ConsentStore(None),
                          standing=standing)


# --- what the declaration does -------------------------------------------

def test_a_declared_executable_is_approved_without_anyone_being_asked(tmp_path):
    """The whole point of #125: the target restarted, so no pid anyone
    approved still exists, and the work continues anyway."""
    grant = manager(declaration(tmp_path, {"allow": [CLIENT]})).grant_for(100)

    assert grant is not None and grant.allowed
    assert grant.source is ConsentSource.DECLARED
    assert grant.standing_for == CLIENT


def test_the_grant_says_nobody_was_asked(tmp_path):
    """The cost of D#125 is paid at the moment it is spent, so it is named
    there. A result that showed this as an ordinary approval would hide
    the one fact that distinguishes it."""
    grant = manager(declaration(tmp_path, {"allow": [CLIENT]})).grant_for(100)

    assert "standing declaration" in grant.describe()
    assert "nobody was asked" in grant.describe()


def test_an_undeclared_executable_is_still_asked_about(tmp_path):
    assert manager(declaration(tmp_path, {"allow": [CLIENT]})).grant_for(200) is None


def test_a_declaration_can_rule_a_target_out_for_good(tmp_path):
    grant = manager(declaration(tmp_path, {"restrict": [CLIENT]})).grant_for(100)

    assert grant is not None and grant.allowed is False


def test_an_executable_in_both_lists_is_restricted(tmp_path):
    """A declaration that contradicts itself is a mistake, and the safe
    reading of a mistake is the refusal."""
    grant = manager(declaration(
        tmp_path, {"allow": [CLIENT], "restrict": [CLIENT]})).grant_for(100)

    assert grant.allowed is False


def test_an_entry_may_carry_a_note(tmp_path):
    grant = manager(declaration(tmp_path, {"allow": [
        {"path": CLIENT, "note": "the line-of-business client"}]})).grant_for(100)

    assert grant.note == "the line-of-business client"


# --- the order, which is the decision ------------------------------------

def test_a_restriction_on_the_pid_beats_a_standing_approval(tmp_path):
    """"Leave that one alone", said a minute ago, is not overturned by a
    file edited last week. This is the direction that would be a safety
    defect, so it is the one worth stating first."""
    m = manager(declaration(tmp_path, {"allow": [CLIENT]}))
    m.record_grant(100, allowed=False, source=ConsentSource.OPERATOR_TOOL,
                   note="mid-shift, do not touch")

    grant = m.grant_for(100)
    assert grant.allowed is False
    assert grant.standing_for is None


def test_an_approval_on_the_pid_beats_a_standing_restriction(tmp_path):
    """The same rule the other way: the person is allowed to change their
    mind about the process in front of them without editing a file."""
    m = manager(declaration(tmp_path, {"restrict": [CLIENT]}))
    m.record_grant(100, allowed=True, source=ConsentSource.ELICITED)

    assert m.grant_for(100).allowed is True


def test_an_ancestors_decision_beats_a_standing_declaration(tmp_path):
    """A helper process of a restricted application is not rescued by its
    executable being declared: the nearer answer is about the application
    actually running."""
    m = manager(declaration(tmp_path, {"allow": [CLIENT]}),
                parent_of=lambda pid: 7 if pid == 100 else None)
    m.record_grant(7, allowed=False, source=ConsentSource.OPERATOR_TOOL)

    grant = m.grant_for(100)
    assert grant.allowed is False
    assert grant.inherited_from == 7


# --- the constraint that makes it worth anything -------------------------

def test_no_tool_writes_the_declaration(tmp_path):
    """`grant_targets` records an answer relayed by an agent; the
    declaration is the operator's own signature. If the first could
    produce the second, the second would be worth exactly as much as the
    first, and #125 would have bought nothing."""
    from ghostdriver.tools import Toolbox

    path = tmp_path / STANDING_FILE
    path.write_text(json.dumps({"allow": [CLIENT]}), encoding="utf-8")
    before = path.read_bytes()

    box = Toolbox(sessions=manager(StandingApprovals.load(path)))
    box.grant_targets(allow=[100, 200], restrict=[300], note="from chat")

    assert path.read_bytes() == before


def test_a_declared_decision_is_not_written_to_the_pid_store(tmp_path):
    """The store keeps what someone was asked (D65). Copying a declaration
    into it would outlive the declaration -- deleting a line from the file
    would leave the approval standing in a folder nobody thinks to look
    in."""
    folder = tmp_path / "consent"
    m = SessionManager(parent_of=lambda pid: None, store=ConsentStore(folder),
                       standing=declaration(tmp_path, {"allow": [CLIENT]}))

    assert m.grant_for(100).source is ConsentSource.DECLARED
    assert not folder.exists()


# --- reading the file ----------------------------------------------------

def test_no_file_means_no_standing_decisions(tmp_path):
    standing = StandingApprovals.load(tmp_path / STANDING_FILE,
                                      exe_of=lambda pid: CLIENT)

    assert standing.enabled is False
    assert standing.decide(100) is None
    assert standing.problem is None


def test_a_declaration_that_cannot_be_read_approves_nothing_and_says_so(tmp_path):
    """Fail closed, but not silently: an operator whose file has a typo
    would otherwise get the behaviour of having declared nothing and no
    way to tell that from having declared nothing."""
    path = tmp_path / STANDING_FILE
    path.write_text("{ not json", encoding="utf-8")

    standing = StandingApprovals.load(path, exe_of=lambda pid: CLIENT)
    assert standing.decide(100) is None
    assert standing.problem and "could not be read" in standing.problem


def test_the_problem_reaches_the_person_being_asked(tmp_path):
    """A `needs_consent` is the one moment the operator is reading, so it
    is where a declaration that is not in force has to be mentioned."""
    import pytest

    from ghostdriver.session import ConsentRequired

    path = tmp_path / STANDING_FILE
    path.write_text("[]", encoding="utf-8")
    m = manager(StandingApprovals.load(path, exe_of=lambda pid: CLIENT))

    with pytest.raises(ConsentRequired) as raised:
        m.attach(100, command_line=["VendorApp"])
    assert "could not be read" in raised.value.message


def test_a_process_whose_image_cannot_be_read_is_asked_about(tmp_path):
    """Not knowing what a target is, is not evidence it was declared."""
    path = tmp_path / STANDING_FILE
    path.write_text(json.dumps({"allow": [CLIENT]}), encoding="utf-8")

    standing = StandingApprovals.load(path, exe_of=lambda pid: None)
    assert standing.decide(100) is None


def test_withdrawing_a_declaration_takes_effect_without_a_restart(tmp_path):
    """A revocation that waits for a redeploy is one the operator will
    believe has taken effect when it has not."""
    path = tmp_path / STANDING_FILE
    path.write_text(json.dumps({"allow": [CLIENT]}), encoding="utf-8")
    standing = StandingApprovals.load(path, exe_of=lambda pid: CLIENT)
    assert standing.decide(100).allowed is True

    path.write_text(json.dumps({"allow": [OTHER]}), encoding="utf-8")
    assert standing.decide(100) is None


def test_creating_the_file_turns_the_feature_on_without_a_restart(tmp_path):
    """The server starts before the operator writes anything; "no file"
    has to be a state it can leave."""
    path = tmp_path / STANDING_FILE
    standing = StandingApprovals.load(path, exe_of=lambda pid: CLIENT)
    assert standing.decide(100) is None

    path.write_text(json.dumps({"allow": [CLIENT]}), encoding="utf-8")
    assert standing.decide(100).allowed is True


def test_an_entry_of_the_wrong_shape_invalidates_the_file(tmp_path):
    """Rather than being skipped. A list of four paths of which one is a
    number is a file the operator got wrong, and three quarters of a
    consent policy is not a consent policy."""
    path = tmp_path / STANDING_FILE
    path.write_text(json.dumps({"allow": [CLIENT, 17]}), encoding="utf-8")

    standing = StandingApprovals.load(path, exe_of=lambda pid: CLIENT)
    assert standing.decide(100) is None
    assert standing.problem is not None
