import pytest
from ghostdriver.model.window import WindowNode
from ghostdriver.model.locator import Locator
from ghostdriver.model.result import ErrorKind, ActionResult


def leaf(handle, class_name, text, visible=True):
    return WindowNode(
        handle=handle, class_name=class_name, text=text,
        rect=(0, 0, 10, 10), visible=visible, enabled=True,
        pid=1234, children=(),
    )


def test_window_node_walk_is_preorder():
    tree = WindowNode(
        handle=1, class_name="Root", text="", rect=(0, 0, 100, 100),
        visible=True, enabled=True, pid=1234,
        children=(leaf(2, "A", "a"), leaf(3, "B", "b")),
    )
    assert [n.handle for n in tree.walk()] == [1, 2, 3]


def test_window_node_depth_counts_levels():
    tree = WindowNode(
        handle=1, class_name="Root", text="", rect=(0, 0, 100, 100),
        visible=True, enabled=True, pid=1234,
        children=(WindowNode(
            handle=2, class_name="Mid", text="", rect=(0, 0, 50, 50),
            visible=True, enabled=True, pid=1234,
            children=(leaf(3, "Leaf", "x"),),
        ),),
    )
    assert tree.depth() == 3


def test_window_node_is_immutable():
    n = leaf(1, "A", "a")
    with pytest.raises(Exception):
        n.handle = 2


def test_locator_parse_class_and_text():
    loc = Locator.parse('class=VendorButton text="Expand All"')
    assert loc.class_name == "VendorButton"
    assert loc.text == "Expand All"
    assert loc.visible is True


def test_locator_parse_visible_false():
    loc = Locator.parse("class=VendorEdit visible=false")
    assert loc.visible is False


def test_locator_roundtrips_through_dict():
    loc = Locator(class_name="A", text="b", within=Locator(class_name="Tab"))
    assert Locator.from_dict(loc.to_dict()) == loc


def test_locator_rejects_unknown_key():
    with pytest.raises(ValueError, match="unknown locator key"):
        Locator.parse("colour=red")


def test_action_result_not_ok_when_postcondition_unverified():
    r = ActionResult(ok=True, tier_used=3, postcondition_verified=False)
    assert r.ok is False


def test_error_kind_has_spec_members():
    for name in (
        "NOT_FOUND", "AMBIGUOUS", "STALE", "NOT_ACTIONABLE",
        "DENIED_BY_POLICY", "DENIED_BY_ENVIRONMENT",
        "TIER_EXHAUSTED", "POSTCONDITION_FAILED", "TIMEOUT",
    ):
        assert hasattr(ErrorKind, name)
