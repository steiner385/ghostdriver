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
