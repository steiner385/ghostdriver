import json

from ghostdriver.model.window import WindowNode
from ghostdriver.probe.profile import (
    ProfileDocument,
    class_census,
    match_profile,
)


def profile_of(**kwargs) -> str:
    """The verdict alone.

    match_profile returns (profile, reason): the reason is there so a
    reader can disagree with which rung of the ladder answered. These
    tests are about the verdict, so they read it through here.
    """
    profile, reason = match_profile(**kwargs)
    assert reason, f"{profile} was returned with no reason"
    return profile


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
    assert next(iter(class_census(tree))) == "Btn"


def test_matches_m1_when_uia_is_rich():
    assert profile_of(
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
    assert profile_of(
        uia_verdict="unusable", msaa_verdict="unusable",
        window_count=3, toolkit="mfc",
    ) == "O1"
    assert profile_of(
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
        assert profile_of(
            uia_verdict=verdict, msaa_verdict="unusable",
            window_count=1100, toolkit="delphi-vcl",
        ) == "indeterminate", f"{verdict} must not classify"


def test_unusable_uia_with_many_windows_is_l1():
    """A tree that genuinely reports no patterns, with a window per control."""
    assert profile_of(
        uia_verdict="unusable", msaa_verdict="identification-only",
        window_count=1100, toolkit="delphi-vcl",
    ) == "L1"


def test_msaa_actionable_rescues_a_small_window_count():
    """msaa_verdict must actually influence the result, not be decorative."""
    assert profile_of(
        uia_verdict="partial", msaa_verdict="actionable",
        window_count=5, toolkit="mfc",
    ) == "M1"


def test_profile_boundary_is_pinned_at_fifty():
    """Pin the threshold so a regression anywhere in 4..1099 cannot hide."""
    common = dict(uia_verdict="unusable", msaa_verdict="unusable", toolkit="mfc")
    assert profile_of(window_count=50, **common) == "L1"
    assert profile_of(window_count=49, **common) == "O1"


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


# --- the gap the ad-hoc sweep found -------------------------------------

def test_a_partial_uia_tree_is_not_reported_as_unknown():
    """"We have evidence but no rule matched" is not "we could not tell".

    Found by sweeping ten live applications: a chat client with a working
    provider exposing 43 elements at depth 11 came back as
    `indeterminate`, which told an operator nothing was known about a
    target that was plainly drivable. `indeterminate` is reserved for an
    assessment that did not conclude.
    """
    assert profile_of(
        uia_verdict="partial", msaa_verdict="identification-only",
        window_count=25, toolkit="unknown",
    ) == "M1"


def test_an_embedded_web_view_without_a_rich_tree_is_w1():
    """W1 is in the spec and the classifier never returned it.

    A Chromium-family view inside a native shell, with renderer
    accessibility not exposing a usable tree, needs a browser driver rather
    than native-window techniques -- which is exactly what W1 says.
    """
    assert profile_of(
        uia_verdict="partial", msaa_verdict="identification-only",
        window_count=25, toolkit="unknown", hosts_web_content=True,
    ) == "W1"


def test_a_web_app_whose_renderer_accessibility_is_on_is_m1():
    """The spec puts "Chromium with renderer accessibility enabled" under
    M1: the tree is there, so drive it rather than reaching for a separate
    driver."""
    assert profile_of(
        uia_verdict="rich", msaa_verdict="identification-only",
        window_count=3, toolkit="unknown", hosts_web_content=True,
    ) == "M1"


def test_web_content_does_not_override_an_unconcluded_assessment():
    """An assessment that never ran cannot be evidence for anything."""
    assert profile_of(
        uia_verdict="unavailable", msaa_verdict="unusable",
        window_count=3, toolkit="unknown", hosts_web_content=True,
    ) == "indeterminate"


def test_indeterminate_still_means_the_assessment_did_not_conclude():
    for verdict in ("unavailable", "empty", "unknown"):
        assert profile_of(
            uia_verdict=verdict, msaa_verdict="unusable",
            window_count=900, toolkit="mfc",
        ) == "indeterminate"


def test_every_verdict_carries_a_reason_naming_its_evidence():
    """The reason is what lets a reader disagree with the classification
    rather than only with the outcome."""
    profile, reason = match_profile(
        uia_verdict="unusable", msaa_verdict="unusable",
        window_count=900, toolkit="mfc",
    )
    assert profile == "L1"
    assert "900 windows" in reason


def test_a_document_records_why_it_classified_as_it_did():
    document = ProfileDocument(
        profile_id="x", matched_profile="W1",
        classification_reason="hosts an embedded web view",
        blocked_by=["'Tip of the Day' is holding 'ProjectLibre'"],
    )
    emitted = document.to_dict()

    assert emitted["classification_reason"] == "hosts an embedded web view"
    assert emitted["blocked_by"] == [
        "'Tip of the Day' is holding 'ProjectLibre'"
    ]


# --- a re-probe must not take the curated policy with it -----------------

def curated(tmp_path, **extra):
    """A profile someone has edited, as they actually arrive."""
    import json

    document = {
        "_comment": ["Hand-written notes that this code has no field for."],
        "profile_id": "app-1.0-32",
        "matched_profile": "L1",
        "window_count": 12,
        "denylist": ["*delete*", "*submit*"],
        "environment_allowlist": ["https://staging.example.internal/*"],
        "input_sensitivity": [
            {"cadence": "fast_human", "source": "declared", "surface": "web",
             "evidence": "hosted content counts input events"},
        ],
        "grid_strategy": "capture-and-read",
        **extra,
    }
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def reprobe(profile_id="app-1.0-32", **extra):
    return ProfileDocument(profile_id=profile_id, matched_profile="L1",
                           window_count=57, **extra)


def test_a_reprobe_keeps_the_denylist(tmp_path):
    """The original known cost of D3, now paid off."""
    import json

    path = curated(tmp_path)
    reprobe().save(path)

    after = json.loads(path.read_text())
    assert after["denylist"] == ["*delete*", "*submit*"]
    assert after["environment_allowlist"] == [
        "https://staging.example.internal/*"
    ]


def test_a_reprobe_keeps_what_a_session_measured(tmp_path):
    """The reason this stopped being an acceptable cost.

    A denylist can be retyped from memory. An input-sensitivity note was
    *measured* -- and measuring it again means tripping the target at
    machine speed, which is the thing the note exists to prevent.
    """
    import json

    path = curated(tmp_path)
    reprobe().save(path)

    notes = json.loads(path.read_text())["input_sensitivity"]
    assert len(notes) == 1
    assert notes[0]["cadence"] == "fast_human"
    assert notes[0]["evidence"] == "hosted content counts input events"


def test_a_reprobe_keeps_keys_this_code_does_not_model(tmp_path):
    """These documents are hand-edited. An operator's comments are not ours
    to drop because we have no field for them."""
    import json

    path = curated(tmp_path, operator_note="ask Dana before changing this")
    reprobe().save(path)

    after = json.loads(path.read_text())
    assert after["_comment"] == [
        "Hand-written notes that this code has no field for."
    ]
    assert after["operator_note"] == "ask Dana before changing this"


def test_a_reprobe_does_replace_what_it_measured(tmp_path):
    """The other half: preserving everything would make re-probing
    pointless."""
    import json

    path = curated(tmp_path)
    reprobe().save(path)

    assert json.loads(path.read_text())["window_count"] == 57


def test_the_result_says_what_it_preserved(tmp_path):
    """So the person running it can see the curation survived, rather than
    opening the file to check."""
    outcome = reprobe().save(curated(tmp_path))

    assert outcome["merged"] is True
    assert "denylist" in outcome["preserved"]
    assert "input_sensitivity" in outcome["preserved"]
    assert "_comment" in outcome["preserved"]
    assert "window_count" not in outcome["preserved"], "that one was replaced"


def test_probing_over_a_different_application_is_refused(tmp_path):
    """The path is usually typed by hand, and silently rewriting one
    application's profile with another's is not recoverable."""
    import json

    import pytest as _pytest

    path = curated(tmp_path)

    with _pytest.raises(ValueError, match="describes"):
        reprobe(profile_id="other-app-2.0-64").save(path)

    assert json.loads(path.read_text())["profile_id"] == "app-1.0-32"


def test_it_can_be_forced_when_that_is_what_is_meant(tmp_path):
    import json

    path = curated(tmp_path)
    reprobe(profile_id="other-app-2.0-64").save(path, force=True)

    assert json.loads(path.read_text())["profile_id"] == "other-app-2.0-64"
    assert json.loads(path.read_text())["denylist"] == ["*delete*", "*submit*"]


def test_a_first_probe_writes_the_whole_template(tmp_path):
    """With no file there, the empty curated fields are the point: they show
    an operator what there is to fill in."""
    import json

    path = tmp_path / "new.json"
    outcome = reprobe().save(path)

    document = json.loads(path.read_text())
    assert outcome["merged"] is False
    assert document["denylist"] == []
    assert "input_sensitivity" in document


def test_an_unreadable_existing_profile_stops_the_write(tmp_path):
    """Overwriting it would destroy whatever is in there, and a file that
    will not parse is exactly the one worth keeping to look at."""
    import pytest as _pytest

    path = tmp_path / "broken.json"
    path.write_text("{not json at all", encoding="utf-8")

    with _pytest.raises(ValueError, match="could not be read"):
        reprobe().save(path)

    assert path.read_text() == "{not json at all"


def test_the_write_leaves_no_debris(tmp_path):
    path = curated(tmp_path)
    reprobe().save(path)

    assert not list(path.parent.glob("*.tmp"))


def test_a_hand_written_policy_profile_loads(tmp_path):
    """One that never came from a probe: no profile_id, no measurements,
    just policy. The example this project ships is exactly this shape, and
    it could not be read at all."""
    import json

    path = tmp_path / "policy.json"
    path.write_text(json.dumps({
        "_comment": "policy only",
        "denylist": ["*delete*"],
    }), encoding="utf-8")

    document = ProfileDocument.load(path)

    assert document.denylist == ["*delete*"]
    assert document.profile_id == ""
    assert document.matched_profile == "unknown"


def test_the_shipped_example_loads():
    """It is the thing operators copy. If it does not parse, the
    documentation is wrong in the most expensive possible way."""
    document = ProfileDocument.load("docs/example-profile.json")

    assert document.matched_profile == "L1"
    assert document.denylist
    assert document.input_sensitivity
