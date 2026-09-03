from dataclasses import FrozenInstanceError

import pytest

from ghostdriver.model.locator import Locator
from ghostdriver.model.result import ActionResult, ErrorKind
from ghostdriver.model.window import WindowNode


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
    with pytest.raises(FrozenInstanceError):
        n.handle = 2


def test_window_node_is_responsive_by_default():
    """A node says its text is trustworthy unless told otherwise."""
    assert leaf(1, "A", "a").responsive is True


def test_window_node_can_record_a_non_answering_control():
    """An unresponsive control must be distinguishable from an empty one.

    Both carry text="" — only this flag separates "no caption" from
    "the control never answered".
    """
    n = WindowNode(
        handle=1, class_name="A", text="", rect=(0, 0, 1, 1),
        visible=True, enabled=True, pid=1, children=(), responsive=False,
    )
    assert n.responsive is False
    assert n.text == ""


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


def test_locator_parse_rejects_role_with_an_explanation():
    """`role=` must fail loudly rather than resolve to nothing.

    resolve() returns False for any role predicate in Iteration 1, so a
    parsed role= locator matches zero elements with no indication why. The
    error has to say that role mapping is not here yet, not merely that
    something went wrong.
    """
    with pytest.raises(ValueError, match="role") as exc:
        Locator.parse("role=button")
    assert "later iteration" in str(exc.value)


def test_locator_role_field_survives_construction_in_code():
    """Only the command-line shorthand rejects role; the field stays.

    Profiles will populate it once role mapping exists, so removing the
    field would be a different and larger change than closing the CLI hole.
    """
    assert Locator(role="button").role == "button"
    assert Locator.from_dict(Locator(role="button").to_dict()).role == "button"


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


# --- select_main_tree ---------------------------------------------------
#
# These reproduce a real target's shape. A toolkit that minimizes to a
# taskbar proxy leaves a small always-visible proxy window owning every
# pooled form in the process, so the proxy wins on total node count while
# showing nothing. Choosing it made `find ... visible=true` answer "no
# matches" against a fully visible application.

def _n(handle, class_name, visible=True, children=()):
    return WindowNode(
        handle=handle, class_name=class_name, text="", rect=(0, 0, 1, 1),
        visible=visible, enabled=True, pid=1, children=tuple(children),
    )


def _proxy(n_hidden=8):
    """Visible frame, every descendant hidden. Large by total count."""
    kids = [_n(200 + i, "TPooledForm", visible=False) for i in range(n_hidden)]
    return _n(1, "TApplication", visible=True, children=kids)


def _real_ui(n_visible=4, root_visible=True):
    kids = [_n(300 + i, "TPanel", visible=True) for i in range(n_visible)]
    return _n(2, "TShellWin", visible=root_visible, children=kids)


def test_selects_the_window_showing_ui_not_the_largest():
    from ghostdriver.model.window import select_main_tree

    proxy = _proxy(n_hidden=20)          # 21 nodes, 1 visible
    real = _real_ui(n_visible=4)         # 5 nodes, 5 visible
    assert sum(1 for _ in proxy.walk()) > sum(1 for _ in real.walk())
    assert select_main_tree([proxy, real]).class_name == "TShellWin"
    assert select_main_tree([real, proxy]).class_name == "TShellWin"


def test_a_visible_frame_alone_does_not_beat_a_hidden_real_window():
    """The minimized case, and the bug's second form.

    Minimized, the proxy still carries the visible style on its own frame
    while the real window is hidden outright. Scoring "has any visible
    node" gives the proxy 1 against the real window's 0 and picks exactly
    the wrong one again.
    """
    from ghostdriver.model.window import select_main_tree

    proxy = _proxy(n_hidden=3)                        # 4 nodes, 1 visible
    hidden_real = _real_ui(n_visible=0, root_visible=False)
    hidden_real = WindowNode(
        handle=2, class_name="TShellWin", text="", rect=(0, 0, 1, 1),
        visible=False, enabled=True, pid=1,
        children=tuple(_n(400 + i, "TPanel", visible=False) for i in range(9)),
    )                                                 # 10 nodes, 0 visible
    assert select_main_tree([proxy, hidden_real]).class_name == "TShellWin"


def test_falls_back_to_size_when_nothing_is_visible_anywhere():
    from ghostdriver.model.window import select_main_tree

    small = _n(1, "TSmall", visible=False, children=[_n(11, "A", visible=False)])
    big = _n(2, "TBig", visible=False,
             children=[_n(20 + i, "B", visible=False) for i in range(6)])
    assert select_main_tree([small, big]).class_name == "TBig"


def test_no_trees_is_none_not_an_error():
    from ghostdriver.model.window import select_main_tree

    assert select_main_tree([]) is None
