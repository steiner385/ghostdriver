"""The macro CRUD tools (#86): save / list / show / delete, against a temp
operator directory. No desktop, no fixture -- these touch files, not a target
(`env: any`)."""

import json

import pytest

from ghostdriver.operator import ENV_VAR
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox


@pytest.fixture
def box(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "ops"))
    return Toolbox(SessionManager())


LEAF = {"tool": "click", "args": {"locator": "type=TabItem name=${plan}"},
        "expect": {"verified": "effect"}, "verified": True}
PAINTED = {"tool": "click", "args": {"locator": "class=Grid", "at": {"x": 5, "y": 9}},
           "delivery_only": True, "note": "painted row"}


def test_save_then_show_round_trips(box):
    saved = box.macro_save(
        "embed", [LEAF, PAINTED], description="embed illustrations", tier="interactive",
        params={"plan": {"required": True, "note": "the plan"}},
        provenance={"recorded_against": "ca4904", "revision": 2})

    assert saved["ok"] and saved["replaced"] is False and saved["saved_to"].endswith("embed.json")

    shown = box.macro_show("embed")
    assert shown["ok"] and shown["name"] == "embed" and shown["tier"] == "interactive"
    assert shown["description"] == "embed illustrations"
    assert shown["params"] == [{"name": "plan", "required": True, "note": "the plan"}]
    assert shown["provenance"]["recorded_against"] == "ca4904"
    assert shown["provenance"]["revision"] == 2
    assert [s["tool"] for s in shown["steps"]] == ["click", "click"]
    assert shown["steps"][0]["verified"] is True and shown["steps"][0]["delivery_only"] is False
    assert shown["steps"][1]["delivery_only"] is True and shown["steps"][1]["verified"] is False


def test_a_when_branch_macro_saves_and_shows_its_shape(box):
    body = [{"when": {"locator": "class=Funnel", "pressed": True},
             "then": [{"tool": "click", "args": {"locator": "once"}}],
             "else": [{"tool": "click", "args": {"locator": "twice"}}]}]
    assert box.macro_save("toggle", body)["ok"]

    shown = box.macro_show("toggle")
    branch = shown["steps"][0]
    assert branch["when"] == "class=Funnel"
    assert [s["tool"] for s in branch["then"]] == ["click"]
    assert [s["tool"] for s in branch["else"]] == ["click"]


def test_a_malformed_macro_is_refused_at_save(box):
    result = box.macro_save("bad", [{"tool": "click", "typo": 1}])

    assert not result["ok"] and "malformed" in result["error"]["message"]
    assert box.macro_list()["total"] == 0, "nothing was written"


def test_saving_over_a_name_reports_that_it_replaced(box):
    box.macro_save("m", [{"tool": "click", "args": {"locator": "a"}}])
    again = box.macro_save("m", [{"tool": "click", "args": {"locator": "b"}}])

    assert again["ok"] and again["replaced"] is True


def test_list_shows_each_macro_with_its_shape(box):
    box.macro_save("one", [{"tool": "click", "args": {"locator": "a"}}],
                   description="the first", params={"p": {"required": True}})
    box.macro_save("two", [{"tool": "find", "args": {"locator": "b"}},
                           {"tool": "click", "args": {"locator": "c"}}])

    listed = box.macro_list()
    by_name = {m["name"]: m for m in listed["macros"]}
    assert listed["total"] == 2
    assert by_name["one"]["description"] == "the first" and by_name["one"]["params"] == ["p"]
    assert by_name["two"]["steps"] == 2


def test_delete_archives_and_is_recoverable(box, tmp_path):
    box.macro_save("gone", [{"tool": "click", "args": {"locator": "a"}}])

    result = box.macro_delete("gone")

    assert result["ok"] and "archived" in result["note"]
    assert box.macro_list()["total"] == 0, "it left the listing"
    archived = tmp_path / "ops" / "workflows" / ".archive"
    kept = list(archived.glob("gone-*.json"))
    assert len(kept) == 1, "it is recoverable in the archive"
    assert json.loads(kept[0].read_text(encoding="utf-8"))["name"] == "gone"


def test_show_and_delete_name_the_missing_macro(box):
    assert box.macro_show("nope")["error"]["kind"] == "not_found"
    assert box.macro_delete("nope")["error"]["kind"] == "not_found"


def test_without_an_operator_directory_every_verb_says_so(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    box = Toolbox(SessionManager())

    for result in (box.macro_list(),
                   box.macro_show("x"),
                   box.macro_delete("x"),
                   box.macro_save("x", [{"tool": "click", "args": {"locator": "a"}}])):
        assert not result["ok"]
        assert ENV_VAR in result["error"]["message"]
