from ghostdriver.model.locator import Locator
from ghostdriver.model.window import WindowNode
from ghostdriver.summarize import summarize


def node(handle, class_name, text="", visible=True, children=()):
    return WindowNode(
        handle=handle, class_name=class_name, text=text,
        rect=(0, 0, 10, 10), visible=visible, enabled=True,
        pid=1, children=tuple(children),
    )


def wide_tree(n_repeats=40):
    """One parent with many same-class, textless children.

    A real legacy target has ~1,100 windows dominated by repeated
    internal controls. Listing them all is what blows the context budget.
    """
    kids = [node(100 + i, "VendorEdit") for i in range(n_repeats)]
    return node(1, "Root", "Main", children=[node(10, "Panel", children=kids)])


def test_collapses_repeated_siblings_into_a_count():
    s = summarize(wide_tree(), collapse_threshold=3)
    assert "40 x VendorEdit" in s.text
    assert s.text.count("VendorEdit") == 1


def test_does_not_collapse_below_threshold():
    tree = node(1, "Root", children=[node(2, "A"), node(3, "A")])
    s = summarize(tree, collapse_threshold=3)
    assert "2 x A" not in s.text


def test_keeps_distinct_captions_when_collapsing():
    kids = [node(100 + i, "VendorButton", f"Btn{i}") for i in range(10)]
    s = summarize(node(1, "Root", children=kids), collapse_threshold=3)
    assert "Btn0" in s.text
    assert "10 x VendorButton" in s.text


def test_visible_only_is_the_default():
    tree = node(1, "Root", children=[node(2, "Shown"), node(3, "Hidden", visible=False)])
    s = summarize(tree)
    assert "Shown" in s.text
    assert "Hidden" not in s.text


def test_visible_only_false_includes_hidden():
    tree = node(1, "Root", children=[node(2, "Shown"), node(3, "Hidden", visible=False)])
    s = summarize(tree, visible_only=False)
    assert "Hidden" in s.text


def test_max_depth_is_respected():
    deep = node(1, "L1", children=[node(2, "L2", children=[node(3, "L3")])])
    s = summarize(deep, max_depth=2)
    assert "L2" in s.text
    assert "L3" not in s.text


def test_truncation_is_reported_not_silent():
    s = summarize(wide_tree(500), max_nodes=20, collapse_threshold=10_000)
    assert s.truncated is True
    assert "truncated" in s.text.lower()


def test_untruncated_output_says_so():
    s = summarize(node(1, "Root"))
    assert s.truncated is False


def test_suggests_locators_for_captioned_controls():
    tree = node(1, "Root", children=[node(2, "VendorButton", "Expand All")])
    s = summarize(tree)
    assert 'class=VendorButton text="Expand All"' in s.suggested_locators


def test_does_not_suggest_locators_for_textless_controls():
    tree = node(1, "Root", children=[node(2, "VendorPanel", "")])
    s = summarize(tree)
    assert not any("VendorPanel" in loc for loc in s.suggested_locators)


def test_collapsing_reports_the_descendants_it_hides():
    """A collapsed group must say how much it dropped.

    Silently eliding subtrees produces output that reads as the whole tree.
    On a real target whose top level is a repeated container class, that
    leaves only container captions to build locators from.
    """
    kids = [
        node(10 + i, "TabSheet", f"Tab{i}",
             children=[node(100 + i, "VendorButton", f"Save{i}")])
        for i in range(3)
    ]
    s = summarize(node(1, "Root", "Main", children=kids), collapse_threshold=3)
    assert "3 x TabSheet" in s.text
    assert "descendants not shown" in s.text
    assert s.elided_nodes == 3
    assert s.truncated is True


def test_no_elision_reported_when_nothing_is_hidden():
    """Collapsing childless siblings hides nothing and must not claim to."""
    kids = [node(10 + i, "VendorEdit") for i in range(4)]
    s = summarize(node(1, "Root", "Main", children=kids), collapse_threshold=3)
    assert s.elided_nodes == 0
    assert s.truncated is False


def test_suggested_locator_survives_a_caption_containing_a_quote():
    """A quoted caption must not produce a locator that parses to nothing.

    The suggested locators are copy-paste input for `ghostdriver find`,
    where shlex splits them. An unescaped embedded quote re-splits the
    tokens and yields a silent zero-match rather than an error.
    """
    tree = node(1, "Root", children=[node(2, "VendorButton", 'Say "Hi"')])
    s = summarize(tree)
    assert s.suggested_locators, "a captioned control must suggest a locator"
    parsed = Locator.parse(s.suggested_locators[0])
    assert parsed.class_name == "VendorButton"
    assert parsed.text == 'Say "Hi"'


# --- depth truncation must be reported ----------------------------------

def _chain(depth, class_name="TLevel"):
    """A single spine `depth` nodes deep."""
    leaf = node(1000 + depth, f"{class_name}{depth}")
    current = leaf
    for level in range(depth - 1, 0, -1):
        current = node(1000 + level, f"{class_name}{level}", children=[current])
    return current


def test_depth_cutoff_marks_the_summary_truncated():
    """The flag has to mean "this is not the whole tree".

    It previously covered only the node cap and sibling collapsing, so a
    summary that stopped at max_depth and dropped an entire document body
    reported truncated=False. A caller trusting that -- which is exactly
    what a tool schema does -- concluded the window held nothing.
    """
    summary = summarize(_chain(8), max_depth=3, max_nodes=200)

    assert summary.truncated
    assert summary.depth_elided_nodes == 5
    assert summary.elided_nodes == 0, "not collapsing; a different cause"


def test_no_depth_elision_when_the_tree_fits():
    summary = summarize(_chain(3), max_depth=10, max_nodes=200)

    assert not summary.truncated
    assert summary.depth_elided_nodes == 0


def test_the_depth_cut_is_marked_on_the_line_where_it_happened():
    """A count with no place attached left the caller guessing which node
    to root at (#28). A leaf at the floor lost nothing and is not marked."""
    parent = node(1, "Root", children=[
        node(2, "Mid", children=[node(3, "Leaf"), node(4, "Leaf")]),
        node(5, "Bare"),
    ])
    summary = summarize(parent, max_depth=2, max_nodes=200)

    assert "Mid [+2 below depth]" in summary.text
    assert "Bare [" not in summary.text


def test_depth_elision_counts_whole_subtrees_not_just_children():
    parent = node(1, "Root", children=[
        node(2, "Mid", children=[node(3, "Leaf"), node(4, "Leaf")]),
    ])
    summary = summarize(parent, max_depth=1, max_nodes=200)

    assert summary.depth_elided_nodes == 3


# --- caption clipping ----------------------------------------------------

def test_long_captions_are_clipped_and_say_how_much_was_withheld():
    """One control must not be able to eat the whole budget.

    A real target put a 363-character dispatch string in an address-bar
    control; rendered in full it accounted for 17% of the entire summary.
    """
    long_text = "x" * 500
    summary = summarize(node(1, "TAddressBar", text=long_text), max_text=80)

    assert long_text not in summary.text
    assert "x" * 80 in summary.text
    assert "(+420 more chars)" in summary.text


def test_a_clipped_caption_is_not_offered_as_a_locator():
    """Neither form of the suggestion is worth making.

    The clipped text would match nothing, and the full text is unusable on
    a command line -- so the node is left out of the suggestions rather
    than handed over as a locator that cannot work.
    """
    summary = summarize(node(1, "TAddressBar", text="y" * 300), max_text=80)

    assert summary.suggested_locators == []


def test_short_captions_are_untouched_and_still_suggested():
    summary = summarize(node(1, "TsfCommandButton", text="Claim Task"), max_text=80)

    assert '"Claim Task"' in summary.text
    assert summary.suggested_locators == [
        'class=TsfCommandButton text="Claim Task"'
    ]
