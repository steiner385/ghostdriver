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


def test_matches_m1_when_uia_is_rich():
    assert match_profile(
        uia_verdict="rich", msaa_verdict="actionable",
        window_count=200, toolkit="dotnet",
    ) == "M1"


def test_matches_o1_when_there_are_no_per_control_windows():
    """Few windows, no accessibility surface, but the toolkit is identified.

    The toolkit inference is the evidence that makes O1 a conclusion rather
    than a shrug: it says we know what we are looking at and it has no
    per-control windows. Without it -- see the companion assertion below --
    there is nothing to classify from, and the answer is "indeterminate".
    """
    assert match_profile(
        uia_verdict="unusable", msaa_verdict="unusable",
        window_count=3, toolkit="mfc",
    ) == "O1"
    assert match_profile(
        uia_verdict="unusable", msaa_verdict="unusable",
        window_count=3, toolkit="unknown",
    ) == "indeterminate"


def test_failed_uia_assessment_is_indeterminate_not_a_profile():
    """An assessment that did not conclude must not produce a confident label.

    "unavailable" means COM was missing, unwritable, or the target outranked
    us -- not that the target ships no provider. Returning L1 here would hand
    the operator exactly the answer the runbook told them to expect, built on
    no evidence at all.
    """
    for verdict in ("unavailable", "empty", "unknown"):
        assert match_profile(
            uia_verdict=verdict, msaa_verdict="unusable",
            window_count=1100, toolkit="delphi-vcl",
        ) == "indeterminate", f"{verdict} must not classify"


def test_unusable_uia_with_many_windows_is_l1():
    """A tree that genuinely reports no patterns, with a window per control."""
    assert match_profile(
        uia_verdict="unusable", msaa_verdict="identification-only",
        window_count=1100, toolkit="delphi-vcl",
    ) == "L1"


def test_msaa_actionable_rescues_a_small_window_count():
    """msaa_verdict must actually influence the result, not be decorative."""
    assert match_profile(
        uia_verdict="partial", msaa_verdict="actionable",
        window_count=5, toolkit="mfc",
    ) == "M1"


def test_profile_boundary_is_pinned_at_fifty():
    """Pin the threshold so a regression anywhere in 4..1099 cannot hide."""
    common = dict(uia_verdict="unusable", msaa_verdict="unusable", toolkit="mfc")
    assert match_profile(window_count=50, **common) == "L1"
    assert match_profile(window_count=49, **common) == "O1"


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
