"""`posted_click_only` in a profile document (#122): parsed, checked, and
matched by window class. Backend-free; the fixture click that proves the
ladder honours it is in `tests/test_actuation_tools.py`.
"""

import json

import pytest

from ghostdriver.model.result import GhostdriverError
from ghostdriver.session import Profile


def test_the_key_is_read_as_class_patterns(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"posted_click_only": ["TsfCommandButton", "TsfSpeed*"]}))

    profile = Profile.load(path)

    assert profile.posted_click_only == ("TsfCommandButton", "TsfSpeed*")
    assert profile.pins_to_posted("TsfCommandButton") == "TsfCommandButton"
    assert profile.pins_to_posted("TsfSpeedButton") == "TsfSpeed*"
    assert profile.pins_to_posted("TEdit") is None
    assert profile.pins_to_posted(None) is None


def test_an_absent_key_pins_nothing(tmp_path):
    path = tmp_path / "p.json"
    path.write_text("{}")
    assert Profile.load(path).posted_click_only == ()
    assert Profile().pins_to_posted("TsfCommandButton") is None


@pytest.mark.parametrize("bad", ["TsfCommandButton", [1], [""], {"class": "x"}])
def test_anything_but_a_list_of_class_patterns_is_an_error_not_a_default(tmp_path, bad):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"posted_click_only": bad}))
    with pytest.raises(GhostdriverError, match="posted_click_only"):
        Profile.load(path)


# --- hover_before_click (#133) -----------------------------------------------------

def test_hover_before_click_names_the_classes_told_the_mouse_is_over_them(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"hover_before_click": ["THtLeftPanel", "THt*Bar"]}))

    profile = Profile.load(path)

    assert profile.hover_before_click == ("THtLeftPanel", "THt*Bar")
    assert profile.wants_hover("THtLeftPanel") and profile.wants_hover("THtTopBar")
    assert not profile.wants_hover("TsfCommandButton")
    assert not profile.wants_hover(None)


def test_no_hover_before_click_hovers_nothing():
    assert not Profile().wants_hover("THtLeftPanel")


@pytest.mark.parametrize("bad", ["THtLeftPanel", [1], [""]])
def test_a_bad_hover_before_click_is_an_error_not_a_default(tmp_path, bad):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"hover_before_click": bad}))
    with pytest.raises(GhostdriverError, match="hover_before_click"):
        Profile.load(path)


# --- notes (#137) --------------------------------------------------------------

def test_notes_are_matched_by_class_pattern(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"notes": {"THtLeftPanel": "use send_keys enter/escape on the edit box",
                                           "Tsf*Grid": "paints its own rows; capture it"}}))

    profile = Profile.load(path)

    assert profile.note_for("THtLeftPanel") == "use send_keys enter/escape on the edit box"
    assert profile.note_for("TsfDataGrid") == "paints its own rows; capture it"
    assert profile.note_for("TEdit") is None and profile.note_for(None) is None
    assert Profile().note_for("THtLeftPanel") is None


@pytest.mark.parametrize("bad", [["THtLeftPanel"], {"": "x"}, {"THtLeftPanel": 1}])
def test_bad_notes_are_an_error_not_a_default(tmp_path, bad):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"notes": bad}))
    with pytest.raises(GhostdriverError, match="notes"):
        Profile.load(path)
