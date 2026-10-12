"""Render a window tree small enough to put in a tool result.

A legacy target has on the order of 1,100 windows. A raw dump is fine in a
file and fatal in an agent's context window, so this module is written to a
budget: filter to visible, cap depth, collapse repeated siblings, hard-cap
node count, and report truncation rather than hiding it (spec section 6.1).

Every way this module drops information has to be visible in its output.
Collapsing a run of siblings hides their subtrees as well as their count,
so the collapsed line states how many descendants went with them and the
summary is marked truncated. Output that silently reads as the whole tree
is worse than output that admits it is partial: the caller builds locators
from what it can see.
"""

from dataclasses import dataclass, field

from .model.window import WindowNode


@dataclass
class Summary:
    text: str
    node_count: int
    truncated: bool
    suggested_locators: list[str] = field(default_factory=list)
    #: Descendants dropped by sibling collapsing. Distinct from hitting the
    #: node cap, so a caller can tell "the tree is too big" from "repeated
    #: containers swallowed their contents".
    elided_nodes: int = 0
    #: Descendants dropped by the depth cap -- a third, separate cause. It
    #: is reported apart from `elided_nodes` because the remedy differs:
    #: raise --depth, not --collapse-threshold.
    depth_elided_nodes: int = 0


#: Longest caption rendered in full. A real target put a 363-character
#: dispatch string in an address-bar control; emitted in the tree and again
#: as a suggested locator, that one control accounted for 17% of the whole
#: summary -- on the command whose entire purpose is fitting a budget. The
#: full value stays available through `read`.
MAX_TEXT = 80


def _clip(text: str, max_text: int) -> str:
    """Shorten a caption, saying how much was withheld rather than eliding silently."""
    if max_text <= 0 or len(text) <= max_text:
        return text
    return f"{text[:max_text]}... (+{len(text) - max_text} more chars)"


def _label(node: WindowNode, max_text: int = MAX_TEXT) -> str:
    if node.text:
        return f'{node.class_name} "{_clip(node.text, max_text)}"'
    return node.class_name


def _quote(value: str) -> str:
    """Escape a caption for embedding in a double-quoted locator token.

    Suggested locators are meant to be copied straight onto the command
    line, where `shlex` parses them. A caption containing a double quote
    would otherwise split into tokens the parser mis-reads, producing a
    locator that matches nothing and explains nothing.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _descendant_count(node: WindowNode) -> int:
    """How many nodes hang below `node`, excluding `node` itself."""
    return sum(1 for _ in node.walk()) - 1


def summarize(
    tree: WindowNode,
    *,
    max_depth: int = 5,
    visible_only: bool = True,
    max_nodes: int = 200,
    collapse_threshold: int = 3,
    max_text: int = MAX_TEXT,
) -> Summary:
    lines: list[str] = []
    suggested: list[str] = []
    state = {"emitted": 0, "capped": False, "elided": 0, "depth_elided": 0}

    def visible_children(node: WindowNode) -> list[WindowNode]:
        return [c for c in node.children if c.visible or not visible_only]

    def emit(text: str) -> bool:
        """Append a line; return False once the node budget is spent."""
        if state["emitted"] >= max_nodes:
            state["capped"] = True
            return False
        lines.append(text)
        state["emitted"] += 1
        return True

    def suggest(class_name: str, text: str) -> None:
        # A caption longer than the clip width is not offered at all. The
        # clipped form would silently match nothing, and the full form is
        # unusable on a command line and blows the budget this module
        # exists to keep. Neither is a suggestion worth making.
        if max_text > 0 and len(text) > max_text:
            return
        candidate = f'class={class_name} text="{_quote(text)}"'
        if candidate not in suggested:
            suggested.append(candidate)

    def render(node: WindowNode, depth: int) -> None:
        indent = "  " * depth
        at_floor = depth + 1 >= max_depth
        # Everything below this point is being dropped. Counting it is what
        # stops a depth-limited summary from reporting itself as the whole
        # tree; marking the line says *where* it was dropped. On the real
        # client (#28) depth hid the whole document view, 54 of 282 windows,
        # and a total with no place attached left the caller guessing which
        # node to describe within.
        cut = sum(1 + _descendant_count(c) for c in visible_children(node)) if at_floor else 0
        mark = f" [+{cut} below depth]" if cut else ""
        if not emit(f"{indent}{_label(node, max_text)}{mark}"):
            return
        if node.text and node.class_name:
            suggest(node.class_name, node.text)
        if at_floor:
            state["depth_elided"] += cut
            return

        kids = visible_children(node)
        # Group same-class children so a run of identical internal controls
        # costs one line instead of forty.
        groups: dict[str, list[WindowNode]] = {}
        order: list[str] = []
        for child in kids:
            if child.class_name not in groups:
                groups[child.class_name] = []
                order.append(child.class_name)
            groups[child.class_name].append(child)

        for class_name in order:
            members = groups[class_name]
            captioned = [m for m in members if m.text]
            if len(members) >= collapse_threshold:
                child_indent = "  " * (depth + 1)
                # Collapsing drops the members' subtrees entirely. Say how
                # much went with them, so a short summary next to a large
                # window_count is recognisable as elision rather than as a
                # tree that genuinely has nothing in it.
                hidden = sum(_descendant_count(m) for m in members)
                head = f"[{len(members)} x {class_name}"
                if hidden:
                    head += f" — {hidden} descendants not shown"
                if not emit(f"{child_indent}{head}]"):
                    return
                state["elided"] += hidden
                # Captions carry the information a count destroys, so keep
                # them even when the structure is collapsed.
                for member in captioned:
                    if not emit(f'{child_indent}  "{_clip(member.text, max_text)}"'):
                        return
                    suggest(class_name, member.text)
            else:
                for member in members:
                    render(member, depth + 1)

    render(tree, 0)
    if state["capped"]:
        lines.append(f"... truncated at {max_nodes} nodes")

    return Summary(
        text="\n".join(lines),
        node_count=state["emitted"],
        # `truncated` means "this is not the whole tree", so it has to cover
        # every way this module drops nodes. It previously omitted the depth
        # cap, which is the most common of the three: a summary that stopped
        # at --depth and left out an entire document body reported
        # truncated=False, and a caller trusting that flag -- which is
        # exactly what a tool schema does -- concluded the editor contained
        # a panel and a status bar.
        truncated=bool(
            state["capped"]
            or state["elided"] > 0
            or state["depth_elided"] > 0
        ),
        suggested_locators=suggested,
        elided_nodes=state["elided"],
        depth_elided_nodes=state["depth_elided"],
    )
