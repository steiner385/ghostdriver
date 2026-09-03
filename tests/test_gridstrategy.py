"""Choosing a route to exact grid text, with no grid and no clipboard.

The routes are injected, so what is tested is judgement: the order they
are tried in, when the probe stops, and what counts as grid text at all.
"""

from ghostdriver.gridstrategy import (GridProbe, RouteResult, Strategy,
                                      find_grid_strategy, looks_like_a_grid)


def route(strategy, worked, lines=0, caveat=""):
    calls = []

    def run():
        calls.append(strategy)
        return RouteResult(strategy=strategy, worked=worked, lines=lines,
                           caveat=caveat)

    run.calls = calls
    return run


# --- what counts as grid text --------------------------------------------

def test_tab_and_newline_delimited_text_is_a_grid():
    ok, lines = looks_like_a_grid("Part No\tRev\tTitle\nCR3522\tA\tSnubbers\n")
    assert ok and lines == 2


def test_one_line_is_not_a_grid():
    """A single line is a caption or a status string. Calling that a working
    route would send a caller to a strategy that returns junk."""
    ok, _ = looks_like_a_grid("Just a caption\twith a tab")
    assert not ok


def test_lines_without_tabs_are_not_a_grid():
    ok, _ = looks_like_a_grid("line one\nline two\nline three")
    assert not ok


def test_empty_text_is_not_a_grid():
    assert looks_like_a_grid("") == (False, 0)


def test_windows_line_endings_are_counted_correctly():
    ok, lines = looks_like_a_grid("a\tb\r\nc\td\r\ne\tf\r\n")
    assert ok and lines == 3


# --- routes are tried cheapest-first -------------------------------------

def test_the_free_route_is_tried_before_the_clipboard():
    """Order is by interference, not likelihood: a region readable without
    a side effect must never be read with one."""
    free = route(Strategy.ACCESSIBLE_ON_FOCUS, worked=True, lines=40)
    clip = route(Strategy.CLIPBOARD_COPY, worked=True, lines=40)

    finding = find_grid_strategy(
        GridProbe(accessible_on_focus=free, clipboard_copy=clip))

    assert finding.strategy is Strategy.ACCESSIBLE_ON_FOCUS
    assert clip.calls == [], "the clipboard was never touched"


def test_the_clipboard_is_tried_only_after_the_free_route_fails():
    free = route(Strategy.ACCESSIBLE_ON_FOCUS, worked=False)
    clip = route(Strategy.CLIPBOARD_COPY, worked=True, lines=40,
                 caveat="clipboard is shared")

    finding = find_grid_strategy(
        GridProbe(accessible_on_focus=free, clipboard_copy=clip))

    assert finding.strategy is Strategy.CLIPBOARD_COPY
    assert free.calls and clip.calls
    assert finding.caveat == "clipboard is shared", "the side effect travels"


def test_no_route_working_is_unknown_not_a_guess():
    """UNKNOWN is the honest answer, and it is what defers OCR: the spec
    builds on pixels only once this has said nothing else works."""
    finding = find_grid_strategy(GridProbe(
        accessible_on_focus=route(Strategy.ACCESSIBLE_ON_FOCUS, worked=False),
        clipboard_copy=route(Strategy.CLIPBOARD_COPY, worked=False),
    ))

    assert finding.strategy is Strategy.UNKNOWN


def test_a_route_not_supplied_is_not_tried():
    """A caller that will not touch the clipboard passes only the free
    route, and the probe does not reach for one it was not given."""
    free = route(Strategy.ACCESSIBLE_ON_FOCUS, worked=False)

    finding = find_grid_strategy(GridProbe(accessible_on_focus=free))

    assert finding.strategy is Strategy.UNKNOWN
    attempted = {a["route"]: a for a in finding.attempts}
    assert attempted["clipboard_copy"]["tried"] is False


# --- what the finding reports --------------------------------------------

def test_every_route_tried_is_in_the_report():
    """A reader sees what the verdict rested on, not only the winner."""
    finding = find_grid_strategy(GridProbe(
        accessible_on_focus=route(Strategy.ACCESSIBLE_ON_FOCUS, worked=False),
        clipboard_copy=route(Strategy.CLIPBOARD_COPY, worked=True, lines=12),
    ))

    assert [a["route"] for a in finding.attempts] == [
        "accessible_on_focus", "clipboard_copy"]
    assert finding.attempts[0]["worked"] is False
    assert finding.attempts[1]["worked"] is True


def test_the_profile_entry_carries_shape_not_content():
    """The sample the profile keeps is a line count. Cell data is the
    target's business and never lands in a versioned document."""
    finding = find_grid_strategy(GridProbe(
        clipboard_copy=route(Strategy.CLIPBOARD_COPY, worked=True, lines=40,
                             caveat="clipboard is shared"),
    ))
    entry = finding.to_dict()

    assert entry["grid_strategy"] == "clipboard_copy"
    assert entry["sample_lines"] == 40
    assert entry["caveat"] == "clipboard is shared"
    assert "text" not in entry and "rows" not in entry
