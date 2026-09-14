"""A presence `expect` that already holds before the action is refused (#128),
the mirror of the absent guard (D#118). Backend-free: the resolver is stood
in for. The locators carry `index=0` so the D#60 foreground corroboration
(class-only locators) is not consulted -- that path reads the real
foreground through a session, which is the fixture tests' job.
"""

import pytest

from ghostdriver.operator import ENV_VAR
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox


@pytest.fixture
def box(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "ops"))
    return Toolbox(SessionManager())


class Resolver:
    def __init__(self, present: bool):
        self.present = present

    def __call__(self, session, where, all_windows):
        return [object()] if self.present else []


def test_a_locator_that_already_resolves_is_refused_not_verified(box, monkeypatch):
    """The field case: a click that did nothing reported verified: effect
    against the bottom tab strip, which was there before the click."""
    monkeypatch.setattr(box, "_resolve", Resolver(present=True))

    with pytest.raises(ValueError, match="already, before the action"):
        box._expectation(None, {"locator": "class=TsfDataPagesNoteBook index=0"})


def test_the_refusal_says_what_to_use_instead(box, monkeypatch):
    monkeypatch.setattr(box, "_resolve", Resolver(present=True))
    with pytest.raises(ValueError) as caught:
        box._expectation(None, "class=TsfDataPagesNoteBook index=0")
    message = str(caught.value)
    assert "absent: true" in message and "changed: true" in message


def test_a_locator_that_does_not_resolve_yet_is_the_postcondition(box, monkeypatch):
    resolver = Resolver(present=False)
    monkeypatch.setattr(box, "_resolve", resolver)

    condition, described = box._expectation(None, {"locator": "class=TPalette index=0"})

    assert described == "class=TPalette index=0 exists"
    assert condition.holds() is False
    resolver.present = True
    assert condition.holds() is True
