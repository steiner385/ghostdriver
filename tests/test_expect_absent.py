"""`expect: {locator, absent: true}` -- "it is gone" as a postcondition (#118).

Backend-free: the absence condition is the resolver and nothing else, so it
is proven here through `_ExpectCore._expectation` with the resolver stood in
for, on any platform. The parse rules ride alongside.
"""

import pytest

from ghostdriver.operator import ENV_VAR
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox
from ghostdriver.tools.expect import EXPECT_KEYS, parse_expect, verify_window


@pytest.fixture
def box(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "ops"))
    return Toolbox(SessionManager())


# --- the vocabulary --------------------------------------------------------

def test_absent_is_an_expect_key():
    assert "absent" in EXPECT_KEYS
    assert parse_expect({"locator": "class=TUDVDialog", "absent": True}) == {
        "locator": "class=TUDVDialog", "absent": True}


def test_absent_needs_a_locator_and_nothing_about_it():
    with pytest.raises(ValueError, match="takes a `locator`"):
        parse_expect({"locator": "class=X", "absent": True, "text": "Save"})
    with pytest.raises(ValueError, match="takes a `locator`"):
        parse_expect({"locator": "class=X", "absent": True, "selected": True})
    with pytest.raises(ValueError, match="takes a `locator`"):
        parse_expect({"changed": True, "absent": True})


def test_absent_false_is_an_ordinary_presence_expect():
    parsed = parse_expect({"locator": "class=X", "absent": False, "text": "Save"})
    assert parsed["text"] == "Save"


# --- timeout_s widens the verify window for any expect, not just changed (#73) ----

def test_verify_window_reads_timeout_s_from_any_expect():
    assert verify_window(None) is None
    assert verify_window("class=TPanel") is None, "a bare locator: the default window"
    assert verify_window({"locator": "class=TPanel"}) is None
    assert verify_window({"locator": "class=TPanel", "timeout_s": 10}) == 10.0
    assert verify_window({"changed": True}) == 6.0, "a surface docks slowly"
    assert verify_window({"changed": True, "timeout_s": 3}) == 3.0
    assert verify_window({"nonsense": 1}) is None, "malformed: _expectation reports it"


# --- the condition ----------------------------------------------------------

class Resolver:
    """Stands in for `_resolve`: `present` is what resolves right now."""

    def __init__(self, present: bool):
        self.present = present
        self.scopes: list[bool] = []

    def __call__(self, session, where, all_windows):
        self.scopes.append(all_windows)
        return [object()] if self.present else []


def test_an_absent_expect_holds_once_the_locator_stops_resolving(box, monkeypatch):
    resolver = Resolver(present=True)
    monkeypatch.setattr(box, "_resolve", resolver)

    condition, described = box._expectation(
        None, {"locator": "class=TUDVDialog", "absent": True, "all_windows": True})

    assert described == "class=TUDVDialog is gone"
    assert condition.holds() is False, "still there"
    resolver.present = False
    assert condition.holds() is True, "gone"
    assert resolver.scopes and all(resolver.scopes), "the expect's window scope is used"


def test_an_absent_expect_searches_every_window_unless_told_not_to(box, monkeypatch):
    """A dialog is a window of its own, and "gone" means gone everywhere
    (#250): the wider scope is the default, the narrower one is asked for."""
    resolver = Resolver(present=True)
    monkeypatch.setattr(box, "_resolve", resolver)

    condition, _ = box._expectation(None, {"locator": "class=#32770", "absent": True})
    condition.holds()
    assert resolver.scopes and all(resolver.scopes), "every window, unasked"

    resolver.scopes.clear()
    condition, _ = box._expectation(
        None, {"locator": "class=#32770", "absent": True, "all_windows": False})
    condition.holds()
    assert resolver.scopes and not any(resolver.scopes), "the main window, when asked"


def test_an_absent_expect_on_something_not_there_is_refused_not_satisfied(box, monkeypatch):
    """A postcondition that cannot fail is a false green (D#71): the locator
    must resolve *before* the action for its absence afterwards to mean it."""
    monkeypatch.setattr(box, "_resolve", Resolver(present=False))

    with pytest.raises(ValueError, match="does not resolve before the action"):
        box._expectation(None, {"locator": "class=TUDVDialog", "absent": True})


def test_a_bad_locator_in_an_absent_expect_is_an_error_not_a_condition(box, monkeypatch):
    monkeypatch.setattr(box, "_resolve", Resolver(present=True))
    with pytest.raises(ValueError):
        box._expectation(None, {"locator": "=== not a locator", "absent": True})
