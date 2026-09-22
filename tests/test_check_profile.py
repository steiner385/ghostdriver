"""`ghostdriver check-profile`: read a profile back and say what the tool
will make of it, so an operator writing regions and a busy indicator by
hand learns of a mistake before a session does."""

import json

from ghostdriver.cli import main


def write(tmp_path, document):
    path = tmp_path / "sandbox.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_a_good_profile_is_summarised(tmp_path, capsys):
    path = write(tmp_path, {
        "matched_profile": "L1",
        "denylist": ["*delete*", "TabItem:Change Log",
                     {"within": "class=Grid", "region": {"left": 0, "top": 24,
                                                          "right": 600, "bottom": 44},
                      "note": "the release row"}],
        "input_sensitivity": [{"cadence": "robot", "source": "declared", "surface": "*"}],
        "busy_indicator": {"region": {"left": 0, "top": 0, "right": 10, "bottom": 10},
                           "ink_above": 0.05},
        "safe_controls": [{"locator": "class=Button", "expect": {"locator": "class=Panel"}}],
    })

    code = main(["check-profile", str(path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "denylist        : 2 name(s), 1 place(s)" in out
    assert "the release row" in out
    assert "busy_indicator  : region" in out
    assert "safe_controls   : 1" in out


def test_a_malformed_place_is_an_error_with_the_reason(tmp_path, capsys):
    path = write(tmp_path, {"denylist": [{"within": "class=Grid", "region": {"left": 0}}]})

    code = main(["check-profile", str(path)])

    assert code == 2
    assert "unreadable denylist entry" in capsys.readouterr().err


def test_retired_evidence_and_unknown_keys_are_told_apart(tmp_path, capsys):
    path = write(tmp_path, {"denylist": [], "environment_allowlist": ["http://x/*"],
                            "class_census": {"TPanel": 9}, "colour": "blue"})

    code = main(["check-profile", str(path)])

    out = capsys.readouterr().out
    assert code == 0
    # retired names its reason; evidence is one informational line; only a
    # genuinely unknown key is flagged as a possible typo.
    assert "environment_allowlist" in out and "no longer read" in out
    assert "probe evidence  : 1 key(s)" in out
    warnings = [ln for ln in out.splitlines() if ln.startswith("warning:")]
    assert not any("class_census" in ln for ln in warnings)
    assert any("colour" in ln and "typo" in ln for ln in warnings)


def test_a_missing_file_is_an_error(tmp_path, capsys):
    code = main(["check-profile", str(tmp_path / "nope.json")])

    assert code == 2
    assert "could not be read" in capsys.readouterr().err


def test_the_class_hints_are_summarised(tmp_path, capsys):
    """A profile's author sees the tool read what they declared."""
    import json

    from ghostdriver.cli import cmd_check_profile

    path = tmp_path / "hints.json"
    path.write_text(json.dumps({
        "posted_click_only": ["TsfCommandButton"], "insert_first": ["TsfDBInputEdit"],
        "menus_by_keyboard": True, "notes": {"THtLeftPanel": "use the keys"}}))

    assert cmd_check_profile(str(path)) == 0
    out = capsys.readouterr().out
    assert "posted_only     : TsfCommandButton" in out
    assert "insert_first    : TsfDBInputEdit" in out
    assert "menus           : chosen by the menu's keyboard route first" in out
    assert "notes           : 1 class(es): THtLeftPanel" in out
    assert "wait_idle waits for the surface" in out
