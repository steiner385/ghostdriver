"""Elements that are not windows: the locator form, the resolver, the identity.

Pure. The backend that walks a real accessibility surface is proven in
test_windows_elements.py; everything here is decidable from data.
"""

import pytest

from ghostdriver.model.element import AccessibleElement
from ghostdriver.model.locator import Locator
from ghostdriver.model.window import WindowNode
from ghostdriver.policy import denied
from ghostdriver.resolve import resolve_elements


def element(control_type, name="", *, index=1, host="SysTabControl32",
            offscreen=False, enabled=True, class_name="", automation_id="",
            patterns=(), selected=None):
    return AccessibleElement(
        runtime_id=(42, hash((control_type, name, index)) & 0xFFFF),
        control_type=control_type, name=name, automation_id=automation_id,
        class_name=class_name, rect=(0, 0, 10, 10), enabled=enabled,
        offscreen=offscreen, patterns=tuple(patterns), host_handle=0x10,
        host_class=host, sibling_index=index, selected=selected,
    )


def window(handle, class_name, text="", children=()):
    return WindowNode(handle=handle, class_name=class_name, text=text,
                      rect=(0, 0, 100, 100), visible=True, enabled=True,
                      pid=1, children=tuple(children))


# --- the locator form ---------------------------------------------------------

def test_type_or_name_makes_an_element_locator():
    assert Locator.parse('type=TabItem name="Components"').is_element
    assert Locator.parse("type=TabItem").is_element
    assert Locator.parse('name="Components"').is_element
    assert not Locator.parse('class=Button text="Apply"').is_element


def test_an_element_locator_round_trips_through_describe():
    expr = 'type=TabItem name="Change Log" index=0 within=(class=SysTabControl32)'
    loc = Locator.parse(expr)

    again = Locator.parse(loc.describe())

    assert again == loc
    assert again.control_type == "TabItem" and again.name == "Change Log"
    assert again.within is not None and not again.within.is_element


def test_scopes_may_be_elements_or_windows():
    loc = Locator.parse("type=TabItem within=(type=Tab within=(class=GhostFixtureShell))")

    assert loc.within.is_element
    assert not loc.within.within.is_element


# --- the resolver -------------------------------------------------------------

TAB = element("Tab", host="SysTabControl32")
TABS = [element("TabItem", n, index=i + 1)
        for i, n in enumerate(("Operations", "Components", "Change Log"))]
BUTTONS = [element("MenuItem", "", index=i + 1, host="ToolbarWindow32",
                   patterns=("Invoke",)) for i in range(3)]
WALKED = [(TAB, ())] + [(t, (TAB,)) for t in TABS]
HOST_CHAIN = (window(1, "GhostFixtureShell", "Fixture"),
              window(0x10, "SysTabControl32"))


def test_type_and_name_select_one_element():
    found = resolve_elements(WALKED, HOST_CHAIN,
                             Locator.parse('type=TabItem name="Components"'))
    assert [e.name for e in found] == ["Components"]


def test_type_alone_lists_every_element_of_that_type_in_walk_order():
    found = resolve_elements(WALKED, HOST_CHAIN, Locator.parse("type=TabItem"))
    assert [e.name for e in found] == ["Operations", "Components", "Change Log"]


def test_type_matches_case_insensitively_and_with_wildcards():
    assert len(resolve_elements(WALKED, HOST_CHAIN, Locator.parse("type=tabitem"))) == 3
    assert len(resolve_elements(WALKED, HOST_CHAIN, Locator.parse("type=Tab*"))) == 4


def test_text_is_a_synonym_for_name_on_an_element():
    found = resolve_elements(WALKED, HOST_CHAIN,
                             Locator.parse('type=TabItem text="/Change/"'))
    assert [e.name for e in found] == ["Change Log"]


def test_index_picks_from_the_ordered_matches():
    found = resolve_elements(WALKED, HOST_CHAIN, Locator.parse("type=TabItem index=2"))
    assert [e.name for e in found] == ["Change Log"]
    assert resolve_elements(WALKED, HOST_CHAIN, Locator.parse("type=TabItem index=9")) == []


def test_an_element_scope_asks_the_accessibility_ancestors():
    inside = Locator.parse("type=TabItem within=(type=Tab)")
    outside = Locator.parse("type=TabItem within=(type=ToolBar)")

    assert len(resolve_elements(WALKED, HOST_CHAIN, inside)) == 3
    assert resolve_elements(WALKED, HOST_CHAIN, outside) == []


def test_a_window_scope_asks_the_host_window_and_its_ancestors():
    """The host itself counts: `within=(class=SysTabControl32)` names the
    window the tabs are in, and the shell above it is reachable too."""
    host = Locator.parse("type=TabItem within=(class=SysTabControl32)")
    shell = Locator.parse("type=TabItem within=(class=GhostFixtureShell)")
    nested = Locator.parse(
        "type=TabItem within=(class=SysTabControl32 within=(class=GhostFixtureShell))")
    elsewhere = Locator.parse("type=TabItem within=(class=ToolbarWindow32)")

    assert len(resolve_elements(WALKED, HOST_CHAIN, host)) == 3
    assert len(resolve_elements(WALKED, HOST_CHAIN, shell)) == 3
    assert len(resolve_elements(WALKED, HOST_CHAIN, nested)) == 3
    assert resolve_elements(WALKED, HOST_CHAIN, elsewhere) == []


def test_offscreen_elements_are_not_visible():
    hidden = element("TabItem", "Hidden", index=4, offscreen=True)
    walked = WALKED + [(hidden, (TAB,))]

    default = resolve_elements(walked, HOST_CHAIN, Locator.parse("type=TabItem"))
    any_visibility = resolve_elements(walked, HOST_CHAIN,
                                      Locator.parse("type=TabItem visible=false"))

    assert "Hidden" not in [e.name for e in default]
    assert [e.name for e in any_visibility] == ["Hidden"]


# --- identity: what the denylist can name --------------------------------------

def test_a_named_element_is_known_by_its_caption_and_its_typed_caption():
    tab = element("TabItem", "Change Log")
    assert tab.identities()[:2] == ["Change Log", "TabItem:Change Log"]


def test_an_unlabelled_element_is_known_by_type_and_position_under_its_host():
    third = element("MenuItem", "", index=3, host="ToolbarWindow32")
    assert third.identities() == ["MenuItem#3@ToolbarWindow32"]


def test_an_automation_id_is_an_identity_too():
    assert "Button#btnDelete" in element(
        "Button", "", automation_id="btnDelete").identities()


@pytest.mark.parametrize("pattern, identity", [
    ("*change log*", "Change Log"),
    ("TabItem:Change*", "TabItem:Change Log"),
    ("MenuItem#3@*", "MenuItem#3@ToolbarWindow32"),
])
def test_the_denylist_matches_any_identity(pattern, identity):
    assert denied(identity, [pattern]) is not None


def test_a_suggested_locator_finds_the_element_again():
    """Among its siblings, which is where an unlabelled element's position
    means something: the suggestion for a nameless button is its index
    among the buttons under the same host."""
    for group in (TABS, BUTTONS):
        walked = [(e, ()) for e in group]
        chain = (window(0x10, group[0].host_class),)
        for e in group:
            loc = Locator.parse(e.suggested_locator())
            assert resolve_elements(walked, chain, loc) == [e], e.suggested_locator()


def test_the_shared_names_answer_as_windownode_would():
    e = element("TabItem", "Components", enabled=False, offscreen=True)
    assert e.text == "Components"
    assert e.visible is False and e.enabled is False and e.actionable is False
    assert e.responsive is True and e.handle == 0x10
