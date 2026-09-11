"""The place-plus-value locator (D#105): a control addressed by where it is
and what it shows, the value checked without disclosure.

Pure. The backend that supplies the `confirm` callback and the withholding
is proven elsewhere; everything here is decidable from data.
"""

import pytest

from ghostdriver.model.locator import Locator
from ghostdriver.model.result import GhostdriverError
from ghostdriver.model.window import WindowNode
from ghostdriver.resolve import resolve, resolve_one


def node(handle, cls, rect, text="", children=()):
    return WindowNode(handle=handle, class_name=cls, text=text, rect=rect,
                      visible=True, enabled=True, pid=1, children=tuple(children))


def tree_with_fields():
    """A top-level at screen (10, 20) holding three unnamed `text` fields at
    different y offsets -- the shape of Studio's Quality tab."""
    fields = [
        node(2, "text", (310, 828, 419, 850)),   # window-coords centre ~ (354, 819)
        node(3, "text", (310, 860, 419, 882)),
        node(4, "text", (310, 970, 419, 992)),
    ]
    return node(1, "frame", (10, 20, 1930, 1014), text="Untitled", children=fields)


# --- parsing ------------------------------------------------------------------

def test_region_and_value_parse():
    loc = Locator.parse('class=text region=290,808,440,840 value="0.16"')
    assert loc.region == (290, 808, 440, 840)
    assert loc.value == "0.16"


def test_region_roundtrips_through_describe():
    loc = Locator.parse('class=text region=290,808,440,840 value="0.16"')
    assert Locator.parse(loc.describe()) == loc


def test_an_empty_or_malformed_region_is_refused():
    with pytest.raises(ValueError, match="empty"):
        Locator.parse("region=100,100,50,50")   # right <= left
    with pytest.raises(ValueError, match="four integers"):
        Locator.parse("region=1,2,3")


def test_region_from_dict_accepts_list_and_object():
    loc = Locator.from_dict({"class_name": "text", "region": [1, 2, 3, 4]})
    assert loc.region == (1, 2, 3, 4)
    loc2 = Locator.from_dict(
        {"class_name": "text", "region": {"left": 1, "top": 2, "right": 3, "bottom": 4}})
    assert loc2.region == (1, 2, 3, 4)


# --- resolution: region -------------------------------------------------------

def test_region_selects_by_window_relative_centre():
    tree = tree_with_fields()
    # The first field's centre, in the frame's own coordinates, is about
    # (354, 819); a region around it selects exactly that field.
    loc = Locator.parse("class=text region=300,808,410,840")
    got = resolve(tree, loc)
    assert [n.handle for n in got] == [2]


def test_region_is_read_in_the_windows_own_coordinates():
    # A region using screen coordinates (offset by the frame origin) matches
    # nothing: the region is relative to the window, not the screen.
    tree = tree_with_fields()
    loc = Locator.parse("class=text region=310,828,419,850")  # screen-ish
    # centre in window coords is ~(354,819); this region (window coords)
    # is y 828..850, which the centre 819 is just above -> no match here,
    # proving the frame origin (20) was subtracted.
    assert resolve(tree, loc) == []


# --- resolution: value, via confirm ------------------------------------------

def test_value_uses_the_confirm_callback_and_selects_one():
    tree = tree_with_fields()
    shown = {2: "0.16", 3: "0.2", 4: "0.42"}

    def confirm(n, expected):
        return shown.get(n.handle) == expected

    loc = Locator.parse('class=text value="0.2"')
    got = resolve(tree, loc, confirm=confirm)
    assert [n.handle for n in got] == [3]


def test_place_and_value_together_pin_one_field():
    tree = tree_with_fields()
    shown = {2: "0.16", 3: "0.16", 4: "0.42"}  # two fields show 0.16

    def confirm(n, expected):
        return shown.get(n.handle) == expected

    # value alone is ambiguous (two show 0.16); place plus value is not.
    loc = Locator.parse('class=text region=300,808,410,840 value="0.16"')
    assert resolve_one(tree, loc, confirm=confirm).handle == 2


def test_a_value_locator_without_a_confirmer_is_refused():
    tree = tree_with_fields()
    loc = Locator.parse('class=text value="0.2"')
    with pytest.raises(GhostdriverError, match="no way to confirm"):
        resolve(tree, loc)  # confirm=None


def test_confirm_none_answer_is_not_a_match():
    tree = tree_with_fields()

    def confirm(n, expected):
        return None  # did not answer

    loc = Locator.parse('class=text value="0.2"')
    assert resolve(tree, loc, confirm=confirm) == []
