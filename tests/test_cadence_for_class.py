"""A cadence declared per control class (#238). Backend-free: the class name
is passed in, so no window is read."""

import json
from types import SimpleNamespace

import pytest

from ghostdriver.cadence import FAST_HUMAN, ROBOT
from ghostdriver.model.result import GhostdriverError
from ghostdriver.sensitivity import Note, Sensitivity, Source
from ghostdriver.session import Profile
from ghostdriver.tools.cadence_choice import choose_cadence


def session(**profile):
    return SimpleNamespace(profile=Profile(**profile))


def test_a_declared_class_cadence_applies_to_that_class_only():
    s = session(cadence_for_class={"TRichEditor*": "fast_human"})

    assert choose_cadence(s, 0, None, class_name="TRichEditorBox") is FAST_HUMAN
    assert choose_cadence(s, 0, None, class_name="TEdit") is ROBOT


def test_a_cadence_named_on_the_call_beats_the_class():
    s = session(cadence_for_class={"TRichEditor*": "fast_human"})
    assert choose_cadence(s, 0, "robot", class_name="TRichEditorBox") is ROBOT


def test_the_class_beats_a_blanket_surface_note():
    blanket = Sensitivity(notes=[Note(surface="*", cadence="robot", source=Source.DECLARED)])
    s = session(cadence_for_class={"TRichEditor*": "fast_human"}, sensitivity=blanket)
    assert choose_cadence(s, 0, None, class_name="TRichEditorBox") is FAST_HUMAN


def test_without_the_key_nothing_changes():
    assert choose_cadence(session(), 0, None, class_name="TRichEditorBox") is ROBOT


def test_the_key_is_read_and_a_bad_one_refused(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"cadence_for_class": {"TRich*": "fast_human"}}))
    assert Profile.load(path).class_cadence("TRichEdit") == "fast_human"

    for bad in ({"TRich*": "slow"}, ["TRich*"], {"": "robot"}):
        path.write_text(json.dumps({"cadence_for_class": bad}))
        with pytest.raises(GhostdriverError, match="cadence_for_class"):
            Profile.load(path)
