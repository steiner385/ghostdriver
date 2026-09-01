from tests.conftest import on_windows


def _first_hwnd(pid):
    from ghostdriver.backends.windows.enumerate import top_level_windows
    return top_level_windows(pid)[0]


@on_windows
def test_assessment_returns_a_populated_result(tk_target):
    from ghostdriver.backends.windows.uia import assess_uia
    got = assess_uia(_first_hwnd(tk_target))
    assert got.available is True
    assert got.element_count >= 1


@on_windows
def test_richness_is_a_ratio_between_zero_and_one(tk_target):
    from ghostdriver.backends.windows.uia import assess_uia
    assert 0.0 <= assess_uia(_first_hwnd(tk_target)).richness <= 1.0


@on_windows
def test_control_type_histogram_is_populated(tk_target):
    from ghostdriver.backends.windows.uia import assess_uia
    assert sum(assess_uia(_first_hwnd(tk_target)).control_type_histogram.values()) >= 1


@on_windows
def test_raw_view_is_selectable(tk_target):
    """Control view filters elements; raw view does not.

    Comparing the two is what distinguishes "the walker was too shallow"
    from "the provider genuinely exposes nothing", so both must be
    reachable.
    """
    from ghostdriver.backends.windows.uia import assess_uia
    control = assess_uia(_first_hwnd(tk_target), view="control")
    raw = assess_uia(_first_hwnd(tk_target), view="raw")
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
