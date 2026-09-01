import pytest
from ghostdriver.model.window import WindowNode
from ghostdriver.model.locator import Locator
from ghostdriver.model.result import ErrorKind, GhostdriverError
from ghostdriver.resolve import resolve, resolve_one


def node(handle, class_name, text="", visible=True, children=()):
    return WindowNode(
        handle=handle, class_name=class_name, text=text,
        rect=(0, 0, 10, 10), visible=visible, enabled=True,
        pid=1, children=tuple(children),
    )


def stacked_tabs():
    """Two tab pages each holding a button with the identical caption.

    This is the shape that defeats coordinate-based addressing: both
    buttons carry the same class, the same text, and in the real world the
    same screen rectangle. Only the ancestor distinguishes them.
    """
    return node(1, "Root", children=[
        node(10, "TabPage", "Alpha", children=[
            node(11, "VendorButton", "Expand All"),
        ]),
        node(20, "TabPage", "Beta", visible=False, children=[
            node(21, "VendorButton", "Expand All", visible=False),
        ]),
    ])


def test_resolve_by_class_returns_preorder():
    tree = stacked_tabs()
    got = resolve(tree, Locator(class_name="VendorButton", visible=None))
    assert [n.handle for n in got] == [11, 21]


def test_resolve_defaults_to_visible_only():
    tree = stacked_tabs()
    got = resolve(tree, Locator(class_name="VendorButton"))
    assert [n.handle for n in got] == [11]


def test_resolve_within_disambiguates_identical_controls():
    tree = stacked_tabs()
    got = resolve(tree, Locator(
        class_name="VendorButton", text="Expand All", visible=None,
        within=Locator(class_name="TabPage", text="Beta", visible=None),
    ))
    assert [n.handle for n in got] == [21]


def test_resolve_class_supports_glob():
    tree = stacked_tabs()
    got = resolve(tree, Locator(class_name="Vendor*", visible=None))
    assert [n.handle for n in got] == [11, 21]


def test_resolve_text_supports_regex_when_slash_delimited():
    tree = stacked_tabs()
    got = resolve(tree, Locator(text="/^Expand/", visible=None))
    assert [n.handle for n in got] == [11, 21]


def test_resolve_index_selects_nth():
    tree = stacked_tabs()
    got = resolve(tree, Locator(class_name="VendorButton", visible=None, index=1))
    assert [n.handle for n in got] == [21]


def test_resolve_index_out_of_range_returns_empty():
    tree = stacked_tabs()
    assert resolve(tree, Locator(class_name="VendorButton", visible=None, index=9)) == []


def test_resolve_one_raises_not_found():
    with pytest.raises(GhostdriverError) as exc:
        resolve_one(stacked_tabs(), Locator(class_name="Nope"))
    assert exc.value.kind is ErrorKind.NOT_FOUND


def test_resolve_one_raises_ambiguous():
    with pytest.raises(GhostdriverError) as exc:
        resolve_one(stacked_tabs(), Locator(class_name="VendorButton", visible=None))
    assert exc.value.kind is ErrorKind.AMBIGUOUS


def test_resolve_one_succeeds_when_unique():
    got = resolve_one(stacked_tabs(), Locator(class_name="VendorButton"))
    assert got.handle == 11


def nested_within_tree():
    """Two identical Panel > Button subtrees; only one Panel is inside a Dialog.

    The panels are deliberately indistinguishable. That is what forces the
    nested constraint to do the work: a resolver that honours only the first
    level of `within` matches both buttons, because both sit under a Panel
    whose own class and text match.
    """
    return node(1, "Root", children=[
        node(10, "Dialog", "Confirm", children=[
            node(11, "Panel", "Body", children=[
                node(12, "Button", "OK"),
            ]),
        ]),
        node(20, "Panel", "Body", children=[
            node(21, "Button", "OK"),
        ]),
    ])


def test_nested_within_requires_every_level_to_match():
    """Only the button whose Panel sits inside a Dialog may match.

    Against a resolver that checks just the first level of `within`, this
    returns both buttons — the two Panels are identical, so the Dialog
    constraint is the only thing that can tell them apart.
    """
    got = resolve(nested_within_tree(), Locator(
        class_name="Button", text="OK",
        within=Locator(
            class_name="Panel", text="Body",
            within=Locator(class_name="Dialog"),
        ),
    ))
    assert [n.handle for n in got] == [12]


def test_nested_within_excludes_identical_subtree_outside_the_scope():
    """The button under the Dialog-less Panel must never match.

    Stated separately from the positive case so a resolver that returns
    both buttons fails on an explicit assertion rather than only on a
    list-equality mismatch.
    """
    got = resolve(nested_within_tree(), Locator(
        class_name="Button", text="OK",
        within=Locator(
            class_name="Panel", text="Body",
            within=Locator(class_name="Dialog"),
        ),
    ))
    assert 21 not in [n.handle for n in got]
