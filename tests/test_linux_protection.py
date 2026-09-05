"""What a Linux read is allowed to disclose.

Windows never had to decide this: the OS refuses a cross-process `WM_GETTEXT`
on a password field, so the value is not available to leak, and `is_protected`
exists only to tell "protected" from "hung" (D37). AT-SPI does the opposite --
it hands the value over -- and measured across thirteen surfaces, a
`Gtk.Entry` told not to show its characters is identical to one that does.
Role, states, interfaces, attributes, description, actions, relations: no
difference at all except the content itself.

So the driver cannot detect the field it must protect, and the platform will
not protect it. What is left is to withhold by class rather than by
detection. These tests are that policy.
"""

import pytest

from tests.conftest import on_linux
from tests.test_linux_atspi import report  # noqa: F401  (module-scoped fixture)


def _protection():
    """Imported inside the tests -- `ghostdriver.backends.*` at module scope
    is what took the whole suite down on the wrong host once (D74)."""
    from ghostdriver.backends.linux import protection

    return protection


EDITABLE_ENTRY = ("text", frozenset({"EDITABLE", "FOCUSABLE", "SENSITIVE", "SHOWING"}))
PASSWORD_WIDGET = ("password text", frozenset({"EDITABLE", "FOCUSABLE", "SENSITIVE"}))
LABEL = ("label", frozenset({"SENSITIVE", "SHOWING", "VISIBLE"}))
TABLE = ("table", frozenset({"FOCUSABLE", "SENSITIVE", "SHOWING"}))


def test_the_dedicated_password_widget_is_never_disclosed():
    """The one case AT-SPI does identify. `password text` is a distinct role,
    so this is detection rather than policy."""
    p = _protection()
    assert p.classify(*PASSWORD_WIDGET) is p.Disclosure.PROTECTED


def test_an_editable_entry_is_withheld_because_it_might_be_one():
    """The case that has no signal. A plain entry and a hidden entry are
    indistinguishable, so the class is withheld rather than the field."""
    p = _protection()
    assert p.classify(*EDITABLE_ENTRY) is p.Disclosure.WITHHELD


@pytest.mark.parametrize("node", [LABEL, TABLE], ids=["label", "table"])
def test_everything_that_cannot_hold_a_typed_secret_reads_normally(node):
    """The blast radius, kept small deliberately. A password is typed into an
    editable entry; static text, tables and captions are not that, and
    withholding them would cost the reads `read` mostly exists for."""
    p = _protection()
    assert p.classify(*node) is p.Disclosure.ALLOWED


def test_a_withheld_field_can_be_disclosed_when_the_caller_asks():
    """Withheld is a default, not a wall. A caller that knows what it is doing
    can have the value; the point is that it says so, and the saying is what
    ends up in the trace instead of the secret."""
    p = _protection()
    verdict, value = p.read(*EDITABLE_ENTRY, read=lambda: "hunter2", disclose=True)
    assert verdict is p.Disclosure.WITHHELD and value == "hunter2"


def test_the_dedicated_widget_is_not_disclosed_even_when_asked():
    """The opt-in does not reach PROTECTED. Where the platform does tell us,
    the answer is no, the way Windows' answer is no."""
    p = _protection()
    verdict, value = p.read(*PASSWORD_WIDGET, read=lambda: "hunter3", disclose=True)
    assert verdict is p.Disclosure.PROTECTED and value is None


def test_a_withheld_read_does_not_call_the_reader_at_all():
    """Not disclosing is not enough: the value must never be fetched, or it
    lives in this process and reaches a traceback or a log by accident."""
    p = _protection()
    calls = []
    p.read(*EDITABLE_ENTRY, read=lambda: calls.append(1) or "hunter2", disclose=False)
    assert calls == [], "the value was fetched despite being withheld"


def test_withheld_is_distinct_from_empty_and_from_no_answer():
    """Three different facts, and collapsing any two of them misleads a caller:
    the field was not read, the field is empty, the field never replied."""
    p = _protection()
    verdict, value = p.read(*EDITABLE_ENTRY, read=lambda: "hunter2", disclose=False)
    assert verdict is p.Disclosure.WITHHELD
    assert value is None
    assert p.classify(*LABEL) is p.Disclosure.ALLOWED


def test_a_value_can_be_confirmed_without_being_disclosed():
    """What makes the default affordable. D29 has `set_value` check the display
    after writing; that needs a *comparison*, not a disclosure. The driver
    already knows what it typed, so it can confirm the field agrees without
    the value passing through a result, a trace (D62) or a model's context."""
    p = _protection()
    assert p.confirms(*EDITABLE_ENTRY, expected="hunter2", read=lambda: "hunter2") is True
    assert p.confirms(*EDITABLE_ENTRY, expected="hunter2", read=lambda: "other") is False


def test_confirming_reports_unknown_when_the_field_did_not_answer():
    """`None` from the reader is the deadline expiring (D#9), which is not the
    same as a mismatch."""
    p = _protection()
    assert p.confirms(*EDITABLE_ENTRY, expected="x", read=lambda: None) is None


def test_every_verdict_carries_a_reason_a_caller_can_act_on():
    p = _protection()
    for role, states in (PASSWORD_WIDGET, EDITABLE_ENTRY, LABEL):
        reason = p.reason(p.classify(role, states))
        assert reason and len(reason) > 30, (role, reason)
    assert "await_human" in p.reason(p.Disclosure.PROTECTED)


# --- the policy against the real thing ----------------------------------------

@on_linux
@pytest.mark.slow
@pytest.mark.parametrize("name,expected", [
    ("password widget", "PROTECTED"),
    ("password entry", "WITHHELD"),
    ("plain entry", "WITHHELD"),
    ("bound entry", "WITHHELD"),
    ("status", "ALLOWED"),
    ("results grid", "ALLOWED"),
])
def test_the_policy_against_the_real_accessible_tree(report, name, expected):  # noqa: F811
    """The classification run on roles and states read off a live AT-SPI tree,
    rather than on constants a test made up.

    Note `plain entry` is withheld alongside the password one. That is the
    finding, not a bug: nothing distinguishes them, so a policy that let the
    plain one through would let a hidden one through too.
    """
    p = _protection()
    node = report["by_name"][name]
    verdict = p.classify(node["role"], frozenset(node["states"]))
    assert verdict.name == expected, (
        f"{name}: role={node['role']!r} states={node['states']} -> {verdict.name}"
    )


@on_linux
@pytest.mark.slow
def test_the_real_password_entry_is_never_fetched(report):  # noqa: F811
    """The leak, closed. `tests/test_linux_reading.py` asserts that AT-SPI
    *will* hand over `hunter2`; this asserts that the driver does not ask."""
    p = _protection()
    node = report["by_name"]["password entry"]
    assert node["text"] == "hunter2", "the fixture's secret changed; update this test"

    fetched = []
    verdict, value = p.read(
        node["role"], frozenset(node["states"]),
        read=lambda: fetched.append(node["text"]) or node["text"],
    )
    assert verdict is p.Disclosure.WITHHELD
    assert value is None
    assert fetched == [], "the real password was fetched into this process"
