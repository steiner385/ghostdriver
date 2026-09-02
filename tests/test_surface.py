"""Classifying which mechanism can drive each region.

The point of this module is to notice, from structural evidence alone, that
part of a UI needs a different approach -- and to notice when that answer
changes. So these tests are written around the evidence, never around the
control classes of any particular application.
"""

from ghostdriver.model.window import WindowNode
from ghostdriver.surface import (
    CHROME_ELEMENT_BUDGET,
    MIN_REGION_AREA,
    Region,
    RegionEvidence,
    SurfaceKind,
    classify_region,
    map_digest,
    non_native,
    surface_map,
    walk_regions,
)


def node(class_name="TThing", text="", w=400, h=300, visible=True,
         children=(), responsive=True, handle=1):
    return WindowNode(
        handle=handle, class_name=class_name, text=text,
        rect=(0, 0, w, h), visible=visible, enabled=True, pid=1,
        children=tuple(children), responsive=responsive,
    )


def kind_of(n, **evidence):
    base = dict(
        child_windows=len(n.children),
        answers_text=n.responsive,
        has_own_text=bool(n.text),
    )
    base.update(evidence)
    return classify_region(n, RegionEvidence(**base))[0]


# --- the four mechanisms ------------------------------------------------

def test_a_node_with_child_windows_is_native():
    parent = node(children=[node(handle=2)])
    assert kind_of(parent) is SurfaceKind.NATIVE


def test_a_node_that_answers_with_text_is_native():
    assert kind_of(node(text="Claim Task")) is SurfaceKind.NATIVE


def test_a_small_childless_leaf_is_native_not_a_region():
    """An empty edit is a control, not a drawing surface.

    Without a size floor every blank input in an application would be
    reported as needing pixels.
    """
    small = node(w=90, h=20)
    assert small.rect[2] * small.rect[3] < MIN_REGION_AREA
    assert kind_of(small) is SurfaceKind.NATIVE


def test_a_large_silent_childless_region_is_opaque():
    assert kind_of(node(w=900, h=200), accessible_elements=0) is SurfaceKind.OPAQUE


def test_a_region_with_an_element_tree_beneath_it_is_drivable():
    """The embedded-document case.

    No child windows and no text, exactly like an owner-drawn control --
    but another surface exposes structure inside it, so there is a way in
    that is not pixels.
    """
    assert kind_of(
        node(w=900, h=600),
        accessible_elements=CHROME_ELEMENT_BUDGET + 20,
        accessible_named=15,
    ) is SurfaceKind.ACCESSIBLE


def test_a_browser_host_class_is_a_web_document():
    assert kind_of(node(class_name="Chrome_WidgetWin_1")) is SurfaceKind.WEB
    assert kind_of(node(class_name="Internet Explorer_Server")) is SurfaceKind.WEB


def test_a_browser_host_wins_over_its_own_child_windows():
    """Order inside the classifier is load-bearing, and this is why.

    Measured on a real embedded browser: the host window owns a chain of
    compositing child windows -- a second host, a render-widget window, a
    D3D window. They are real child HWNDs, so the "window tree continues"
    test matches, and on evidence alone the region classifies as native.
    A caller would then walk into the compositor and try to drive a
    document with window messages.

    The class signature carries information no amount of probing recovers:
    with the engine's accessibility surface dormant, the host exposes a
    single Pane and nothing else.
    """
    host = node(class_name="Chrome_WidgetWin_0", w=1508, h=625, children=[
        node(class_name="Chrome_WidgetWin_1", handle=2, children=[
            node(class_name="Chrome_RenderWidgetHostHWND", handle=3),
        ]),
    ])
    assert kind_of(host) is SurfaceKind.WEB


def test_a_dormant_engine_is_still_a_web_document():
    """An embedded engine exposes its document tree lazily.

    Measured: 1 element, no patterns, depth 0 -- evidence indistinguishable
    from an empty container. The region is still a web document and still
    needs a DOM, so this must not depend on the engine having woken up.
    """
    assert kind_of(
        node(class_name="Chrome_WidgetWin_0", w=1508, h=625),
        accessible_elements=0,
        accessible_named=0,
    ) is SurfaceKind.WEB


def test_an_unresponsive_region_is_not_reported_as_opaque():
    """Silence is not emptiness.

    A control that never answered might be full of data. Calling it opaque
    would send a caller to OCR on the strength of a timeout.
    """
    assert kind_of(node(w=900, h=600, responsive=False)) is SurfaceKind.UNRESPONSIVE


# --- the trap this classifier fell into once ----------------------------

def test_a_scrollbars_own_elements_do_not_make_a_region_drivable():
    """The regression that matters.

    A scrollable owner-drawn region exposes its scrollbar on the
    accessibility surface -- a handful of pattern-bearing, *named* elements
    ("Page down", "Position"). An earlier version of this classifier
    treated any named element as content and would have reported every
    scrolling grid as drivable through a surface that held nothing but its
    own scrollbar. Measured against a real one: 6 elements, all chrome.
    """
    assert kind_of(
        node(w=1159, h=162),
        accessible_elements=6,
        accessible_named=6,
    ) is SurfaceKind.OPAQUE


def test_the_budget_is_a_threshold_not_a_coincidence():
    at_budget = kind_of(node(w=900, h=600),
                        accessible_elements=CHROME_ELEMENT_BUDGET)
    past_budget = kind_of(node(w=900, h=600),
                          accessible_elements=CHROME_ELEMENT_BUDGET + 1)
    assert at_budget is SurfaceKind.OPAQUE
    assert past_budget is SurfaceKind.ACCESSIBLE


# --- every answer carries its reasons -----------------------------------

def test_every_classification_explains_itself():
    """These are heuristics over partial evidence, so a caller who
    disagrees has to be able to see what the answer rested on."""
    for n, ev in (
        (node(children=[node(handle=2)]), {}),
        (node(text="x"), {}),
        (node(w=900, h=600), {"accessible_elements": 0}),
        (node(w=900, h=600), {"accessible_elements": 40}),
        (node(class_name="Chrome_WidgetWin_1"), {}),
        (node(w=900, h=600, responsive=False), {}),
    ):
        base = dict(child_windows=len(n.children), answers_text=n.responsive,
                    has_own_text=bool(n.text))
        base.update(ev)
        _, reason = classify_region(n, RegionEvidence(**base))
        assert reason and len(reason) > 10


# --- walking --------------------------------------------------------------

def test_a_web_host_is_not_descended_into():
    """Its child windows belong to the engine's compositor.

    They say nothing about the document, and walking them would report a
    web region as a stack of anonymous native panes.
    """
    host = node(class_name="Chrome_WidgetWin_1", handle=2,
                children=[node(class_name="Intermediate D3D Window", handle=3)])
    tree = node(class_name="Shell", handle=1, children=[host])

    walked = [n.class_name for n in walk_regions(tree)]
    assert "Chrome_WidgetWin_1" in walked
    assert "Intermediate D3D Window" not in walked


def test_evidence_is_only_gathered_where_it_can_change_the_answer():
    """Probing costs a walk per region, so it must not be done blindly.

    A node with child windows or its own text is already decided; asking
    another surface about it would buy nothing.
    """
    asked = []

    def gather(n):
        asked.append(n.class_name)
        return RegionEvidence(accessible_elements=0)

    tree = node(class_name="Shell", handle=1, w=900, h=600, children=[
        node(class_name="Decided_HasText", handle=2, text="Save", w=900, h=600),
        node(class_name="Undecided_BigAndSilent", handle=3, w=900, h=600),
        node(class_name="Decided_TooSmall", handle=4, w=10, h=10),
    ])
    surface_map(tree, gather)

    assert asked == ["Undecided_BigAndSilent"]


def test_non_native_is_the_caller_actionable_subset():
    tree = node(class_name="Shell", handle=1, children=[
        node(class_name="Button", handle=2, text="Go", w=80, h=20),
        node(class_name="Canvas", handle=3, w=900, h=600),
    ])
    regions = surface_map(tree)
    assert [r.class_name for r in non_native(regions)] == ["Canvas"]


# --- change detection -----------------------------------------------------

def _regions(*pairs):
    return [
        Region(class_name=c, rect=(0, 0, 10, 10), kind=k, reason="")
        for c, k in pairs
    ]


def test_the_digest_ignores_position_and_repetition():
    """Screens move and repopulate constantly. None of that changes how
    they have to be driven, and a digest that churned on it would train a
    caller to ignore the one signal it exists to give."""
    one = _regions(("Grid", SurfaceKind.OPAQUE), ("Btn", SurfaceKind.NATIVE))
    many = _regions(
        ("Grid", SurfaceKind.OPAQUE), ("Grid", SurfaceKind.OPAQUE),
        ("Btn", SurfaceKind.NATIVE), ("Btn", SurfaceKind.NATIVE),
    )
    assert map_digest(one) == map_digest(many)


def test_the_digest_changes_when_a_region_changes_kind():
    before = _regions(("Panel", SurfaceKind.NATIVE))
    after = _regions(("Panel", SurfaceKind.OPAQUE))
    assert map_digest(before) != map_digest(after)


def test_the_digest_changes_when_a_new_kind_appears():
    """A document appearing where there was none is exactly the moment an
    approach that worked stops working."""
    before = _regions(("Panel", SurfaceKind.NATIVE))
    after = before + _regions(("Host", SurfaceKind.WEB))
    assert map_digest(before) != map_digest(after)


# --- the probe has to reach past an engine's own chrome ------------------

#: Depth at which a real embedded browser engine's document content began,
#: beneath its root view, non-client view, frame view and browser view.
#: Measured live; anything shallower sees only the engine's own furniture.
ENGINE_CHROME_DEPTH = 5


def test_the_probe_reaches_past_an_engines_wrapper_views():
    """A shallow probe reports a full document as opaque.

    Measured against a live embedded engine rendering a real page: depths
    1-5 are the engine's own view hierarchy, 10 elements in total, and
    content only starts at depth 6. At the original probe depth of 4 the
    walk saw 7 elements -- below the scrollbar budget -- so a region full
    of readable, actuatable content was indistinguishable from an
    owner-drawn grid. The browser-class signature caught it anyway, which
    is exactly why the shallow probe went unnoticed for as long as it did.
    """
    from ghostdriver.backends.windows.region import PROBE_DEPTH

    assert PROBE_DEPTH > ENGINE_CHROME_DEPTH, (
        "the probe must reach past an engine's wrapper views, or regions "
        "with real content classify as opaque"
    )


def test_the_element_cap_clears_the_chrome_budget():
    """Otherwise the cap, not the evidence, decides the classification."""
    from ghostdriver.backends.windows.region import PROBE_ELEMENTS

    assert PROBE_ELEMENTS > CHROME_ELEMENT_BUDGET * 2


def test_a_budget_alone_cannot_hold_against_two_scrollbars():
    """Why scrollbars are excluded structurally rather than out-counted.

    A scrollbar contributes a container plus five parts, all named ("Line
    up", "Page down", "Position") -- 6 elements. One fits inside the
    budget. A region that scrolls in *both* directions contributes 12,
    clears the budget on furniture alone, and would be reported as
    drivable through an accessibility surface holding nothing at all.
    Found on a real owner-drawn grid that needed both scrollbars.

    Raising the budget only moves the goalposts; the walk now skips
    scrollbar subtrees outright, so no number of them can defeat it.
    """
    from ghostdriver.backends.windows.region import SCROLLBAR_CONTROL_TYPE

    ONE_SCROLLBAR = 6
    assert ONE_SCROLLBAR <= CHROME_ELEMENT_BUDGET, "one is absorbed"
    assert ONE_SCROLLBAR * 2 > CHROME_ELEMENT_BUDGET, "two are not"
    assert SCROLLBAR_CONTROL_TYPE == 50014, "UIA_ScrollBarControlTypeId"
