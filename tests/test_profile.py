import json

from ghostdriver.model.window import WindowNode
from ghostdriver.probe.profile import ProfileDocument, class_census, match_profile


def node(handle, class_name, children=()):
    return WindowNode(
        handle=handle, class_name=class_name, text="", rect=(0, 0, 1, 1),
        visible=True, enabled=True, pid=1, children=tuple(children),
    )


def test_class_census_counts_every_class():
    tree = node(1, "Root", [node(2, "Btn"), node(3, "Btn"), node(4, "Edit")])
    assert class_census(tree) == {"Root": 1, "Btn": 2, "Edit": 1}


def test_class_census_is_sorted_by_descending_count():
    tree = node(1, "Root", [node(2, "Btn"), node(3, "Btn")])
    assert list(class_census(tree))[0] == "Btn"


def test_matches_l1_when_uia_unusable_and_windows_are_plentiful():
    assert match_profile(
        uia_verdict="unusable", msaa_verdict="identification-only",
        window_count=1100, toolkit="delphi-vcl",
    ) == "L1"


def test_matches_m1_when_uia_is_rich():
    assert match_profile(
        uia_verdict="rich", msaa_verdict="actionable",
        window_count=200, toolkit="dotnet",
    ) == "M1"


def test_matches_o1_when_there_are_no_per_control_windows():
    assert match_profile(
        uia_verdict="unusable", msaa_verdict="unusable",
        window_count=3, toolkit="unknown",
    ) == "O1"


def test_profile_roundtrips_through_json(tmp_path):
    doc = ProfileDocument(
        profile_id="abc", matched_profile="L1",
        executable={"path": "x.exe", "bitness": "x86"},
        toolkit={"inferred": "delphi-vcl", "confidence": "high"},
    )
    path = tmp_path / "profile.json"
    doc.save(path)
    assert ProfileDocument.load(path).matched_profile == "L1"
    assert json.loads(path.read_text())["matched_profile"] == "L1"


def test_profile_roundtrips_unresponsive_count(tmp_path):
    """unresponsive_count must survive a save/load cycle like every other field."""
    doc = ProfileDocument(
        profile_id="abc", matched_profile="L1", window_count=10,
        unresponsive_count=3,
    )
    path = tmp_path / "profile.json"
    doc.save(path)
    loaded = ProfileDocument.load(path)
    assert loaded.unresponsive_count == 3
    assert json.loads(path.read_text())["unresponsive_count"] == 3


def test_phase1_fields_that_require_actuation_are_empty_not_absent():
    """Phase 1 cannot learn these read-only, so they ship empty.

    Absent keys would make a phase-1 profile indistinguishable from a
    truncated one; empty values say "not yet learned" explicitly.
    """
    doc = ProfileDocument(profile_id="x", matched_profile="L1")
    data = doc.to_dict()
    assert data["actuation_map"] == {}
    assert data["grid_strategy"] == "unknown"
    assert data["denylist"] == []
    assert data["environment_allowlist"] == []
    assert data["unresponsive_count"] == 0
