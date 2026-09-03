"""An element that is not a window.

A tab item, a toolbar button, a menu entry, a grid cell: things a person
sees and clicks that own no window handle, and so exist only on the
accessibility surface. To the window tree they are nothing -- one
SysTabControl32 with no children -- which is why, until now, the safest
things to drive on the primary target could not be named at all.

Platform-neutral, like `WindowNode`: the backend produces these, the
resolver and the tools consume them. The runtime id is opaque and, like a
handle, valid only for the walk that produced it; re-resolution is by
locator, never by id.

The attribute names shared with `WindowNode` (`text`, `visible`, `enabled`,
`responsive`, `actionable`, `handle`) are deliberate: the wait conditions,
the denylist check and the actuation gate read those names, and an element
answers them in the terms that make sense for it. `handle` is the *host*
window -- the nearest window that owns the element -- because that is
where a posted message to it would go.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AccessibleElement:
    #: Opaque, per-walk identity. Never persisted, never returned as data.
    runtime_id: tuple[int, ...]
    #: UIA control type name: TabItem, Button, MenuItem, Pane, ...
    control_type: str
    name: str
    automation_id: str
    class_name: str
    rect: tuple[int, int, int, int]
    enabled: bool
    offscreen: bool
    #: Pattern names the element supports, e.g. ("SelectionItem",).
    patterns: tuple[str, ...]
    #: The nearest window owning the element, and its class.
    host_handle: int
    host_class: str
    #: Position among siblings *of the same control type* under the same
    #: parent element, 1-based. The only identity an unlabelled button has.
    sibling_index: int = 1
    #: For SelectionItem elements: whether it is selected now. None when
    #: the element does not carry the pattern.
    selected: bool | None = None
    #: The element's own value, when it publishes one (Value pattern).
    value: str | None = None
    pid: int = 0

    # --- the names shared with WindowNode ----------------------------------

    @property
    def text(self) -> str:
        return self.name

    @property
    def visible(self) -> bool:
        return not self.offscreen

    @property
    def responsive(self) -> bool:
        return True

    @property
    def actionable(self) -> bool:
        return self.enabled

    @property
    def handle(self) -> int:
        return self.host_handle

    # --- identity, for the denylist -----------------------------------------

    def identities(self) -> list[str]:
        """Every string an operator could name this element by.

        In order of how a person would write them: the caption; the
        type-qualified caption; the automation id; and, for an element with
        no caption at all, its type and position under its host window.
        The denylist matches any of them.
        """
        found = []
        if self.name:
            found.append(self.name)
            found.append(f"{self.control_type}:{self.name}")
        if self.automation_id:
            found.append(f"{self.control_type}#{self.automation_id}")
        found.append(f"{self.control_type}#{self.sibling_index}@{self.host_class}")
        return found

    def suggested_locator(self) -> str:
        """A locator string that would find this element again."""
        parts = [f"type={self.control_type}"]
        if self.name:
            parts.append(f'name="{self.name}"')
        else:
            parts.append(f"index={self.sibling_index - 1}")
        parts.append(f"within=(class={self.host_class})")
        return " ".join(parts)
