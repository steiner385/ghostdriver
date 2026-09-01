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
    """Dialog containing Panel with Button; identical Button in Panel outside Dialog.

    Tests nested within constraints: a Button is only matched if its Panel
    ancestor is inside the specified Dialog ancestor.
    """
    return node(1, "Root", children=[
        node(10, "Dialog", "MainDialog", children=[
            node(11, "Panel", "InnerPanel", children=[
                node(111, "Button", "SubmitButton"),
            ]),
        ]),
        node(20, "Panel", "OuterPanel", children=[
            node(21, "Button", "SubmitButton"),
        ]),
    ])


def test_nested_within_matches_only_button_inside_dialog():
    """Nested within constraints must be checked recursively at each level.

    Without recursive checking, the Button under OuterPanel would incorrectly
    match because OuterPanel matches the panel constraint; it would only be
    excluded if we also check that the Panel is inside a Dialog.
    """
    tree = nested_within_tree()
    got = resolve(tree, Locator(
        class_name="Button", text="SubmitButton",
        within=Locator(
            class_name="Panel", text="InnerPanel",
            within=Locator(class_name="Dialog", text="MainDialog", visible=None),
        ),
    ))
    assert [n.handle for n in got] == [111]


def test_nested_within_excludes_button_outside_dialog():
    """Nested within excludes buttons whose ancestor chains don't satisfy the constraint.

    The Button at handle 21 must not match even though it has a Panel ancestor
    named SubmitButton, because that Panel is not inside a Dialog.
    """
    tree = nested_within_tree()
    got = resolve(tree, Locator(
        class_name="Button", text="SubmitButton",
        within=Locator(
            class_name="Panel", text="InnerPanel", visible=None,
            within=Locator(class_name="Dialog", text="MainDialog", visible=None),
        ),
    ))
    # Only the button inside the nested constraint should match
    assert [n.handle for n in got] == [111]
    # Verify the button outside the dialog is NOT in the result
    assert 21 not in [n.handle for n in got]
