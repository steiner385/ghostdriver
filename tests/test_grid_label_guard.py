"""The guard that refuses a region `read` already answers (#141, D#141).

Neutral on purpose, and not because a Windows fixture was inconvenient. The
guard lives above the backend boundary -- it reads a `WindowNode`'s `text`
and a `Profile`, both platform-neutral -- while the failure it got wrong was
found on a real Win32 grid. Gating the check to Windows would put it on the
platform that happens to own the fixture rather than the one that owns the
promise, which is the whole of #39's finding. `text_guard` is the seam that
needs no backend, so the promise is checked wherever the suite runs; the same
promise driven end to end through `probe_grid` against a fixture grid that
reproduces the real control is in `tests/test_windows_grid.py`.
"""

from ghostdriver.model.window import WindowNode
from ghostdriver.session import Profile
from ghostdriver.tools.guidance import text_guard


def node(class_name: str, text: str) -> WindowNode:
    return WindowNode(handle=1, class_name=class_name, text=text,
                      rect=(46, 145, 469, 398), visible=True, enabled=True,
                      pid=4242)


#: The real control, as measured (D#1): an owner-drawn glyph grid whose class
#: answers WM_GETTEXT with a static accessible name.
CHARMAP_GRID = node("CharGridWClass", "Character Grid")


def test_a_region_with_no_text_is_not_refused():
    refusal, waiver = text_guard(Profile(), node("TsfDataGrid", ""),
                                 "class=TsfDataGrid")
    assert refusal is None and waiver is None


def test_an_undeclared_region_that_answers_is_still_refused():
    """The guard is not removed. A button's caption *is* its content, and
    probing one would spend a side effect on what `read` reads for free."""
    refusal, waiver = text_guard(
        Profile(), node("GhostFixtureCommandButton", "Expand All"),
        'class=GhostFixtureCommandButton text="Expand All"')

    assert waiver is None
    assert refusal is not None and "Use `read`" in refusal
    assert "Expand All" in refusal


def test_the_refusal_states_what_was_measured_and_not_what_was_inferred():
    """The refusal used to assert the region "is not a painted region" and
    send the caller to `read`. On the real grid both were false: it is
    painted, and `read` answered with the same label whatever was inside it
    -- a plausible, content-free answer the caller could not tell from a
    real one (D#1). What the tool knows is that a text query answered; that
    the answer is the content is the inference it must not make."""
    refusal, _ = text_guard(Profile(), CHARMAP_GRID, "class=CharGridWClass")

    assert refusal is not None
    assert "not a painted region" not in refusal
    assert "answers a text query" in refusal


def test_the_refusal_names_the_class_and_the_way_out():
    """A caller who cannot act on a refusal re-runs it. This one carries the
    class to list and the key to list it under."""
    refusal, _ = text_guard(Profile(), CHARMAP_GRID, "class=CharGridWClass")

    assert refusal is not None
    assert "'CharGridWClass'" in refusal and "text_is_label" in refusal


def test_a_declared_class_is_probed_rather_than_refused():
    """The fix (D#141): the operator declares that the text is a label, and
    the probe reaches the routes it exists to try."""
    profile = Profile(text_is_label=("CharGridWClass",))

    refusal, waiver = text_guard(profile, CHARMAP_GRID, "class=CharGridWClass")

    assert refusal is None
    assert waiver is not None and "'CharGridWClass'" in waiver
    assert "label, not content" in waiver


def test_the_declaration_is_matched_by_pattern_not_by_equality():
    profile = Profile(text_is_label=("CharGrid*",))
    assert text_guard(profile, CHARMAP_GRID, "x")[0] is None


def test_a_declaration_for_another_class_does_not_waive_this_one():
    """Declared knowledge is per class. A profile that names the grid does
    not thereby say the toolbar's caption is decorative too."""
    profile = Profile(text_is_label=("CharGridWClass",))

    refusal, waiver = text_guard(
        profile, node("GhostFixtureCommandButton", "Expand All"), "x")

    assert refusal is not None and waiver is None


def test_the_waiver_is_not_reported_for_a_region_that_said_nothing():
    """No text, no guard, nothing to waive -- even where the class is
    declared. A report saying the guard was waived when it never fired would
    be a note about a decision nobody made."""
    profile = Profile(text_is_label=("CharGridWClass",))

    refusal, waiver = text_guard(profile, node("CharGridWClass", ""), "x")

    assert refusal is None and waiver is None
