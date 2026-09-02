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
    Access,
    Region,
    RegionEvidence,
    SurfaceKind,
    classify_region,
    map_digest,
    needs_other_mechanism,
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


def classified(n, **evidence):
    base = dict(
        child_windows=len(n.children),
        answers_text=n.responsive,
        has_own_text=bool(n.text),
    )
    base.update(evidence)
    return classify_region(n, RegionEvidence(**base))


def kind_of(n, **evidence):
    return classified(n, **evidence)[0]


def access_of(n, **evidence):
    return classified(n, **evidence)[1]


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
    assert kind_of(node(w=900, h=200), accessible_elements=0) is SurfaceKind.OWNER_DRAWN


def test_a_region_with_an_element_tree_beneath_it_is_read_there():
    """Where the two axes come apart on the same region.

    No child windows and no text, exactly like an owner-drawn control --
    but another surface exposes structure inside it. It is still a native
    window; what changed is the way in.
    """
    evidence = dict(accessible_elements=CHROME_ELEMENT_BUDGET + 20,
                    accessible_named=15)

    assert kind_of(node(w=900, h=600), **evidence) is SurfaceKind.NATIVE
    assert access_of(node(w=900, h=600), **evidence) is Access.ACCESSIBILITY


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
    from an empty container. The region is still a web document, so the
    identity must not depend on the engine having woken up.
    """
    assert kind_of(
        node(class_name="Chrome_WidgetWin_0", w=1508, h=625),
        accessible_elements=0,
        accessible_named=0,
    ) is SurfaceKind.WEB


def _web_reason(**evidence):
    host = node(class_name="Chrome_WidgetWin_0", w=1508, h=625)
    base = dict(child_windows=1, answers_text=True, has_own_text=False)
    base.update(evidence)
    return classify_region(host, RegionEvidence(**base))[2]


def test_a_web_region_says_whether_it_can_be_read_right_now():
    """Identity and readability are different questions.

    The class settles what the region is. It settles nothing about how to
    read it: the same embedded engine is richly readable when rendered --
    measured at 165 elements with Value, Text and Invoke patterns -- and a
    single empty pane when dormant. A caller told only "web document" has
    to guess, and the expensive guess, "build a browser protocol", is the
    one the bare label invites.
    """
    host = node(class_name="Chrome_WidgetWin_1")
    live = classified(host, accessible_elements=40, accessible_named=13)
    dormant = classified(host, accessible_elements=0)

    # Identity is the same in both, which is the point of separating them.
    assert live[0] is dormant[0] is SurfaceKind.WEB

    # Readability is not, and it is a value rather than a turn of phrase.
    # It used to live only in the reason string, where nothing could act on
    # it and no change detector could see it.
    assert live[1] is Access.ACCESSIBILITY
    assert dormant[1] is Access.NONE

    assert "live" in live[2] and "40 elements" in live[2]
    assert "dormant" in dormant[2]


def test_a_web_region_is_probed_even_though_its_class_already_decided_it():
    """Every other region is probed only when the evidence could change
    the classification. A web host is the exception: its identity is
    settled, but its readability is not, and the probe is what tells them
    apart."""
    asked = []

    def gather(n):
        asked.append(n.class_name)
        return RegionEvidence(child_windows=1, accessible_elements=40)

    # Child windows would normally mark this "decided" and skip the probe.
    host = node(class_name="Chrome_WidgetWin_0", w=1508, h=625, children=[
        node(class_name="Chrome_WidgetWin_1", handle=2),
    ])
    tree = node(class_name="Shell", handle=9, children=[host])
    surface_map(tree, gather)

    assert "Chrome_WidgetWin_0" in asked


def test_an_unresponsive_region_is_not_reported_as_opaque():
    """Silence is not emptiness.

    A control that never answered might be full of data. Calling it opaque
    would send a caller to OCR on the strength of a timeout.
    """
    assert kind_of(node(w=900, h=600, responsive=False)) is SurfaceKind.UNKNOWN


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
    ) is SurfaceKind.OWNER_DRAWN


def test_the_budget_is_a_threshold_not_a_coincidence():
    at_budget = kind_of(node(w=900, h=600),
                        accessible_elements=CHROME_ELEMENT_BUDGET)
    past_budget = kind_of(node(w=900, h=600),
                          accessible_elements=CHROME_ELEMENT_BUDGET + 1)
    assert at_budget is SurfaceKind.OWNER_DRAWN
    assert past_budget is SurfaceKind.NATIVE


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
        _, _, reason = classify_region(n, RegionEvidence(**base))
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


def test_the_actionable_subset_is_chosen_by_access_not_by_kind():
    tree = node(class_name="Shell", handle=1, children=[
        node(class_name="Button", handle=2, text="Go", w=80, h=20),
        node(class_name="Canvas", handle=3, w=900, h=600),
    ])
    regions = surface_map(tree)
    assert [r.class_name for r in needs_other_mechanism(regions)] == ["Canvas"]


# --- change detection -----------------------------------------------------

def _regions(*triples):
    """(class, kind) or (class, kind, access)."""
    out = []
    for item in triples:
        cls, kind = item[0], item[1]
        access = item[2] if len(item) > 2 else Access.WINDOW_MESSAGES
        out.append(Region(class_name=cls, rect=(0, 0, 10, 10), kind=kind,
                          access=access, reason=""))
    return out


def test_the_digest_ignores_position_and_repetition():
    """Screens move and repopulate constantly. None of that changes how
    they have to be driven, and a digest that churned on it would train a
    caller to ignore the one signal it exists to give."""
    one = _regions(("Grid", SurfaceKind.OWNER_DRAWN), ("Btn", SurfaceKind.NATIVE))
    many = _regions(
        ("Grid", SurfaceKind.OWNER_DRAWN), ("Grid", SurfaceKind.OWNER_DRAWN),
        ("Btn", SurfaceKind.NATIVE), ("Btn", SurfaceKind.NATIVE),
    )
    assert map_digest(one) == map_digest(many)


def test_the_digest_changes_when_a_region_changes_kind():
    before = _regions(("Panel", SurfaceKind.NATIVE))
    after = _regions(("Panel", SurfaceKind.OWNER_DRAWN))
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


# --- the two axes move independently -------------------------------------

def test_the_digest_notices_an_engine_waking_up():
    """The defect that made the split worth doing.

    An embedded engine keeps its identity whether its document tree is live
    or dormant, while the way in changes completely between those states.
    Fingerprinting kind alone left the digest blind at the one moment a
    caller's approach had to change -- which is the whole reason the digest
    exists.

    The numbers are the ones measured on a real target: a single element
    while suspended, two hundred and three once awake.
    """
    host = node(class_name="Chrome_WidgetWin_1", handle=2)
    shell = node(class_name="Shell", handle=1, children=[host])

    dormant = surface_map(shell, lambda _: RegionEvidence(
        accessible_elements=1))
    live = surface_map(shell, lambda _: RegionEvidence(
        accessible_elements=203, accessible_named=88))

    assert [r.kind for r in dormant] == [r.kind for r in live], (
        "identity is unchanged, which is why kind alone could not see it"
    )
    assert map_digest(dormant) != map_digest(live)


def test_the_actionable_list_says_which_mechanism_each_region_needs():
    """What the split buys on this list, which is not what it looks like.

    Membership does not change: a live embedded document still cannot be
    read with window messages, so it still belongs here. What changes is
    that it now says *accessibility* -- a mechanism already in hand -- where
    before a caller saw only "web-document" and had to infer, and the
    obvious inference is the expensive one.
    """
    host = node(class_name="Chrome_WidgetWin_1", handle=2)
    shell = node(class_name="Shell", handle=1, children=[host])

    live = surface_map(shell, lambda _: RegionEvidence(
        accessible_elements=203, accessible_named=88))
    dormant = surface_map(shell, lambda _: RegionEvidence(
        accessible_elements=1))

    (live_region,) = needs_other_mechanism(live)
    (dormant_region,) = needs_other_mechanism(dormant)

    assert live_region.kind is dormant_region.kind is SurfaceKind.WEB
    assert live_region.access is Access.ACCESSIBILITY, "already reachable"
    assert dormant_region.access is Access.NONE, "this one is not"


def test_unknown_and_owner_drawn_are_not_the_same_answer():
    """One region is known to expose nothing; the other never said. Merging
    them would report a target that has stopped answering as a canvas, and
    send a caller to capture pixels of a window that may be about to
    recover."""
    silent = node(w=900, h=600, responsive=False)
    canvas = node(w=900, h=600)

    assert kind_of(silent) is SurfaceKind.UNKNOWN
    assert access_of(silent) is Access.NONE

    assert kind_of(canvas, accessible_elements=0) is SurfaceKind.OWNER_DRAWN
    assert access_of(canvas, accessible_elements=0) is Access.PIXELS
