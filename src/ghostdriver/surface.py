"""Which mechanism can drive each region of a window tree.

A target is rarely one kind of surface throughout. The same application can
put native controls in its toolbar, an owner-drawn grid in the middle, and
an embedded web document in a side panel -- and each needs a different way
in. Window messages read the first, only pixels reach the second, and the
third wants a DOM.

The tool's job is not to know which application does that. It is to notice,
per region, which case it is looking at, so a caller can pick a mechanism
and so a *change* in the answer is visible. That is why nothing here names
a product or a control class from any particular application: the evidence
is structural -- does the window tree continue, does the region answer a
text query, does some other surface expose an element tree beneath it.

Classification is deliberately conservative and always carries its reasons.
`reason` is not decoration: these are heuristics over incomplete evidence,
and a caller who disagrees needs to see what the answer was built on.
"""

import fnmatch
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterator

from .model.window import WindowNode


class SurfaceKind(str, Enum):
    """How a region can be driven."""

    #: The window tree continues here, or this node answers with its own
    #: text. Window messages reach it.
    NATIVE = "native"
    #: The window tree stops, but another surface exposes an element tree
    #: underneath. An embedded document is the usual case. Drive it through
    #: that surface, not through window messages.
    ACCESSIBLE = "accessible-surface"
    #: A host window for an embedded browser engine. Its content is a web
    #: document; the window tree cannot see into it and neither, usefully,
    #: can window messages.
    WEB = "web-document"
    #: The window tree stops, the region occupies real screen area, and no
    #: other surface exposes anything inside it. Whatever it displays, it
    #: draws itself. Pixels are the only way in.
    OPAQUE = "opaque"
    #: The region did not answer a text query, so its emptiness is unknown
    #: rather than established. Not the same as opaque, and must not be
    #: reported as it.
    UNRESPONSIVE = "unresponsive"


#: Window classes that host an embedded browser engine. These are framework
#: identifiers, not application ones: any product embedding these engines
#: produces the same class names, which is what makes them safe to match on.
WEB_HOST_CLASSES: tuple[str, ...] = (
    "Chrome_WidgetWin_*",       # CEF, Electron, WebView2
    "Internet Explorer_Server",  # MSHTML, still common in older desktop stacks
    "Shell DocObject View",
    "Shell Embedding",
    "MozillaWindowClass",
)

#: Below this, a childless window is an ordinary leaf control -- an empty
#: edit, a spacer -- not a region that draws its own content. Roughly a
#: 100x100 square: large enough to exclude buttons and inputs, small enough
#: to catch any region actually presenting data.
MIN_REGION_AREA = 10_000

#: A scrollable region attaches a scrollbar, and that scrollbar appears on
#: the accessibility surface as a handful of pattern-bearing elements. They
#: are the region's own chrome, not its content, and counting them as
#: content would report every scrollable opaque region as drivable. Measured
#: against a real owner-drawn grid: 7 elements, of which 6 carried patterns,
#: every one of them a scrollbar part.
CHROME_ELEMENT_BUDGET = 8


@dataclass(frozen=True, slots=True)
class RegionEvidence:
    """What was observed about one region. All of it structural."""

    child_windows: int = 0
    answers_text: bool = True
    has_own_text: bool = False
    #: Elements found beneath the region on the accessibility surface,
    #: excluding the element standing for the region itself.
    accessible_elements: int = 0
    accessible_named: int = 0
    accessible_max_depth: int = 0


@dataclass(frozen=True, slots=True)
class Region:
    class_name: str
    rect: tuple[int, int, int, int]
    kind: SurfaceKind
    reason: str
    handle: int = 0
    evidence: RegionEvidence = field(default_factory=RegionEvidence)

    @property
    def area(self) -> int:
        left, top, right, bottom = self.rect
        return max(0, right - left) * max(0, bottom - top)


def is_web_host(class_name: str) -> bool:
    return any(fnmatch.fnmatchcase(class_name, p) for p in WEB_HOST_CLASSES)


def _area(node: WindowNode) -> int:
    left, top, right, bottom = node.rect
    return max(0, right - left) * max(0, bottom - top)


def classify_region(
    node: WindowNode, evidence: RegionEvidence
) -> tuple[SurfaceKind, str]:
    """Decide how one region can be driven, and say why."""
    if is_web_host(node.class_name):
        # The class settles what this region *is*. It does not settle how to
        # read it, and those are different questions: an embedded engine
        # exposes its document tree lazily, so the same region is richly
        # readable when rendered and a single empty pane when dormant.
        # Reporting only the identity leaves a caller to guess which, and
        # the expensive guess -- "build a browser protocol" -- is the one
        # the bare label invites.
        content = evidence.accessible_elements
        if content > CHROME_ELEMENT_BUDGET:
            return SurfaceKind.WEB, (
                "window class hosts an embedded browser engine, and its "
                f"accessibility surface is live: {content} elements "
                f"({evidence.accessible_named} named) beneath it, readable "
                "without a separate browser protocol"
            )
        return SurfaceKind.WEB, (
            "window class hosts an embedded browser engine, but its "
            f"accessibility surface is dormant ({content} elements): "
            "reading it needs the engine woken, or a browser protocol"
        )

    if not evidence.answers_text:
        return (
            SurfaceKind.UNRESPONSIVE,
            "did not answer a text query; contents unknown, not absent",
        )

    if evidence.child_windows:
        return (
            SurfaceKind.NATIVE,
            f"window tree continues ({evidence.child_windows} child windows)",
        )

    if evidence.has_own_text:
        return SurfaceKind.NATIVE, "answers with its own text"

    area = _area(node)
    if area < MIN_REGION_AREA:
        return (
            SurfaceKind.NATIVE,
            f"leaf control, {area}px is below the {MIN_REGION_AREA}px "
            "region threshold",
        )

    content = evidence.accessible_elements
    # Element count alone decides this, deliberately. A named-element test
    # looks stronger and is worse: a scrollbar's own parts carry names
    # ("Page down", "Position"), so any scrollable owner-drawn region would
    # pass it and be reported as drivable through an accessibility surface
    # that holds nothing but its scrollbar. Names are recorded as evidence
    # and reported, but they do not decide.
    if content > CHROME_ELEMENT_BUDGET:
        return (
            SurfaceKind.ACCESSIBLE,
            f"no child windows, but {content} elements "
            f"({evidence.accessible_named} named) on the accessibility "
            f"surface beneath it, past the {CHROME_ELEMENT_BUDGET}-element "
            "chrome budget",
        )

    return (
        SurfaceKind.OPAQUE,
        f"{area}px with no child windows, no text, and "
        f"{content} accessible elements -- within a scrollbar's budget of "
        f"{CHROME_ELEMENT_BUDGET}, so nothing inside is exposed",
    )


def walk_regions(
    tree: WindowNode, *, visible_only: bool = True
) -> Iterator[WindowNode]:
    """Yield the nodes worth classifying, not descending into web hosts.

    An embedded browser creates its own child windows for compositing. They
    are an implementation detail of the engine, they say nothing about the
    document, and descending into them would report a web region as a stack
    of anonymous native panes.
    """
    def visit(node: WindowNode) -> Iterator[WindowNode]:
        if visible_only and not node.visible:
            return
        yield node
        if is_web_host(node.class_name):
            return
        for child in node.children:
            yield from visit(child)

    yield from visit(tree)


def surface_map(
    tree: WindowNode,
    gather: Callable[[WindowNode], RegionEvidence] | None = None,
    *,
    visible_only: bool = True,
) -> list[Region]:
    """Classify every region of `tree`.

    `gather` supplies the evidence a window tree alone cannot provide -- what
    another accessibility surface exposes beneath a node. It is only called
    for nodes that need it: a node with child windows or its own text is
    already decided, and probing the rest would cost a walk per control for
    an answer that cannot change. Without `gather`, regions are classified
    on tree evidence alone, which can only over-report OPAQUE.
    """
    regions: list[Region] = []
    for node in walk_regions(tree, visible_only=visible_only):
        base = RegionEvidence(
            child_windows=len(node.children),
            answers_text=node.responsive,
            has_own_text=bool(node.text),
        )
        # A web host is probed even though it has child windows and would
        # otherwise be "decided". Its identity is settled by class, but its
        # readability is not settled at all -- an embedded engine's
        # document tree comes and goes -- so it is the one region where
        # the evidence changes the advice rather than the classification.
        undecided = node.responsive and (
            is_web_host(node.class_name)
            or (
                not node.children
                and not node.text
                and _area(node) >= MIN_REGION_AREA
            )
        )
        evidence = gather(node) if (undecided and gather) else base
        kind, reason = classify_region(node, evidence)
        regions.append(
            Region(
                class_name=node.class_name,
                rect=node.rect,
                kind=kind,
                reason=reason,
                handle=node.handle,
                evidence=evidence,
            )
        )
    return regions


def non_native(regions: list[Region]) -> list[Region]:
    """The regions that need a mechanism other than window messages."""
    return [r for r in regions if r.kind is not SurfaceKind.NATIVE]


def map_digest(regions: list[Region]) -> str:
    """A stable fingerprint of the *shape* of a surface map.

    Deliberately blind to position and to how many of each region there are.
    Screens move, split and repopulate constantly; none of that changes how
    they must be driven. What this is sensitive to is a class changing kind
    -- a region that used to answer window messages now drawing itself, or
    an embedded document appearing where there was none -- which is exactly
    the moment a caller's approach stops working and it needs to notice.
    """
    import hashlib

    shape = sorted({f"{r.class_name}:{r.kind.value}" for r in regions})
    return hashlib.sha256("|".join(shape).encode()).hexdigest()[:16]


def summarize_kinds(regions: list[Region]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for region in regions:
        counts[region.kind.value] = counts.get(region.kind.value, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
