"""Render a window tree small enough to put in a tool result.

A legacy target has on the order of 1,100 windows. A raw dump is fine in a
file and fatal in an agent's context window, so this module is written to a
budget: filter to visible, cap depth, collapse repeated siblings, hard-cap
node count, and report truncation rather than hiding it (spec section 6.1).
"""

from dataclasses import dataclass, field

from .model.window import WindowNode


@dataclass
class Summary:
    text: str
    node_count: int
    truncated: bool
    suggested_locators: list[str] = field(default_factory=list)


def _label(node: WindowNode) -> str:
    if node.text:
        return f'{node.class_name} "{node.text}"'
    return node.class_name


def summarize(
    tree: WindowNode,
    *,
    max_depth: int = 5,
    visible_only: bool = True,
    max_nodes: int = 200,
    collapse_threshold: int = 3,
) -> Summary:
    lines: list[str] = []
    suggested: list[str] = []
    state = {"emitted": 0, "truncated": False}

    def visible_children(node: WindowNode) -> list[WindowNode]:
        return [c for c in node.children if c.visible or not visible_only]

    def emit(text: str) -> bool:
        """Append a line; return False once the node budget is spent."""
        if state["emitted"] >= max_nodes:
            state["truncated"] = True
            return False
        lines.append(text)
        state["emitted"] += 1
        return True

    def render(node: WindowNode, depth: int) -> None:
        indent = "  " * depth
        if not emit(f"{indent}{_label(node)}"):
            return
        if node.text and node.class_name:
            candidate = f'class={node.class_name} text="{node.text}"'
            if candidate not in suggested:
                suggested.append(candidate)
        if depth + 1 >= max_depth:
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
                if not emit(f"{child_indent}[{len(members)} x {class_name}]"):
                    return
                # Captions carry the information a count destroys, so keep
                # them even when the structure is collapsed.
                for member in captioned:
                    if not emit(f'{child_indent}  "{member.text}"'):
                        return
                    candidate = f'class={class_name} text="{member.text}"'
                    if candidate not in suggested:
                        suggested.append(candidate)
            else:
                for member in members:
                    render(member, depth + 1)

    render(tree, 0)
    if state["truncated"]:
        lines.append(f"... truncated at {max_nodes} nodes")

    return Summary(
        text="\n".join(lines),
        node_count=state["emitted"],
        truncated=state["truncated"],
        suggested_locators=suggested,
    )
