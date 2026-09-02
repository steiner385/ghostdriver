"""The tool surface, exercised the way a protocol client would call it.

Kept separate from the MCP binding on purpose: everything that can be wrong
here -- a tier not enforced, a result that blows a context budget, an error
that says nothing useful -- is wrong in these functions, and is testable
without a protocol client.
"""

import base64
import json

import pytest

from ghostdriver.model.result import ErrorKind
from ghostdriver.policy import ConsentSource
from ghostdriver.session import SessionManager
from ghostdriver.tools import MAX_ELEMENTS, Toolbox
from tests.conftest import on_windows

pytestmark = on_windows

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def box():
    return Toolbox(sessions=SessionManager())


def attached(box, pid):
    """A session against a fixture target, with consent already recorded.

    Standing in for the operator having been asked and having said yes,
    which is what every real session does before any of this is reachable.
    """
    box.grant_targets(allow=[pid], note="test fixture")
    result = box.attach(pid)
    assert result["ok"], result
    return result["session_id"]


# --- consent -------------------------------------------------------------

def test_an_undecided_target_asks_rather_than_failing(box, win32_target):
    """Nothing is automatable until someone says so -- and "nobody has been
    asked yet" is a question, not a refusal."""
    result = box.attach(win32_target)

    assert result["ok"] is False
    assert result["needs_consent"] is True
    assert result["target"]["pid"] == win32_target
    assert "summary" in result["target"], "enough to put the question"


def test_a_granted_target_attaches(box, win32_target):
    box.grant_targets(allow=[win32_target], note="approved in chat")
    result = box.attach(win32_target)

    assert result["ok"]
    assert result["tier"] == "read_only"
    assert result["consent"]["note"] == "approved in chat"


def test_a_restricted_target_is_refused_without_asking_again(box, win32_target):
    """"Leave that one alone" has to stick."""
    box.grant_targets(restrict=[win32_target], note="not for this task")
    result = box.attach(win32_target)

    assert result["ok"] is False
    assert not result.get("needs_consent"), "already decided; do not re-ask"
    assert "not for this task" in result["error"]["message"]


def test_the_target_list_shows_what_a_person_needs_to_decide(box, win32_target):
    """A pid and a process name are not enough to answer with."""
    listed = box.list_targets()
    mine = [t for t in listed["targets"] if t["pid"] == win32_target]

    assert listed["note"], "the caller is told consent is required"
    if mine:
        assert "summary" in mine[0]
        assert "endpoints" in mine[0]
        assert mine[0]["consent"] is None, "undecided until someone decides"


def test_granting_nothing_is_an_error_rather_than_a_silent_no_op(box):
    result = box.grant_targets()

    assert result["ok"] is False
    assert "allow" in result["error"]["message"]


def test_a_decision_can_be_revised(box, win32_target):
    box.grant_targets(restrict=[win32_target])
    assert box.attach(win32_target)["ok"] is False

    box.grant_targets(allow=[win32_target])
    assert box.attach(win32_target)["ok"] is True


def test_attach_reports_blocking_state_immediately(box, modal_target):
    """It changes what every later call means: a held target answers reads
    from a window nobody can act on."""
    pid, _, _ = modal_target
    box.grant_targets(allow=[pid])
    result = box.attach(pid)

    assert result["blocked"], "a modal dialog is up and attach says so"
    assert "Confirm Delete Record" in result["blocked"][0]


def test_attaching_to_a_dead_pid_says_so(box):
    box.grant_targets(allow=[999_999])
    result = box.attach(999_999)

    assert result["ok"] is False
    assert result["error"]["kind"] == ErrorKind.NOT_FOUND.value


def test_an_unknown_tier_is_refused_by_name(box, win32_target):
    box.grant_targets(allow=[win32_target])
    result = box.attach(win32_target, tier="root")

    assert result["ok"] is False
    assert "read_only" in result["error"]["message"]


# --- the gate ------------------------------------------------------------

@pytest.mark.parametrize("call", [
    lambda b: b.describe("nope"),
    lambda b: b.find("nope", "class=X"),
    lambda b: b.read("nope", "class=X"),
    lambda b: b.capture("nope"),
    lambda b: b.wait_for("nope", "class=X"),
    lambda b: b.surfaces("nope"),
    lambda b: b.modals("nope"),
    lambda b: b.restore("nope"),
    lambda b: b.probe("nope"),
])
def test_every_tool_refuses_an_unknown_session(box, call):
    """The gate is not optional on any of them."""
    result = call(box)

    assert result["ok"] is False
    assert result["error"]["kind"] == ErrorKind.NOT_FOUND.value


def test_a_released_session_stops_working(box, win32_target):
    session = attached(box, win32_target)
    assert box.describe(session)["ok"]

    box.release(session)

    assert box.describe(session)["ok"] is False


# --- discovery and reading ----------------------------------------------

def test_describe_returns_a_tree_and_suggested_locators(box, win32_target):
    session = attached(box, win32_target)
    result = box.describe(session)

    assert result["ok"]
    assert result["windows"], "at least the main window"
    assert "GhostdriverTestWindow" in result["windows"][0]["tree"]


def test_describe_says_which_windows_it_searched(box, win32_target):
    session = attached(box, win32_target)

    assert "main window only" in box.describe(session)["searched"]
    assert "every top-level" in box.describe(
        session, all_windows=True)["searched"]


def test_find_returns_elements_with_re_resolvable_locators(box, win32_target):
    """Handles are recycled, so a locator is the durable way back.

    Note the casing: the fixture registers its controls as "BUTTON", and
    Windows canonicalises that to "Button" when read back. Class matching is
    case-sensitive by design, so a locator has to use the name the system
    reports, not the one the application registered.
    """
    session = attached(box, win32_target)
    result = box.find(session, 'class=Button text="Expand All"')

    assert result["ok"] and result["match_count"] == 1
    element = result["elements"][0]
    assert element["class"] == "Button"
    assert element["locator"] == 'class=Button text="Expand All"'
    assert element["handle_ephemeral"].startswith("0x")


def test_find_hints_at_the_windows_it_did_not_search(box, win32_target):
    session = attached(box, win32_target)
    result = box.find(session, "class=NoSuchClass")

    assert result["match_count"] == 0
    assert "all_windows=true" in result["hint"]


def test_a_malformed_locator_explains_itself(box, win32_target):
    session = attached(box, win32_target)
    result = box.find(session, "clazz=Nope")

    assert result["ok"] is False
    assert "clazz" in result["error"]["message"]


def test_read_keeps_unanswered_apart_from_empty(box, win32_target):
    """None and "" are different facts. Collapsing them asserts a field is
    empty when it may be full."""
    session = attached(box, win32_target)
    result = box.read(session, "class=Edit")

    assert result["ok"]
    assert result["values"][0]["answered"] is True
    assert result["values"][0]["text"] == "", "answered, and genuinely empty"
    assert result["unanswered"] == 0


def test_read_reports_a_control_that_never_answered(box, silent_target):
    pid, _ = silent_target
    session = attached(box, pid)
    result = box.read(session, "class=GhostdriverSilentClass")

    assert result["unanswered"] == 1
    assert result["values"][0]["text"] is None
    assert result["values"][0]["answered"] is False


# --- capture -------------------------------------------------------------

def test_capture_returns_a_png(box, win32_target):
    session = attached(box, win32_target)
    result = box.capture(session)

    assert result["ok"], result.get("error")
    assert result["mime_type"] == "image/png"
    assert base64.b64decode(result["base64"])[:8] == PNG_MAGIC
    assert result["width"] > 0


def test_capture_of_an_ambiguous_locator_is_refused(box, win32_target):
    """Capturing "one of these three" would return an arbitrary one."""
    session = attached(box, win32_target)
    result = box.capture(session, locator="class=Button")

    assert result["ok"] is False
    assert result["error"]["kind"] == ErrorKind.AMBIGUOUS.value


def test_capture_of_a_single_element_crops_to_it(box, win32_target):
    session = attached(box, win32_target)
    result = box.capture(session, locator='class=Button text="Expand All"')

    assert result["ok"]
    assert 0 < result["width"] < 400, "the button, not the whole window"


# --- waiting -------------------------------------------------------------

def test_wait_for_returns_immediately_when_already_true(box, win32_target):
    session = attached(box, win32_target)
    result = box.wait_for(session, 'class=Button text="Expand All"',
                          timeout_s=5)

    assert result["ok"] and result["polls"] == 1


def test_wait_for_times_out_with_a_timeout_error(box, win32_target):
    session = attached(box, win32_target)
    result = box.wait_for(session, "class=NeverAppears", timeout_s=0.3)

    assert result["ok"] is False
    assert result["error"]["kind"] == ErrorKind.TIMEOUT.value


def test_an_unknown_condition_lists_the_ones_that_exist(box, win32_target):
    session = attached(box, win32_target)
    result = box.wait_for(session, "class=Button", condition="sideways")

    assert result["ok"] is False
    assert "present" in result["error"]["message"]


# --- surfaces, modals, restore ------------------------------------------

def test_surfaces_classifies_and_fingerprints(box, win32_target):
    session = attached(box, win32_target)
    result = box.surfaces(session)

    assert result["ok"]
    assert result["kinds"], "every region falls into some kind"
    assert len(result["shape_digest"]) == 16


def test_surfaces_reports_a_changed_shape(box, win32_target):
    session = attached(box, win32_target)

    assert box.surfaces(session, changed_from="0" * 16)["changed"] is True
    digest = box.surfaces(session)["shape_digest"]
    assert box.surfaces(session, changed_from=digest)["changed"] is False


def test_modals_names_the_dialog_holding_the_target(box, modal_target):
    pid, _, _ = modal_target
    session = attached(box, pid)
    result = box.modals(session)

    assert result["blocked"] is True
    assert result["dialogs"][0]["dialog"] == "Confirm Delete Record"


def test_modals_on_an_unblocked_target_says_so(box, win32_target):
    session = attached(box, win32_target)
    result = box.modals(session)

    assert result["blocked"] is False
    assert result["dialogs"] == []


def test_restore_brings_a_minimized_target_back(box, minimized_target):
    pid, _, form, _ = minimized_target
    session = attached(box, pid)
    result = box.restore(session)

    assert result["ok"]
    assert result["took_foreground"] is False
    handles = [w["handle_ephemeral"] for w in result["now_visible"]]
    assert f"0x{form:08X}" in handles


def test_restore_is_a_no_op_when_nothing_is_minimized(box, win32_target):
    session = attached(box, win32_target)
    result = box.restore(session)

    assert result["ok"], result.get("error")
    # Reported, not just asserted: this failed once in a full run and could
    # not be reproduced, and "assert [] == [...]" says nothing about which
    # window was found minimized or what state it was in.
    assert result["restored"] == [], result
    assert "nothing was minimized" in result["note"]


# --- the shape of every result ------------------------------------------

def test_every_result_is_json_serializable(box, win32_target):
    """These cross a protocol boundary. A dataclass or an enum that leaks
    into a result fails at the client, far from the code that made it."""
    session = attached(box, win32_target)
    for result in (
        box.list_targets(),
        box.describe(session),
        box.find(session, "class=Button"),
        box.read(session, "class=Edit"),
        box.capture(session),
        box.wait_for(session, "class=Button", timeout_s=1),
        box.surfaces(session),
        box.modals(session),
        box.restore(session),
        box.describe("unknown-session"),
    ):
        json.dumps(result)


def test_find_caps_what_it_returns_and_says_it_capped(box, win32_target):
    """A target with ~1,100 windows can answer almost any query with more
    than a caller can read."""
    session = attached(box, win32_target)
    result = box.find(session, "class=*")

    assert len(result["elements"]) <= MAX_ELEMENTS
    if result["match_count"] > MAX_ELEMENTS:
        assert "Narrow the locator" in result["truncated"]
