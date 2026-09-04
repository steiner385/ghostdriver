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


def test_a_retired_key_is_warned_about(tmp_path, capsys):
    path = write(tmp_path, {"denylist": [], "environment_allowlist": ["http://x/*"],
                            "colour": "blue"})

    code = main(["check-profile", str(path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "environment_allowlist" in out and "no longer read" in out
    assert "colour" in out and "unknown key" in out


def test_a_missing_file_is_an_error(tmp_path, capsys):
    code = main(["check-profile", str(tmp_path / "nope.json")])

    assert code == 2
    assert "could not be read" in capsys.readouterr().err
