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
