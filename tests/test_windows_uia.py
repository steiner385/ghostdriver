import pytest

from tests.conftest import main_tree, on_windows


def _main_hwnd(pid):
    """The main window's handle, selected the way the tool selects it.

    top_level_windows(pid)[0] is Z-order-first, not the application's main
    window; assessing a stray top-level window would produce a UIA verdict
    about the wrong thing.
    """
    return main_tree(pid).handle


@on_windows
def test_assessment_returns_a_populated_result(win32_target):
    from ghostdriver.backends.windows.uia import assess_uia
    got = assess_uia(_main_hwnd(win32_target))
    assert got.available is True
    assert got.element_count >= 1


@on_windows
def test_richness_is_the_pattern_ratio_it_claims_to_be(win32_target):
    """Richness must equal with_patterns/element_count, not merely be in range.

    Bounds alone cannot fail: richness is in [0,1] by construction, and a
    completely broken UIA path returns 0.0 and passes. Recomputing the ratio
    from the two counts, and requiring the walk to have found at least one
    element, is what makes the assertion capable of failing.
    """
    from ghostdriver.backends.windows.uia import assess_uia
    got = assess_uia(_main_hwnd(win32_target))
    assert got.element_count >= 1, "the walk found nothing to compute a ratio over"
    assert 0.0 <= got.richness <= 1.0
    assert got.with_patterns <= got.element_count
    assert got.richness == pytest.approx(got.with_patterns / got.element_count)


@on_windows
def test_control_type_histogram_is_populated(win32_target):
    from ghostdriver.backends.windows.uia import assess_uia
    assert sum(assess_uia(_main_hwnd(win32_target)).control_type_histogram.values()) >= 1


@on_windows
def test_raw_view_is_selectable(win32_target):
    """Control view filters elements; raw view does not.

    Comparing the two is what distinguishes "the walker was too shallow"
    from "the provider genuinely exposes nothing", so both must be
    reachable and both must actually run.

    What this can prove: the `view` argument is accepted, each call
    produces its own assessment, both walks completed, and the raw view is
    never smaller than the filtered one. What it cannot prove: that the
    two walks used different tree walkers. On a target whose control view
    filters nothing out the counts are legitimately equal, so an
    implementation that ignored `view` entirely would still satisfy the
    inequality here. Only a target with real filtered-out chrome
    distinguishes them, which is the Windows validation session's job.
    """
    from ghostdriver.backends.windows.uia import assess_uia
    control = assess_uia(_main_hwnd(win32_target), view="control")
    raw = assess_uia(_main_hwnd(win32_target), view="raw")
    assert control is not raw, "each call must produce its own assessment"
    assert control.available is True, "the control-view walk did not run"
    assert raw.available is True, "the raw-view walk did not run"
    assert raw.element_count >= control.element_count


def test_verdict_is_unusable_when_no_element_supports_a_pattern():
    from ghostdriver.backends.windows.uia import UiaAssessment, verdict_for
    assert verdict_for(UiaAssessment(
        available=True, element_count=92, with_patterns=0, richness=0.0,
    )) == "unusable"


def test_verdict_is_rich_when_most_elements_have_patterns():
    from ghostdriver.backends.windows.uia import UiaAssessment, verdict_for
    assert verdict_for(UiaAssessment(
        available=True, element_count=100, with_patterns=70, richness=0.7,
    )) == "rich"


def test_verdict_is_partial_in_between():
    from ghostdriver.backends.windows.uia import UiaAssessment, verdict_for
    assert verdict_for(UiaAssessment(
        available=True, element_count=100, with_patterns=15, richness=0.15,
    )) == "partial"


@on_windows
def test_invalid_handle_reports_unavailable_rather_than_raising():
    from ghostdriver.backends.windows.uia import assess_uia
    got = assess_uia(0xDEADBEEF)
    assert got.available is False


def test_partial_walk_results_are_preserved():
    """A walk that errors partway must keep what it already collected.

    Reporting available=False here would render as "no UIA provider", which
    is the signature of the hard profile this tool exists to detect -- so
    discarding a partial walk does not lose information, it fabricates a
    different and wrong conclusion.
    """
    from ghostdriver.backends.windows.uia import _build_assessment
    got = _build_assessment(
        {"count": 40, "with_patterns": 30, "depth": 5},
        {"Button": 30, "Pane": 10}, {"Invoke": 30}, [],
        error="walk aborted",
    )
    assert got.available is True
    assert got.element_count == 40
    assert got.verdict == "rich"
    assert got.error == "walk aborted"


def test_assessment_records_zero_richness_without_dividing_by_zero():
    """An empty walk must not raise, and must classify as empty."""
    from ghostdriver.backends.windows.uia import _build_assessment
    got = _build_assessment({"count": 0, "with_patterns": 0, "depth": 0}, {}, {}, [])
    assert got.richness == 0.0
    assert got.verdict == "empty"
