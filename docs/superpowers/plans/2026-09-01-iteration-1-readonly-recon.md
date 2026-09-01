# Iteration 1 — Read-Only Reconnaissance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python library and CLI that, on Windows, enumerates a target application's window tree, resolves declarative locators against it, reads control text, and emits a capability profile document — touching no application state.

**Architecture:** A thin Windows adapter produces plain `WindowNode` trees and process facts. All matching, summarization, and inference logic operates on those data structures and is platform-independent. This keeps Win32 types out of the core model (spec §3.2) and makes roughly two-thirds of the code testable without Windows.

**Tech Stack:** Python 3.11+, pywin32, psutil, comtypes (UIA and MSAA), pytest. pywinauto is a declared dependency for later iterations but Iteration 1 does not call it — enumeration is direct so the tree shape stays under our control.

**Spec:** `docs/superpowers/specs/2026-09-01-desktop-automation-mcp-design.md`

## Global Constraints

- **Python 3.11+.** Uses `X | None` unions and `tuple[...]` generics without `__future__` imports.
- **Windows backend only.** Linux/X11 is a separate spec.
- **No Win32 types above the backend boundary.** No `HWND`, window-message constants, or `LPARAM` packing outside `src/ghostdriver/backends/windows/`. The core model sees `int` handles carried inside `WindowNode` and nothing else.
- **Iteration 1 is strictly read-only.** The only cross-process messages permitted are `WM_GETTEXT` (`0x000D`) and `WM_GETTEXTLENGTH` (`0x000E`). No `BM_*`, no `WM_LBUTTON*`, no `WM_SETTEXT`, no `WM_CHAR`, no `WM_USER`-range messages.
- **Every cross-process `SendMessage` uses `SendMessageTimeoutW` with `SMTO_ABORTIFHUNG` (`0x0002`) and an explicit timeout.** A hung target must never wedge the tool.
- **No vendor or product names** in code, tests, comments, docs, fixtures, or commit messages. Describe targets by tech stack: "32-bit Delphi VCL application", "owner-drawn grid", "vendor-registered window class".
- **Locators never carry handles across a public boundary.** Handles live inside `WindowNode` and are re-resolved per call.
- **`describe` output is hard-capped** and reports truncation explicitly rather than silently.

---

## File Structure

| Path | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, dependencies, pytest config |
| `src/ghostdriver/model/window.py` | `WindowNode` — the platform-neutral tree node |
| `src/ghostdriver/model/locator.py` | `Locator` — declarative query, parsing, serialization |
| `src/ghostdriver/model/result.py` | `ActionResult`, `ErrorKind`, `GhostdriverError` |
| `src/ghostdriver/resolve.py` | Pure locator resolution against a `WindowNode` tree |
| `src/ghostdriver/summarize.py` | Pure tree summarization for `describe` |
| `src/ghostdriver/probe/toolkit.py` | Pure toolkit inference from a module-path list |
| `src/ghostdriver/probe/profile.py` | `ProfileDocument` dataclass and JSON I/O |
| `src/ghostdriver/probe/runner.py` | Phase-1 probe orchestration |
| `src/ghostdriver/backends/windows/winapi.py` | ctypes declarations, argtypes, constants |
| `src/ghostdriver/backends/windows/enumerate.py` | Window-tree enumeration |
| `src/ghostdriver/backends/windows/text.py` | `WM_GETTEXT` read path |
| `src/ghostdriver/backends/windows/process.py` | Modules, bitness, DPI awareness, integrity level |
| `src/ghostdriver/backends/windows/uia.py` | UIA richness assessment |
| `src/ghostdriver/backends/windows/msaa.py` | MSAA assessment |
| `src/ghostdriver/cli.py` | `list-targets`, `describe`, `find`, `read`, `probe` |
| `docs/VALIDATION.md` | Runbook for the Windows validation session |

Files under `backends/windows/` are the only ones importing `ctypes`, `win32*`, or `comtypes`. Everything else is pure and testable on any platform.

---

## Task 1: Project scaffold and core model types

**Files:**
- Create: `pyproject.toml`
- Create: `src/ghostdriver/__init__.py`
- Create: `src/ghostdriver/model/__init__.py`
- Create: `src/ghostdriver/model/window.py`
- Create: `src/ghostdriver/model/locator.py`
- Create: `src/ghostdriver/model/result.py`
- Test: `tests/test_model.py`

**Interfaces:**
- Consumes: nothing
- Produces: `WindowNode(handle:int, class_name:str, text:str, rect:tuple[int,int,int,int], visible:bool, enabled:bool, pid:int, children:tuple[WindowNode,...])` with methods `walk()` and `depth()`; `Locator(class_name, text, role, within, visible, index)` with `Locator.parse(str)` and `.to_dict()`/`.from_dict()`; `ErrorKind` enum; `ActionResult`; `GhostdriverError`.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "ghostdriver"
version = "0.1.0"
description = "Desktop automation MCP server"
requires-python = ">=3.11"
dependencies = [
    "psutil>=5.9",
    "pywin32>=306; sys_platform == 'win32'",
    "comtypes>=1.2; sys_platform == 'win32'",
    "pywinauto>=0.6.8; sys_platform == 'win32'",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
ghostdriver = "ghostdriver.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_model.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ghostdriver'`

- [ ] **Step 4: Create `src/ghostdriver/__init__.py` and `src/ghostdriver/model/__init__.py`**

Both files are empty.

- [ ] **Step 5: Implement `src/ghostdriver/model/window.py`**

```python
"""Platform-neutral representation of a window tree.

Backends produce these; everything above the backend boundary consumes them.
No Win32 types appear here by design (spec section 3.2).
"""

from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True, slots=True)
class WindowNode:
    """One window in a target's tree.

    `handle` is an opaque integer supplied by the backend. It is valid only
    for the lifetime of the enumeration that produced it: the OS recycles
    handles, so it must never be persisted or returned to a caller.
    """

    handle: int
    class_name: str
    text: str
    rect: tuple[int, int, int, int]  # left, top, right, bottom, screen coords
    visible: bool
    enabled: bool
    pid: int
    children: tuple["WindowNode", ...] = ()

    def walk(self) -> Iterator["WindowNode"]:
        """Yield this node then all descendants, in pre-order."""
        yield self
        for child in self.children:
            yield from child.walk()

    def depth(self) -> int:
        """Number of levels in this subtree, counting this node as 1."""
        if not self.children:
            return 1
        return 1 + max(child.depth() for child in self.children)
```

- [ ] **Step 6: Implement `src/ghostdriver/model/locator.py`**

```python
"""Declarative element queries.

A Locator is the only durable way to refer to an element. Handles are
recycled by the OS and go void when a process exits, so resolution always
happens against a freshly enumerated tree (spec section 4.2).
"""

import shlex
from dataclasses import dataclass, asdict


@dataclass(frozen=True, slots=True)
class Locator:
    class_name: str | None = None
    text: str | None = None
    role: str | None = None
    within: "Locator | None" = None
    visible: bool | None = True
    index: int | None = None

    _KEYS = ("class", "text", "role", "visible", "index")

    @classmethod
    def parse(cls, expr: str) -> "Locator":
        """Parse `class=X text="y" visible=false index=0`.

        `within` is not expressible in this shorthand; build it in code or
        via from_dict(). Values may be quoted with shlex rules.
        """
        fields: dict[str, object] = {}
        for token in shlex.split(expr):
            if "=" not in token:
                raise ValueError(f"malformed locator token: {token!r}")
            key, _, value = token.partition("=")
            if key not in cls._KEYS:
                raise ValueError(f"unknown locator key: {key!r}")
            if key == "class":
                fields["class_name"] = value
            elif key == "visible":
                fields["visible"] = value.strip().lower() in ("1", "true", "yes")
            elif key == "index":
                fields["index"] = int(value)
            else:
                fields[key] = value
        return cls(**fields)  # type: ignore[arg-type]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Locator":
        data = dict(data)
        within = data.pop("within", None)
        return cls(within=cls.from_dict(within) if within else None, **data)

    def describe(self) -> str:
        """Human-readable form, for error messages."""
        parts = []
        if self.class_name:
            parts.append(f"class={self.class_name}")
        if self.text:
            parts.append(f'text="{self.text}"')
        if self.role:
            parts.append(f"role={self.role}")
        if self.visible is not None:
            parts.append(f"visible={str(self.visible).lower()}")
        if self.index is not None:
            parts.append(f"index={self.index}")
        if self.within:
            parts.append(f"within({self.within.describe()})")
        return " ".join(parts) or "<empty locator>"
```

- [ ] **Step 7: Implement `src/ghostdriver/model/result.py`**

```python
"""Structured outcomes. Spec section 9."""

from dataclasses import dataclass, field
from enum import Enum


class ErrorKind(str, Enum):
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    STALE = "stale"
    NOT_ACTIONABLE = "not_actionable"
    DENIED_BY_POLICY = "denied_by_policy"
    DENIED_BY_ENVIRONMENT = "denied_by_environment"
    TIER_EXHAUSTED = "tier_exhausted"
    POSTCONDITION_FAILED = "postcondition_failed"
    TIMEOUT = "timeout"


class GhostdriverError(Exception):
    def __init__(self, kind: ErrorKind, message: str, locator: str | None = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.locator = locator

    def to_dict(self) -> dict:
        return {"kind": self.kind.value, "message": self.message,
                "locator": self.locator}


@dataclass
class ActionResult:
    """Outcome of an action.

    `ok` is forced False when a declared postcondition did not verify. An
    action that cannot distinguish success from a no-op must not claim
    success (spec section 4.4).
    """

    ok: bool
    tier_used: int | None = None
    tiers_attempted: list[int] = field(default_factory=list)
    precondition_verified: bool | None = None
    postcondition_verified: bool | None = None
    elapsed_ms: int = 0
    error: dict | None = None

    def __post_init__(self) -> None:
        if self.postcondition_verified is False:
            self.ok = False
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pip install -e ".[dev]" && pytest tests/test_model.py -v`
Expected: PASS — 9 tests

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml src/ghostdriver tests/test_model.py
git commit -m "feat: add core model types (WindowNode, Locator, ActionResult)"
```

---

## Task 2: Pure locator resolution

**Files:**
- Create: `src/ghostdriver/resolve.py`
- Test: `tests/test_resolve.py`

**Interfaces:**
- Consumes: `WindowNode`, `Locator`, `ErrorKind`, `GhostdriverError` from Task 1
- Produces: `resolve(tree: WindowNode, locator: Locator) -> list[WindowNode]` returning matches in pre-order; `resolve_one(tree, locator) -> WindowNode` raising `GhostdriverError` with `NOT_FOUND` or `AMBIGUOUS`

- [ ] **Step 1: Write the failing test**

Create `tests/test_resolve.py`:

```python
import pytest
from ghostdriver.model.window import WindowNode
from ghostdriver.model.locator import Locator
from ghostdriver.model.result import ErrorKind, GhostdriverError
from ghostdriver.resolve import resolve, resolve_one


def node(handle, class_name, text="", visible=True, children=()):
    return WindowNode(
        handle=handle, class_name=class_name, text=text,
        rect=(0, 0, 10, 10), visible=visible, enabled=True,
        pid=1, children=tuple(children),
    )


def stacked_tabs():
    """Two tab pages each holding a button with the identical caption.

    This is the shape that defeats coordinate-based addressing: both
    buttons carry the same class, the same text, and in the real world the
    same screen rectangle. Only the ancestor distinguishes them.
    """
    return node(1, "Root", children=[
        node(10, "TabPage", "Alpha", children=[
            node(11, "VendorButton", "Expand All"),
        ]),
        node(20, "TabPage", "Beta", visible=False, children=[
            node(21, "VendorButton", "Expand All", visible=False),
        ]),
    ])


def test_resolve_by_class_returns_preorder():
    tree = stacked_tabs()
    got = resolve(tree, Locator(class_name="VendorButton", visible=None))
    assert [n.handle for n in got] == [11, 21]


def test_resolve_defaults_to_visible_only():
    tree = stacked_tabs()
    got = resolve(tree, Locator(class_name="VendorButton"))
    assert [n.handle for n in got] == [11]


def test_resolve_within_disambiguates_identical_controls():
    tree = stacked_tabs()
    got = resolve(tree, Locator(
        class_name="VendorButton", text="Expand All", visible=None,
        within=Locator(class_name="TabPage", text="Beta", visible=None),
    ))
    assert [n.handle for n in got] == [21]


def test_resolve_class_supports_glob():
    tree = stacked_tabs()
    got = resolve(tree, Locator(class_name="Vendor*", visible=None))
    assert [n.handle for n in got] == [11, 21]


def test_resolve_text_supports_regex_when_slash_delimited():
    tree = stacked_tabs()
    got = resolve(tree, Locator(text="/^Expand/", visible=None))
    assert [n.handle for n in got] == [11, 21]


def test_resolve_index_selects_nth():
    tree = stacked_tabs()
    got = resolve(tree, Locator(class_name="VendorButton", visible=None, index=1))
    assert [n.handle for n in got] == [21]


def test_resolve_index_out_of_range_returns_empty():
    tree = stacked_tabs()
    assert resolve(tree, Locator(class_name="VendorButton", visible=None, index=9)) == []


def test_resolve_one_raises_not_found():
    with pytest.raises(GhostdriverError) as exc:
        resolve_one(stacked_tabs(), Locator(class_name="Nope"))
    assert exc.value.kind is ErrorKind.NOT_FOUND


def test_resolve_one_raises_ambiguous():
    with pytest.raises(GhostdriverError) as exc:
        resolve_one(stacked_tabs(), Locator(class_name="VendorButton", visible=None))
    assert exc.value.kind is ErrorKind.AMBIGUOUS


def test_resolve_one_succeeds_when_unique():
    got = resolve_one(stacked_tabs(), Locator(class_name="VendorButton"))
    assert got.handle == 11
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_resolve.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ghostdriver.resolve'`

- [ ] **Step 3: Implement `src/ghostdriver/resolve.py`**

```python
"""Pure locator resolution against a WindowNode tree.

No platform calls. Everything here is testable on any OS, which is why the
backend's only job is producing the tree (spec section 3.2).
"""

import fnmatch
import re

from .model.locator import Locator
from .model.result import ErrorKind, GhostdriverError
from .model.window import WindowNode


def _text_matches(pattern: str, value: str) -> bool:
    """Exact match, unless the pattern is /slash-delimited/, then regex."""
    if len(pattern) >= 2 and pattern.startswith("/") and pattern.endswith("/"):
        return re.search(pattern[1:-1], value) is not None
    return pattern == value


def _node_matches(node: WindowNode, loc: Locator) -> bool:
    if loc.visible is not None and node.visible != loc.visible:
        return False
    if loc.class_name is not None and not fnmatch.fnmatchcase(
        node.class_name, loc.class_name
    ):
        return False
    if loc.text is not None and not _text_matches(loc.text, node.text):
        return False
    # `role` is a normalized label supplied by a profile; Iteration 1 has no
    # role mapping, so a role predicate matches nothing rather than
    # silently matching everything.
    if loc.role is not None:
        return False
    return True


def _walk_with_ancestors(
    node: WindowNode, ancestors: tuple[WindowNode, ...] = ()
):
    yield node, ancestors
    for child in node.children:
        yield from _walk_with_ancestors(child, ancestors + (node,))


def resolve(tree: WindowNode, locator: Locator) -> list[WindowNode]:
    """Return every node matching `locator`, in pre-order.

    `index`, when set, selects one match from that ordered list and is
    applied last. An out-of-range index yields no matches rather than an
    error, so callers distinguish "not there" from "ambiguous" uniformly.
    """
    matches: list[WindowNode] = []
    for node, ancestors in _walk_with_ancestors(tree):
        if not _node_matches(node, locator):
            continue
        if locator.within is not None and not any(
            _node_matches(a, locator.within) for a in ancestors
        ):
            continue
        matches.append(node)

    if locator.index is not None:
        if 0 <= locator.index < len(matches):
            return [matches[locator.index]]
        return []
    return matches


def resolve_one(tree: WindowNode, locator: Locator) -> WindowNode:
    """Resolve to exactly one node, or raise.

    Ambiguity is an error rather than a silent first-match, because on a
    target with ~1,100 windows a silent first-match is how a test starts
    asserting against the wrong control.
    """
    matches = resolve(tree, locator)
    if not matches:
        raise GhostdriverError(
            ErrorKind.NOT_FOUND,
            f"no element matched {locator.describe()}",
            locator.describe(),
        )
    if len(matches) > 1:
        raise GhostdriverError(
            ErrorKind.AMBIGUOUS,
            f"{len(matches)} elements matched {locator.describe()}; "
            f"add within=... or index=N",
            locator.describe(),
        )
    return matches[0]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_resolve.py -v`
Expected: PASS — 10 tests

- [ ] **Step 5: Commit**

```bash
git add src/ghostdriver/resolve.py tests/test_resolve.py
git commit -m "feat: add pure locator resolution with ancestor scoping"
```

---

## Task 3: Tree summarization for `describe`

**Files:**
- Create: `src/ghostdriver/summarize.py`
- Test: `tests/test_summarize.py`

**Interfaces:**
- Consumes: `WindowNode` from Task 1
- Produces: `summarize(tree, *, max_depth=5, visible_only=True, max_nodes=200, collapse_threshold=3) -> Summary` where `Summary` has fields `text: str`, `node_count: int`, `truncated: bool`, `suggested_locators: list[str]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_summarize.py`:

```python
from ghostdriver.model.window import WindowNode
from ghostdriver.summarize import summarize


def node(handle, class_name, text="", visible=True, children=()):
    return WindowNode(
        handle=handle, class_name=class_name, text=text,
        rect=(0, 0, 10, 10), visible=visible, enabled=True,
        pid=1, children=tuple(children),
    )


def wide_tree(n_repeats=40):
    """One parent with many same-class, textless children.

    A real legacy target has ~1,100 windows dominated by repeated
    internal controls. Listing them all is what blows the context budget.
    """
    kids = [node(100 + i, "VendorEdit") for i in range(n_repeats)]
    return node(1, "Root", "Main", children=[node(10, "Panel", children=kids)])


def test_collapses_repeated_siblings_into_a_count():
    s = summarize(wide_tree(), collapse_threshold=3)
    assert "40 x VendorEdit" in s.text
    assert s.text.count("VendorEdit") == 1


def test_does_not_collapse_below_threshold():
    tree = node(1, "Root", children=[node(2, "A"), node(3, "A")])
    s = summarize(tree, collapse_threshold=3)
    assert "2 x A" not in s.text


def test_keeps_distinct_captions_when_collapsing():
    kids = [node(100 + i, "VendorButton", f"Btn{i}") for i in range(10)]
    s = summarize(node(1, "Root", children=kids), collapse_threshold=3)
    assert "Btn0" in s.text
    assert "10 x VendorButton" in s.text


def test_visible_only_is_the_default():
    tree = node(1, "Root", children=[node(2, "Shown"), node(3, "Hidden", visible=False)])
    s = summarize(tree)
    assert "Shown" in s.text
    assert "Hidden" not in s.text


def test_visible_only_false_includes_hidden():
    tree = node(1, "Root", children=[node(2, "Shown"), node(3, "Hidden", visible=False)])
    s = summarize(tree, visible_only=False)
    assert "Hidden" in s.text


def test_max_depth_is_respected():
    deep = node(1, "L1", children=[node(2, "L2", children=[node(3, "L3")])])
    s = summarize(deep, max_depth=2)
    assert "L2" in s.text
    assert "L3" not in s.text


def test_truncation_is_reported_not_silent():
    s = summarize(wide_tree(500), max_nodes=20, collapse_threshold=10_000)
    assert s.truncated is True
    assert "truncated" in s.text.lower()


def test_untruncated_output_says_so():
    s = summarize(node(1, "Root"))
    assert s.truncated is False


def test_suggests_locators_for_captioned_controls():
    tree = node(1, "Root", children=[node(2, "VendorButton", "Expand All")])
    s = summarize(tree)
    assert 'class=VendorButton text="Expand All"' in s.suggested_locators


def test_does_not_suggest_locators_for_textless_controls():
    tree = node(1, "Root", children=[node(2, "VendorPanel", "")])
    s = summarize(tree)
    assert not any("VendorPanel" in loc for loc in s.suggested_locators)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_summarize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ghostdriver.summarize'`

- [ ] **Step 3: Implement `src/ghostdriver/summarize.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_summarize.py -v`
Expected: PASS — 10 tests

- [ ] **Step 5: Commit**

```bash
git add src/ghostdriver/summarize.py tests/test_summarize.py
git commit -m "feat: add budgeted tree summarization for describe"
```

---

## Task 4: Toolkit inference from a module list

**Files:**
- Create: `src/ghostdriver/probe/__init__.py`
- Create: `src/ghostdriver/probe/toolkit.py`
- Test: `tests/test_toolkit.py`

**Interfaces:**
- Consumes: nothing
- Produces: `ToolkitInference(toolkit: str, confidence: str, evidence: list[str])`; `infer_toolkit(module_paths: list[str]) -> ToolkitInference`

- [ ] **Step 1: Write the failing test**

Create `tests/test_toolkit.py`:

```python
from ghostdriver.probe.toolkit import infer_toolkit


def test_identifies_delphi_vcl_from_runtime_packages():
    got = infer_toolkit([
        r"C:\app\rtl170.bpl", r"C:\app\vcl170.bpl", r"C:\windows\user32.dll",
    ])
    assert got.toolkit == "delphi-vcl"
    assert got.confidence == "high"


def test_identifies_delphi_vcl_from_memory_manager_alone():
    got = infer_toolkit([r"C:\app\borlndmm.dll", r"C:\windows\user32.dll"])
    assert got.toolkit == "delphi-vcl"


def test_identifies_dotnet():
    got = infer_toolkit([r"C:\windows\system32\mscoree.dll", r"C:\app\clr.dll"])
    assert got.toolkit == "dotnet"


def test_identifies_java():
    assert infer_toolkit([r"C:\jre\bin\jvm.dll"]).toolkit == "java"


def test_identifies_mfc():
    assert infer_toolkit([r"C:\app\mfc42.dll"]).toolkit == "mfc"


def test_identifies_vb6():
    assert infer_toolkit([r"C:\windows\msvbvm60.dll"]).toolkit == "vb6"


def test_identifies_powerbuilder():
    assert infer_toolkit([r"C:\app\pbvm190.dll"]).toolkit == "powerbuilder"


def test_identifies_qt():
    assert infer_toolkit([r"C:\app\Qt5Core.dll"]).toolkit == "qt"


def test_reports_embedded_webview_alongside_host_toolkit():
    got = infer_toolkit([r"C:\app\vcl170.bpl", r"C:\app\WebView2Loader.dll"])
    assert got.toolkit == "delphi-vcl"
    assert "embedded-webview" in got.secondary


def test_matching_is_case_insensitive():
    assert infer_toolkit([r"C:\APP\VCL170.BPL"]).toolkit == "delphi-vcl"


def test_unknown_toolkit_is_reported_not_guessed():
    got = infer_toolkit([r"C:\windows\system32\user32.dll"])
    assert got.toolkit == "unknown"
    assert got.confidence == "low"


def test_evidence_names_the_matching_modules():
    got = infer_toolkit([r"C:\app\vcl170.bpl", r"C:\windows\user32.dll"])
    assert any("vcl170.bpl" in e for e in got.evidence)
    assert not any("user32.dll" in e for e in got.evidence)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_toolkit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ghostdriver.probe'`

- [ ] **Step 3: Create `src/ghostdriver/probe/__init__.py`**

Empty file.

- [ ] **Step 4: Implement `src/ghostdriver/probe/toolkit.py`**

```python
"""Infer a GUI toolkit from the modules a process has loaded.

Every framework drags in a signature runtime, which makes the loaded-module
list a reliable fingerprint. Pure function over a list of paths: the caller
supplies the list, so this is testable without a running process.
"""

import fnmatch
import os
from dataclasses import dataclass, field

#: Ordered most-specific first. Each entry maps a toolkit label to the
#: filename globs that identify it.
SIGNATURES: list[tuple[str, tuple[str, ...]]] = [
    ("delphi-vcl", ("vcl*.bpl", "rtl*.bpl", "borlndmm.dll", "midas.dll")),
    ("powerbuilder", ("pbvm*.dll", "libpb*.dll")),
    ("vb6", ("msvbvm60.dll", "msvbvm50.dll")),
    ("mfc", ("mfc*.dll",)),
    ("dotnet", ("mscoree.dll", "clr.dll", "coreclr.dll")),
    ("java", ("jvm.dll", "awt.dll", "jawt.dll")),
    ("qt", ("qt5core.dll", "qt6core.dll")),
    ("wxwidgets", ("wxmsw*.dll", "wxbase*.dll")),
]

#: Not host toolkits — these coexist with one and are reported separately.
SECONDARY_SIGNATURES: list[tuple[str, tuple[str, ...]]] = [
    ("embedded-webview", ("webview2loader.dll", "embeddedbrowserwebview.dll")),
    ("embedded-cef", ("libcef.dll",)),
]


@dataclass
class ToolkitInference:
    toolkit: str
    confidence: str  # "high" | "medium" | "low"
    evidence: list[str] = field(default_factory=list)
    secondary: list[str] = field(default_factory=list)


def _matches(names: list[str], patterns: tuple[str, ...]) -> list[str]:
    hits = []
    for name in names:
        for pattern in patterns:
            if fnmatch.fnmatchcase(name, pattern):
                hits.append(name)
                break
    return hits


def infer_toolkit(module_paths: list[str]) -> ToolkitInference:
    names = [os.path.basename(p).lower() for p in module_paths]

    secondary = [
        label for label, patterns in SECONDARY_SIGNATURES
        if _matches(names, patterns)
    ]

    for label, patterns in SIGNATURES:
        hits = _matches(names, patterns)
        if not hits:
            continue
        # Two or more independent signature files is materially stronger
        # evidence than one, which could be an incidental dependency.
        confidence = "high" if len(hits) >= 2 else "medium"
        return ToolkitInference(
            toolkit=label, confidence=confidence,
            evidence=sorted(set(hits)), secondary=secondary,
        )

    return ToolkitInference(
        toolkit="unknown", confidence="low", evidence=[], secondary=secondary
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_toolkit.py -v`
Expected: PASS — 12 tests

- [ ] **Step 6: Commit**

```bash
git add src/ghostdriver/probe tests/test_toolkit.py
git commit -m "feat: infer GUI toolkit from loaded-module fingerprint"
```

---

## Task 5: Windows API layer and window enumeration

**Files:**
- Create: `src/ghostdriver/backends/__init__.py`
- Create: `src/ghostdriver/backends/windows/__init__.py`
- Create: `src/ghostdriver/backends/windows/winapi.py`
- Create: `src/ghostdriver/backends/windows/enumerate.py`
- Create: `tests/conftest.py`
- Test: `tests/test_windows_enumerate.py`

**Interfaces:**
- Consumes: `WindowNode` from Task 1
- Produces: `winapi` module exposing `user32`, `kernel32`, `WM_GETTEXT`, `WM_GETTEXTLENGTH`, `SMTO_ABORTIFHUNG`, `GW_CHILD`, `GW_HWNDNEXT`, `send_message_timeout(hwnd, msg, wparam, lparam, timeout_ms) -> int | None`; `enumerate.top_level_windows(pid) -> list[int]`, `enumerate.build_tree(hwnd) -> WindowNode`, `enumerate.enumerate_process(pid) -> list[WindowNode]`

**Note on test targets:** these tests drive a real Tk window in a subprocess. Tk creates genuine Win32 windows with child controls, so enumeration is exercised cross-process — the case that actually matters — without needing a purpose-built fixture. The Profile L1 fixture arrives in Iteration 3.

- [ ] **Step 1: Write the shared test fixture**

Create `tests/conftest.py`:

```python
import subprocess
import sys
import time

import pytest

on_windows = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows backend test"
)

_TK_APP = """
import tkinter as tk
root = tk.Tk()
root.title("GhostdriverTestWindow")
tk.Button(root, text="Expand All").pack()
tk.Button(root, text="Collapse All").pack()
tk.Entry(root).pack()
root.geometry("300x200")
root.mainloop()
"""


@pytest.fixture
def tk_target():
    """Launch a Tk window in a subprocess and yield its pid.

    Cross-process is the case that matters: reading text and enumerating
    windows behave differently for windows we do not own.
    """
    proc = subprocess.Popen([sys.executable, "-c", _TK_APP])
    try:
        deadline = time.time() + 10
        from ghostdriver.backends.windows.enumerate import top_level_windows
        while time.time() < deadline:
            if top_level_windows(proc.pid):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Tk target did not create a window in time")
        time.sleep(0.3)  # let child widgets finish realizing
        yield proc.pid
    finally:
        proc.terminate()
        proc.wait(timeout=5)
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_windows_enumerate.py`:

```python
import pytest

from tests.conftest import on_windows

pytestmark = on_windows


@pytest.mark.usefixtures("tk_target")
def test_finds_top_level_window_for_pid(tk_target):
    from ghostdriver.backends.windows.enumerate import top_level_windows
    assert len(top_level_windows(tk_target)) >= 1


def test_builds_a_tree_with_children(tk_target):
    from ghostdriver.backends.windows.enumerate import (
        top_level_windows, build_tree,
    )
    tree = build_tree(top_level_windows(tk_target)[0])
    assert tree.children, "expected the Tk window to have child controls"
    assert tree.pid == tk_target


def test_tree_nodes_carry_class_and_rect(tk_target):
    from ghostdriver.backends.windows.enumerate import enumerate_process
    nodes = list(enumerate_process(tk_target)[0].walk())
    assert all(n.class_name for n in nodes)
    for n in nodes:
        left, top, right, bottom = n.rect
        assert right >= left and bottom >= top


def test_children_are_direct_not_flattened(tk_target):
    """GW_CHILD/GW_HWNDNEXT walking must produce a tree, not a flat list.

    EnumChildWindows returns all descendants, which would put grandchildren
    at depth 1 and destroy ancestor scoping.
    """
    from ghostdriver.backends.windows.enumerate import enumerate_process
    tree = enumerate_process(tk_target)[0]
    assert tree.depth() >= 2


def test_enumeration_is_stable_across_two_calls(tk_target):
    from ghostdriver.backends.windows.enumerate import enumerate_process
    first = [n.class_name for n in enumerate_process(tk_target)[0].walk()]
    second = [n.class_name for n in enumerate_process(tk_target)[0].walk()]
    assert first == second


def test_unknown_pid_yields_no_windows():
    from ghostdriver.backends.windows.enumerate import enumerate_process
    assert enumerate_process(999_999) == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_windows_enumerate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ghostdriver.backends'`

- [ ] **Step 4: Create package files**

`src/ghostdriver/backends/__init__.py` and `src/ghostdriver/backends/windows/__init__.py` are both empty.

- [ ] **Step 5: Implement `src/ghostdriver/backends/windows/winapi.py`**

```python
"""ctypes declarations for the Windows backend.

This is the only place Win32 constants and signatures live. argtypes and
restype are set explicitly on every function: without them ctypes truncates
64-bit pointers to int, which produces silent wrong answers rather than
errors.
"""

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t

# Read-only messages. Iteration 1 must never send anything else.
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E

SMTO_ABORTIFHUNG = 0x0002

GW_CHILD = 5
GW_HWNDNEXT = 2

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

WNDENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
)

user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL

user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND

user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int

user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL

user32.IsWindowEnabled.argtypes = [wintypes.HWND]
user32.IsWindowEnabled.restype = wintypes.BOOL

user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL

user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL

user32.GetWindowThreadProcessId.argtypes = [
    wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
]
user32.SendMessageTimeoutW.restype = LRESULT

# kernel32 handle-returning calls need explicit restype: without it ctypes
# assumes c_int and silently truncates a 64-bit HANDLE, which fails as a
# wrong answer rather than as an error.
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

kernel32.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
kernel32.IsWow64Process.restype = wintypes.BOOL


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return pid.value


def class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(wintypes.HWND(hwnd), buf, 256)
    return buf.value


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return (0, 0, 0, 0)
    return (rect.left, rect.top, rect.right, rect.bottom)


def send_message_timeout(
    hwnd: int, msg: int, wparam: int, lparam: int, timeout_ms: int = 200
) -> int | None:
    """Send a message with a hard timeout.

    Returns the message result, or None if the target did not answer.
    SMTO_ABORTIFHUNG is mandatory: a target that has stopped pumping
    messages must not be able to block the tool indefinitely.
    """
    out = ctypes.c_size_t()
    ok = user32.SendMessageTimeoutW(
        wintypes.HWND(hwnd), msg, wparam, lparam,
        SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(out),
    )
    if not ok:
        return None
    return out.value
```

- [ ] **Step 6: Implement `src/ghostdriver/backends/windows/enumerate.py`**

```python
"""Build platform-neutral WindowNode trees from live windows."""

import ctypes
from ctypes import wintypes

from ...model.window import WindowNode
from . import winapi
from .text import read_window_text


def top_level_windows(pid: int) -> list[int]:
    """Every top-level window belonging to `pid`, in Z-order."""
    found: list[int] = []

    def callback(hwnd, _lparam):
        if winapi.window_pid(hwnd) == pid:
            found.append(hwnd)
        return True

    winapi.user32.EnumWindows(winapi.WNDENUMPROC(callback), 0)
    return found


def direct_children(hwnd: int) -> list[int]:
    """Immediate children only.

    EnumChildWindows returns every descendant flattened, which would place
    grandchildren at depth 1 and make ancestor scoping meaningless. Walking
    GW_CHILD then GW_HWNDNEXT preserves the real tree.
    """
    out: list[int] = []
    child = winapi.user32.GetWindow(wintypes.HWND(hwnd), winapi.GW_CHILD)
    while child:
        out.append(child)
        child = winapi.user32.GetWindow(wintypes.HWND(child), winapi.GW_HWNDNEXT)
    return out


def build_tree(hwnd: int, *, max_depth: int = 32) -> WindowNode:
    """Recursively build a WindowNode for `hwnd` and its descendants."""

    def build(handle: int, depth: int) -> WindowNode:
        children: tuple[WindowNode, ...] = ()
        if depth < max_depth:
            children = tuple(
                build(c, depth + 1) for c in direct_children(handle)
            )
        return WindowNode(
            handle=handle,
            class_name=winapi.class_name(handle),
            text=read_window_text(handle) or "",
            rect=winapi.window_rect(handle),
            visible=bool(winapi.user32.IsWindowVisible(wintypes.HWND(handle))),
            enabled=bool(winapi.user32.IsWindowEnabled(wintypes.HWND(handle))),
            pid=winapi.window_pid(handle),
            children=children,
        )

    return build(hwnd, 0)


def enumerate_process(pid: int) -> list[WindowNode]:
    """One tree per top-level window of `pid`."""
    return [build_tree(h) for h in top_level_windows(pid)]
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_windows_enumerate.py -v`
Expected: PASS — 6 tests on Windows; all skipped elsewhere

- [ ] **Step 8: Commit**

```bash
git add src/ghostdriver/backends tests/conftest.py tests/test_windows_enumerate.py
git commit -m "feat: add Windows window-tree enumeration"
```

---

## Task 6: Cross-process text reading

**Files:**
- Create: `src/ghostdriver/backends/windows/text.py`
- Test: `tests/test_windows_text.py`

**Interfaces:**
- Consumes: `winapi` from Task 5
- Produces: `read_window_text(hwnd: int, timeout_ms: int = 200) -> str | None` — `None` means the window did not answer, `""` means it answered with no text

**Note:** Task 5's `enumerate.py` imports this module, so implement it before running Task 5's tests if executing out of order.

- [ ] **Step 1: Write the failing test**

Create `tests/test_windows_text.py`:

```python
import pytest

from tests.conftest import on_windows

pytestmark = on_windows


def test_reads_caption_of_a_cross_process_control(tk_target):
    from ghostdriver.backends.windows.enumerate import enumerate_process
    texts = {n.text for n in enumerate_process(tk_target)[0].walk()}
    assert "Expand All" in texts
    assert "Collapse All" in texts


def test_reads_top_level_window_title(tk_target):
    from ghostdriver.backends.windows.enumerate import enumerate_process
    assert enumerate_process(tk_target)[0].text == "GhostdriverTestWindow"


def test_returns_none_for_a_dead_handle():
    from ghostdriver.backends.windows.text import read_window_text
    assert read_window_text(0xDEADBEEF) is None


def test_distinguishes_empty_text_from_no_answer(tk_target):
    """A control with no caption returns "", not None.

    Collapsing the two would make "the control has no text" and "the target
    stopped responding" indistinguishable, which is exactly the ambiguity
    that produces false passes.
    """
    from ghostdriver.backends.windows.enumerate import enumerate_process
    results = [n.text for n in enumerate_process(tk_target)[0].walk()]
    assert "" in results
    assert None not in results
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_windows_text.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ghostdriver.backends.windows.text'`

- [ ] **Step 3: Implement `src/ghostdriver/backends/windows/text.py`**

```python
"""Read control text from another process.

GetWindowTextW returns the cached window text and comes back empty for many
cross-process controls. WM_GETTEXT asks the control itself and is the more
reliable read, at the cost of needing a timeout so an unresponsive target
cannot block us.

This is a read-only operation. WM_GETTEXT and WM_GETTEXTLENGTH are the only
messages Iteration 1 is permitted to send.
"""

from . import winapi


def read_window_text(hwnd: int, timeout_ms: int = 200) -> str | None:
    """Return the control's text.

    Returns "" when the control answered and has no text, and None when it
    did not answer at all. Callers must not collapse the two: "no caption"
    and "target is not responding" are different facts.
    """
    length = winapi.send_message_timeout(
        hwnd, winapi.WM_GETTEXTLENGTH, 0, 0, timeout_ms
    )
    if length is None:
        return None
    if length <= 0:
        return ""

    import ctypes

    buf = ctypes.create_unicode_buffer(length + 1)
    result = winapi.send_message_timeout(
        hwnd,
        winapi.WM_GETTEXT,
        length + 1,
        ctypes.cast(buf, ctypes.c_void_p).value or 0,
        timeout_ms,
    )
    if result is None:
        return None
    return buf.value
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_windows_text.py tests/test_windows_enumerate.py -v`
Expected: PASS — 10 tests on Windows

- [ ] **Step 5: Commit**

```bash
git add src/ghostdriver/backends/windows/text.py tests/test_windows_text.py
git commit -m "feat: add cross-process WM_GETTEXT read path"
```

---

## Task 7: Process facts — modules, bitness, DPI awareness, integrity

**Files:**
- Create: `src/ghostdriver/backends/windows/process.py`
- Test: `tests/test_windows_process.py`

**Interfaces:**
- Consumes: `winapi` from Task 5
- Produces: `ProcessFacts(pid, executable, bitness, wow64, integrity_level, dpi_awareness, modules)`; `process_facts(pid) -> ProcessFacts`; `list_modules(pid) -> list[str]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_windows_process.py`:

```python
import os

import pytest

from tests.conftest import on_windows

pytestmark = on_windows


def test_lists_modules_of_a_live_process(tk_target):
    from ghostdriver.backends.windows.process import list_modules
    mods = [m.lower() for m in list_modules(tk_target)]
    assert any(m.endswith("user32.dll") for m in mods)


def test_module_listing_works_across_bitness(tk_target):
    """psutil memory_maps reads the target's mappings directly.

    The .NET Process.Modules API returns only WOW64 stubs when a 64-bit
    caller inspects a 32-bit process, which silently under-reports. This
    path must not have that failure mode.
    """
    from ghostdriver.backends.windows.process import list_modules
    assert len(list_modules(tk_target)) > 5


def test_reports_executable_and_bitness(tk_target):
    from ghostdriver.backends.windows.process import process_facts
    facts = process_facts(tk_target)
    assert facts.executable.lower().endswith(".exe")
    assert facts.bitness in ("x86", "x64")


def test_reports_dpi_awareness(tk_target):
    from ghostdriver.backends.windows.process import process_facts
    assert process_facts(tk_target).dpi_awareness in (
        "unaware", "system", "per-monitor", "unknown",
    )


def test_reports_integrity_level(tk_target):
    from ghostdriver.backends.windows.process import process_facts
    assert process_facts(tk_target).integrity_level in (
        "untrusted", "low", "medium", "high", "system", None,
    )


def test_unknown_pid_returns_empty_module_list():
    from ghostdriver.backends.windows.process import list_modules
    assert list_modules(999_999) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_windows_process.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ghostdriver.backends.windows.process'`

- [ ] **Step 3: Implement `src/ghostdriver/backends/windows/process.py`**

```python
"""Facts about a target process.

Module listing goes through psutil's memory_maps, which reads the target's
own mappings. This matters: a 64-bit caller using the .NET Process.Modules
API against a 32-bit process gets only WOW64 stubs, which looks like a
process with six modules rather than a hundred.
"""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field

import psutil

from . import winapi

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

advapi32.OpenProcessToken.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)
]
advapi32.OpenProcessToken.restype = wintypes.BOOL

advapi32.GetTokenInformation.argtypes = [
    wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
advapi32.GetTokenInformation.restype = wintypes.BOOL

advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)

advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)

TOKEN_QUERY = 0x0008
TOKEN_INTEGRITY_LEVEL_CLASS = 25

INTEGRITY_RIDS = {
    0x0000: "untrusted",
    0x1000: "low",
    0x2000: "medium",
    0x3000: "high",
    0x4000: "system",
}

DPI_AWARENESS = {0: "unaware", 1: "system", 2: "per-monitor"}

MODULE_SUFFIXES = (".dll", ".bpl", ".exe", ".ocx", ".drv", ".cpl")


@dataclass
class ProcessFacts:
    pid: int
    executable: str
    bitness: str          # "x86" | "x64" | "unknown"
    wow64: bool
    integrity_level: str | None
    dpi_awareness: str
    modules: list[str] = field(default_factory=list)


def list_modules(pid: int) -> list[str]:
    try:
        maps = psutil.Process(pid).memory_maps()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return []
    seen: list[str] = []
    for entry in maps:
        path = entry.path
        if path.lower().endswith(MODULE_SUFFIXES) and path not in seen:
            seen.append(path)
    return seen


def _is_wow64(handle) -> bool | None:
    result = wintypes.BOOL()
    try:
        if not winapi.kernel32.IsWow64Process(handle, ctypes.byref(result)):
            return None
    except (AttributeError, OSError):
        return None
    return bool(result.value)


def _dpi_awareness(handle) -> str:
    try:
        shcore = ctypes.WinDLL("shcore")
    except OSError:
        return "unknown"
    value = ctypes.c_int()
    try:
        if shcore.GetProcessDpiAwareness(handle, ctypes.byref(value)) != 0:
            return "unknown"
    except OSError:
        return "unknown"
    return DPI_AWARENESS.get(value.value, "unknown")


def _integrity_level(handle) -> str | None:
    """Read the token's mandatory-label RID. Best effort."""
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(handle, TOKEN_QUERY, ctypes.byref(token)):
        return None
    try:
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(
            token, TOKEN_INTEGRITY_LEVEL_CLASS, None, 0, ctypes.byref(size)
        )
        if size.value == 0:
            return None
        buf = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(
            token, TOKEN_INTEGRITY_LEVEL_CLASS, buf, size, ctypes.byref(size)
        ):
            return None
        # TOKEN_MANDATORY_LABEL begins with SID_AND_ATTRIBUTES, whose first
        # member is a PSID.
        sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
        count = advapi32.GetSidSubAuthorityCount(sid)[0]
        rid = advapi32.GetSidSubAuthority(sid, count - 1)[0]
        return INTEGRITY_RIDS.get(rid, f"0x{rid:04X}")
    except OSError:
        return None
    finally:
        winapi.kernel32.CloseHandle(token)


def process_facts(pid: int) -> ProcessFacts:
    try:
        executable = psutil.Process(pid).exe()
    except (psutil.Error, OSError):
        executable = ""

    handle = winapi.kernel32.OpenProcess(
        winapi.PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    wow64, integrity, dpi = None, None, "unknown"
    if handle:
        try:
            wow64 = _is_wow64(handle)
            integrity = _integrity_level(handle)
            dpi = _dpi_awareness(handle)
        finally:
            winapi.kernel32.CloseHandle(handle)

    if wow64 is None:
        bitness = "unknown"
    else:
        bitness = "x86" if wow64 else "x64"

    return ProcessFacts(
        pid=pid, executable=executable, bitness=bitness,
        wow64=bool(wow64), integrity_level=integrity,
        dpi_awareness=dpi, modules=list_modules(pid),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_windows_process.py -v`
Expected: PASS — 6 tests on Windows

- [ ] **Step 5: Commit**

```bash
git add src/ghostdriver/backends/windows/process.py tests/test_windows_process.py
git commit -m "feat: gather process facts (modules, bitness, DPI, integrity)"
```

---

## Task 8: UIA richness assessment

**Files:**
- Create: `src/ghostdriver/backends/windows/uia.py`
- Test: `tests/test_windows_uia.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: `UiaAssessment(available, element_count, with_patterns, richness, control_type_histogram, pattern_histogram, max_depth_reached, verdict, sample)`; `assess_uia(hwnd, *, view="control", max_depth=12, max_elements=500) -> UiaAssessment`

- [ ] **Step 1: Write the failing test**

Create `tests/test_windows_uia.py`:

```python
import pytest

from tests.conftest import on_windows

pytestmark = on_windows


def _first_hwnd(pid):
    from ghostdriver.backends.windows.enumerate import top_level_windows
    return top_level_windows(pid)[0]


def test_assessment_returns_a_populated_result(tk_target):
    from ghostdriver.backends.windows.uia import assess_uia
    got = assess_uia(_first_hwnd(tk_target))
    assert got.available is True
    assert got.element_count >= 1


def test_richness_is_a_ratio_between_zero_and_one(tk_target):
    from ghostdriver.backends.windows.uia import assess_uia
    assert 0.0 <= assess_uia(_first_hwnd(tk_target)).richness <= 1.0


def test_control_type_histogram_is_populated(tk_target):
    from ghostdriver.backends.windows.uia import assess_uia
    assert sum(assess_uia(_first_hwnd(tk_target)).control_type_histogram.values()) >= 1


def test_raw_view_is_selectable(tk_target):
    """Control view filters elements; raw view does not.

    Comparing the two is what distinguishes "the walker was too shallow"
    from "the provider genuinely exposes nothing", so both must be
    reachable.
    """
    from ghostdriver.backends.windows.uia import assess_uia
    control = assess_uia(_first_hwnd(tk_target), view="control")
    raw = assess_uia(_first_hwnd(tk_target), view="raw")
    assert raw.element_count >= control.element_count


def test_verdict_is_unusable_when_no_element_supports_a_pattern():
    from ghostdriver.backends.windows.uia import UiaAssessment, verdict_for
    assert verdict_for(UiaAssessment(
        available=True, element_count=92, with_patterns=0, richness=0.0,
    )) == "unusable"


def test_verdict_is_rich_when_most_elements_have_patterns():
    from ghostdriver.backends.windows.uia import UiaAssessment, verdict_for
    assert verdict_for(UiaAssessment(
        available=True, element_count=100, with_patterns=70, richness=0.7,
    )) == "rich"


def test_verdict_is_partial_in_between():
    from ghostdriver.backends.windows.uia import UiaAssessment, verdict_for
    assert verdict_for(UiaAssessment(
        available=True, element_count=100, with_patterns=15, richness=0.15,
    )) == "partial"


def test_invalid_handle_reports_unavailable_rather_than_raising():
    from ghostdriver.backends.windows.uia import assess_uia
    got = assess_uia(0xDEADBEEF)
    assert got.available is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_windows_uia.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ghostdriver.backends.windows.uia'`

- [ ] **Step 3: Implement `src/ghostdriver/backends/windows/uia.py`**

```python
"""Assess how much a target exposes through UI Automation.

The question this answers is not "what is in the tree" but "is the tree
worth using". A provider-less application still produces a UIA tree via the
generic HWND fallback: every element reports as Pane and supports no
patterns. Counting pattern support is what separates that from a real
provider.

Both the control view and the raw view are walkable. Comparing them is how
an empty result is shown to be the provider's doing rather than the
walker's.
"""

from dataclasses import dataclass, field

#: Pattern IDs occupy a contiguous block starting at 10000.
PATTERN_IDS: dict[str, int] = {
    "Invoke": 10000,
    "Selection": 10001,
    "Value": 10002,
    "RangeValue": 10003,
    "Scroll": 10004,
    "ExpandCollapse": 10005,
    "Grid": 10006,
    "GridItem": 10007,
    "Window": 10009,
    "SelectionItem": 10010,
    "Table": 10012,
    "TableItem": 10013,
    "Text": 10014,
    "Toggle": 10015,
}

CONTROL_TYPE_NAMES = {
    50000: "Button",
    50004: "Edit",
    50020: "Text",
    50032: "Window",
    50033: "Pane",
}


@dataclass
class UiaAssessment:
    available: bool
    element_count: int = 0
    with_patterns: int = 0
    richness: float = 0.0
    control_type_histogram: dict[str, int] = field(default_factory=dict)
    pattern_histogram: dict[str, int] = field(default_factory=dict)
    max_depth_reached: int = 0
    verdict: str = "unknown"
    sample: list[str] = field(default_factory=list)
    error: str | None = None


def verdict_for(assessment: "UiaAssessment") -> str:
    """Classify a tree by how many of its elements are actionable.

    Zero pattern support means the tree carries structure and no semantics,
    which is worse than useless: it looks like data while supporting no
    action. That case is called out explicitly rather than folded into a
    low score.
    """
    if not assessment.available:
        return "unavailable"
    if assessment.element_count == 0:
        return "empty"
    if assessment.with_patterns == 0:
        return "unusable"
    if assessment.richness >= 0.5:
        return "rich"
    return "partial"


def _control_type_name(type_id: int) -> str:
    return CONTROL_TYPE_NAMES.get(type_id, f"ControlType({type_id})")


def assess_uia(
    hwnd: int, *, view: str = "control", max_depth: int = 12,
    max_elements: int = 500,
) -> UiaAssessment:
    try:
        import comtypes
        import comtypes.client

        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA
    except Exception as exc:  # pragma: no cover - environment dependent
        return UiaAssessment(available=False, error=f"UIA unavailable: {exc}")

    try:
        comtypes.CoInitialize()
        iuia = comtypes.client.CreateObject(
            UIA.CUIAutomation, interface=UIA.IUIAutomation
        )
        root = iuia.ElementFromHandle(hwnd)
        if not root:
            return UiaAssessment(available=False, error="no element for handle")
        walker = iuia.RawViewWalker if view == "raw" else iuia.ControlViewWalker
    except Exception as exc:
        return UiaAssessment(available=False, error=str(exc))

    control_types: dict[str, int] = {}
    patterns: dict[str, int] = {}
    sample: list[str] = []
    state = {"count": 0, "with_patterns": 0, "depth": 0}

    def supported_patterns(element) -> list[str]:
        found = []
        for name, pattern_id in PATTERN_IDS.items():
            try:
                if element.GetCurrentPattern(pattern_id):
                    found.append(name)
            except Exception:
                continue
        return found

    def visit(element, depth: int) -> None:
        if state["count"] >= max_elements or depth > max_depth:
            return
        state["count"] += 1
        state["depth"] = max(state["depth"], depth)

        try:
            type_name = _control_type_name(element.CurrentControlType)
            name = element.CurrentName or ""
            class_name = element.CurrentClassName or ""
        except Exception:
            type_name, name, class_name = "unreadable", "", ""

        control_types[type_name] = control_types.get(type_name, 0) + 1
        found = supported_patterns(element)
        if found:
            state["with_patterns"] += 1
            for pattern_name in found:
                patterns[pattern_name] = patterns.get(pattern_name, 0) + 1

        if len(sample) < 25:
            sample.append(
                f"{'  ' * depth}{type_name} name={name!r} "
                f"cls={class_name!r} patterns={found}"
            )

        try:
            child = walker.GetFirstChildElement(element)
        except Exception:
            return
        while child and state["count"] < max_elements:
            visit(child, depth + 1)
            try:
                child = walker.GetNextSiblingElement(child)
            except Exception:
                break

    try:
        visit(root, 0)
    except Exception as exc:
        return UiaAssessment(available=False, error=str(exc))

    count = state["count"]
    assessment = UiaAssessment(
        available=True,
        element_count=count,
        with_patterns=state["with_patterns"],
        richness=(state["with_patterns"] / count) if count else 0.0,
        control_type_histogram=control_types,
        pattern_histogram=patterns,
        max_depth_reached=state["depth"],
        sample=sample,
    )
    assessment.verdict = verdict_for(assessment)
    return assessment
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_windows_uia.py -v`
Expected: PASS — 8 tests on Windows

- [ ] **Step 5: Commit**

```bash
git add src/ghostdriver/backends/windows/uia.py tests/test_windows_uia.py
git commit -m "feat: assess UIA tree richness and pattern support"
```

---

## Task 9: MSAA assessment

**Files:**
- Create: `src/ghostdriver/backends/windows/msaa.py`
- Test: `tests/test_windows_msaa.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: `MsaaAssessment(available, probed, named, with_default_action, verdict, sample, error)`; `assess_msaa(handles: list[int]) -> MsaaAssessment`

- [ ] **Step 1: Write the failing test**

Create `tests/test_windows_msaa.py`:

```python
import pytest

from tests.conftest import on_windows

pytestmark = on_windows


def _handles(pid, limit=20):
    from ghostdriver.backends.windows.enumerate import enumerate_process
    return [n.handle for n in enumerate_process(pid)[0].walk()][:limit]


def test_probes_controls_and_reports_counts(tk_target):
    from ghostdriver.backends.windows.msaa import assess_msaa
    got = assess_msaa(_handles(tk_target))
    assert got.available is True
    assert got.probed >= 1


def test_verdict_is_identification_only_without_default_actions():
    from ghostdriver.backends.windows.msaa import MsaaAssessment, verdict_for
    assert verdict_for(MsaaAssessment(
        available=True, probed=50, named=40, with_default_action=0,
    )) == "identification-only"


def test_verdict_is_actionable_when_default_actions_exist():
    from ghostdriver.backends.windows.msaa import MsaaAssessment, verdict_for
    assert verdict_for(MsaaAssessment(
        available=True, probed=50, named=40, with_default_action=30,
    )) == "actionable"


def test_verdict_is_unusable_when_nothing_is_named():
    from ghostdriver.backends.windows.msaa import MsaaAssessment, verdict_for
    assert verdict_for(MsaaAssessment(
        available=True, probed=50, named=0, with_default_action=0,
    )) == "unusable"


def test_probes_direct_handles_not_synthesized_chrome(tk_target):
    """Counts must come from the handles we asked about.

    oleacc's default proxy fabricates a title bar, menu bars, and scroll
    bars for every window. Walking children inflates the numbers with
    controls that do not exist, so this assessment probes named handles
    directly instead.
    """
    from ghostdriver.backends.windows.msaa import assess_msaa
    handles = _handles(tk_target, limit=5)
    assert assess_msaa(handles).probed == len(handles)


def test_invalid_handles_do_not_raise():
    from ghostdriver.backends.windows.msaa import assess_msaa
    assert assess_msaa([0xDEADBEEF]).probed == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_windows_msaa.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ghostdriver.backends.windows.msaa'`

- [ ] **Step 3: Implement `src/ghostdriver/backends/windows/msaa.py`**

```python
"""Assess what the legacy accessibility surface offers.

Controls are probed directly by handle rather than by walking children.
oleacc's default proxy synthesizes a title bar, two menu bars, and scroll
bars for every window whether or not they exist, so a child walk reports
large numbers of push buttons that are pure fabrication. Probing named
handles keeps the counts honest.

The distinction that matters is naming versus actuation: a caption tells
you which control you found, a default action tells you that you can do
something with it. A surface that offers the first and not the second is
identification-only.
"""

from dataclasses import dataclass, field

OBJID_CLIENT = 0xFFFFFFFC
CHILDID_SELF = 0


@dataclass
class MsaaAssessment:
    available: bool
    probed: int = 0
    named: int = 0
    with_default_action: int = 0
    verdict: str = "unknown"
    sample: list[str] = field(default_factory=list)
    error: str | None = None


def verdict_for(assessment: "MsaaAssessment") -> str:
    if not assessment.available:
        return "unavailable"
    if assessment.probed == 0:
        return "empty"
    if assessment.with_default_action > 0:
        return "actionable"
    if assessment.named > 0:
        return "identification-only"
    return "unusable"


def assess_msaa(handles: list[int]) -> MsaaAssessment:
    try:
        import ctypes

        import comtypes
        import comtypes.client

        comtypes.client.GetModule("oleacc.dll")
        from comtypes.gen import Accessibility

        comtypes.CoInitialize()
        oleacc = ctypes.oledll.oleacc
    except Exception as exc:  # pragma: no cover - environment dependent
        return MsaaAssessment(available=False, error=f"oleacc unavailable: {exc}")

    named = 0
    actionable = 0
    sample: list[str] = []

    for handle in handles:
        accessible = None
        try:
            pointer = ctypes.POINTER(Accessibility.IAccessible)()
            oleacc.AccessibleObjectFromWindow(
                ctypes.c_void_p(handle),
                ctypes.c_ulong(OBJID_CLIENT),
                ctypes.byref(Accessibility.IAccessible._iid_),
                ctypes.byref(pointer),
            )
            accessible = pointer
        except Exception:
            accessible = None

        name, action, role = "", "", ""
        if accessible:
            for attribute, target in (
                ("accName", "name"), ("accDefaultAction", "action"),
                ("accRole", "role"),
            ):
                try:
                    value = getattr(accessible, attribute)(CHILDID_SELF)
                except Exception:
                    value = None
                if target == "name":
                    name = value or ""
                elif target == "action":
                    action = value or ""
                else:
                    role = str(value) if value is not None else ""

        if name:
            named += 1
        if action:
            actionable += 1
        if len(sample) < 25:
            sample.append(
                f"hwnd=0x{handle:08X} name={name!r} action={action!r} role={role}"
            )

    assessment = MsaaAssessment(
        available=True, probed=len(handles), named=named,
        with_default_action=actionable, sample=sample,
    )
    assessment.verdict = verdict_for(assessment)
    return assessment
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_windows_msaa.py -v`
Expected: PASS — 6 tests on Windows

- [ ] **Step 5: Commit**

```bash
git add src/ghostdriver/backends/windows/msaa.py tests/test_windows_msaa.py
git commit -m "feat: assess MSAA naming and default-action availability"
```

---

## Task 10: Profile document and phase-1 probe runner

**Files:**
- Create: `src/ghostdriver/probe/profile.py`
- Create: `src/ghostdriver/probe/runner.py`
- Test: `tests/test_profile.py`

**Interfaces:**
- Consumes: `ProcessFacts` (Task 7), `infer_toolkit` (Task 4), `assess_uia` (Task 8), `assess_msaa` (Task 9), `enumerate_process` (Task 5), `WindowNode` (Task 1)
- Produces: `class_census(tree) -> dict[str,int]`; `ProfileDocument` with `.to_dict()`, `.save(path)`, `.load(path)`, `.matched_profile`; `run_phase1(pid) -> ProfileDocument`

**Scope note:** phase 1 emits `actuation_map`, `grid_strategy`, `denylist`, and `environment_allowlist` as empty or `"unknown"`. These are filled by supervised phase-2 learning (Iteration 4) and by operator curation (spec §5.2). They are empty because nothing read-only can determine them, not because they are unfinished.

- [ ] **Step 1: Write the failing test**

Create `tests/test_profile.py`:

```python
import json

from ghostdriver.model.window import WindowNode
from ghostdriver.probe.profile import ProfileDocument, class_census, match_profile


def node(handle, class_name, children=()):
    return WindowNode(
        handle=handle, class_name=class_name, text="", rect=(0, 0, 1, 1),
        visible=True, enabled=True, pid=1, children=tuple(children),
    )


def test_class_census_counts_every_class():
    tree = node(1, "Root", [node(2, "Btn"), node(3, "Btn"), node(4, "Edit")])
    assert class_census(tree) == {"Root": 1, "Btn": 2, "Edit": 1}


def test_class_census_is_sorted_by_descending_count():
    tree = node(1, "Root", [node(2, "Btn"), node(3, "Btn")])
    assert list(class_census(tree))[0] == "Btn"


def test_matches_l1_when_uia_unusable_and_windows_are_plentiful():
    assert match_profile(
        uia_verdict="unusable", msaa_verdict="identification-only",
        window_count=1100, toolkit="delphi-vcl",
    ) == "L1"


def test_matches_m1_when_uia_is_rich():
    assert match_profile(
        uia_verdict="rich", msaa_verdict="actionable",
        window_count=200, toolkit="dotnet",
    ) == "M1"


def test_matches_o1_when_there_are_no_per_control_windows():
    assert match_profile(
        uia_verdict="unusable", msaa_verdict="unusable",
        window_count=3, toolkit="unknown",
    ) == "O1"


def test_profile_roundtrips_through_json(tmp_path):
    doc = ProfileDocument(
        profile_id="abc", matched_profile="L1",
        executable={"path": "x.exe", "bitness": "x86"},
        toolkit={"inferred": "delphi-vcl", "confidence": "high"},
    )
    path = tmp_path / "profile.json"
    doc.save(path)
    assert ProfileDocument.load(path).matched_profile == "L1"
    assert json.loads(path.read_text())["matched_profile"] == "L1"


def test_phase1_fields_that_require_actuation_are_empty_not_absent():
    """Phase 1 cannot learn these read-only, so they ship empty.

    Absent keys would make a phase-1 profile indistinguishable from a
    truncated one; empty values say "not yet learned" explicitly.
    """
    doc = ProfileDocument(profile_id="x", matched_profile="L1")
    data = doc.to_dict()
    assert data["actuation_map"] == {}
    assert data["grid_strategy"] == "unknown"
    assert data["denylist"] == []
    assert data["environment_allowlist"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_profile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ghostdriver.probe.profile'`

- [ ] **Step 3: Implement `src/ghostdriver/probe/profile.py`**

```python
"""The capability profile document.

A profile is data, not code: onboarding an application means producing one
of these, not writing a driver. Fields that only supervised actuation can
determine are present and empty in a phase-1 document rather than absent,
so a partial profile is never mistaken for a complete one.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..model.window import WindowNode


def class_census(tree: WindowNode) -> dict[str, int]:
    """Count window classes in a tree, most frequent first."""
    counts: dict[str, int] = {}
    for node in tree.walk():
        counts[node.class_name] = counts.get(node.class_name, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def match_profile(
    *, uia_verdict: str, msaa_verdict: str, window_count: int, toolkit: str
) -> str:
    """Classify a target into a capability profile (spec section 2).

    The distinguishing question for a target with no usable accessibility
    surface is whether it still has one window per control. If it does, it
    is drivable by window messages (L1). If it does not, only coordinates
    and OCR remain (O1).
    """
    if uia_verdict == "rich":
        return "M1"
    if window_count >= 50:
        return "L1"
    return "O1"


@dataclass
class ProfileDocument:
    profile_id: str
    matched_profile: str
    executable: dict = field(default_factory=dict)
    toolkit: dict = field(default_factory=dict)
    integrity_level: str | None = None
    dpi: dict = field(default_factory=dict)
    command_line: list[str] = field(default_factory=list)
    window_count: int = 0
    class_census: dict[str, int] = field(default_factory=dict)
    uia: dict = field(default_factory=dict)
    msaa: dict = field(default_factory=dict)

    # Populated by supervised phase-2 learning (Iteration 4) or by operator
    # curation. Empty here because nothing read-only can determine them.
    actuation_map: dict = field(default_factory=dict)
    grid_strategy: str = "unknown"
    focus_behavior: dict = field(default_factory=dict)
    denylist: list[str] = field(default_factory=list)
    environment_allowlist: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "matched_profile": self.matched_profile,
            "executable": self.executable,
            "toolkit": self.toolkit,
            "integrity_level": self.integrity_level,
            "dpi": self.dpi,
            "command_line": self.command_line,
            "window_count": self.window_count,
            "class_census": self.class_census,
            "uia": self.uia,
            "msaa": self.msaa,
            "actuation_map": self.actuation_map,
            "grid_strategy": self.grid_strategy,
            "focus_behavior": self.focus_behavior,
            "denylist": self.denylist,
            "environment_allowlist": self.environment_allowlist,
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: str | Path) -> "ProfileDocument":
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))
```

- [ ] **Step 4: Implement `src/ghostdriver/probe/runner.py`**

```python
"""Phase-1 probe: gather everything determinable without touching the target.

Phase 1 sends no message that can actuate a control. Its output is a
profile document plus enough evidence for a human to disagree with it.
"""

import hashlib

from ..model.window import WindowNode
from .profile import ProfileDocument, class_census, match_profile
from .toolkit import infer_toolkit


def _profile_id(executable: str, version: str) -> str:
    digest = hashlib.sha256(f"{executable}|{version}".encode()).hexdigest()
    return digest[:16]


def run_phase1(pid: int, *, msaa_sample: int = 40) -> ProfileDocument:
    """Profile a running process. Read-only."""
    import psutil

    from ..backends.windows.enumerate import enumerate_process
    from ..backends.windows.msaa import assess_msaa
    from ..backends.windows.process import process_facts
    from ..backends.windows.uia import assess_uia

    facts = process_facts(pid)
    trees: list[WindowNode] = enumerate_process(pid)
    if not trees:
        raise RuntimeError(f"pid {pid} has no top-level windows on this desktop")

    # Profile the largest tree: an application's main window is the one
    # with the most controls beneath it.
    main = max(trees, key=lambda t: sum(1 for _ in t.walk()))
    nodes = list(main.walk())

    toolkit = infer_toolkit(facts.modules)

    uia_control = assess_uia(main.handle, view="control")
    uia_raw = assess_uia(main.handle, view="raw")
    msaa = assess_msaa([n.handle for n in nodes[:msaa_sample]])

    try:
        command_line = psutil.Process(pid).cmdline()
    except (psutil.Error, OSError):
        command_line = []

    matched = match_profile(
        uia_verdict=uia_control.verdict,
        msaa_verdict=msaa.verdict,
        window_count=len(nodes),
        toolkit=toolkit.toolkit,
    )

    return ProfileDocument(
        profile_id=_profile_id(facts.executable, facts.bitness),
        matched_profile=matched,
        executable={
            "path": facts.executable,
            "bitness": facts.bitness,
            "wow64": facts.wow64,
        },
        toolkit={
            "inferred": toolkit.toolkit,
            "confidence": toolkit.confidence,
            "evidence": toolkit.evidence,
            "secondary": toolkit.secondary,
        },
        integrity_level=facts.integrity_level,
        dpi={"awareness": facts.dpi_awareness},
        command_line=command_line,
        window_count=len(nodes),
        class_census=class_census(main),
        uia={
            "control_view": {
                "element_count": uia_control.element_count,
                "with_patterns": uia_control.with_patterns,
                "richness": round(uia_control.richness, 4),
                "control_types": uia_control.control_type_histogram,
                "patterns": uia_control.pattern_histogram,
                "max_depth_reached": uia_control.max_depth_reached,
            },
            # The raw view bypasses control-view filtering. Recording both is
            # what lets an empty result be attributed to the provider rather
            # than to the walker.
            "raw_view": {
                "element_count": uia_raw.element_count,
                "with_patterns": uia_raw.with_patterns,
                "max_depth_reached": uia_raw.max_depth_reached,
            },
            "verdict": uia_control.verdict,
            "sample": uia_control.sample,
        },
        msaa={
            "probed": msaa.probed,
            "named": msaa.named,
            "with_default_action": msaa.with_default_action,
            "verdict": msaa.verdict,
            "sample": msaa.sample,
        },
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_profile.py -v`
Expected: PASS — 7 tests

- [ ] **Step 6: Commit**

```bash
git add src/ghostdriver/probe/profile.py src/ghostdriver/probe/runner.py tests/test_profile.py
git commit -m "feat: add capability profile document and phase-1 probe runner"
```

---

## Task 11: Command-line interface

**Files:**
- Create: `src/ghostdriver/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 1–10
- Produces: `main(argv: list[str] | None = None) -> int`; subcommands `list-targets`, `describe`, `find`, `read`, `probe`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli.py`:

```python
import pytest

from ghostdriver.cli import build_parser, main


def test_parser_exposes_every_subcommand():
    parser = build_parser()
    for command in ("list-targets", "describe", "find", "read", "probe"):
        assert parser.parse_args([command] + (
            [] if command == "list-targets" else ["--pid", "1"]
        ))


def test_describe_accepts_depth_and_all_flags():
    args = build_parser().parse_args(
        ["describe", "--pid", "1", "--depth", "7", "--all"]
    )
    assert args.depth == 7
    assert args.all is True


def test_find_requires_a_locator():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["find", "--pid", "1"])


def test_find_parses_locator_expression():
    args = build_parser().parse_args(
        ["find", "--pid", "1", "--locator", 'class=A text="b"']
    )
    assert args.locator == 'class=A text="b"'


def test_no_subcommand_returns_nonzero():
    assert main([]) != 0


def test_unknown_pid_reports_error_not_traceback(capsys):
    code = main(["describe", "--pid", "999999"])
    assert code != 0
    assert "no windows" in capsys.readouterr().err.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ghostdriver.cli'`

- [ ] **Step 3: Implement `src/ghostdriver/cli.py`**

```python
"""Command-line entry point.

Iteration 1 ships a CLI rather than an MCP server so the read path can be
validated against a real target before any protocol layer exists. The MCP
server arrives in Iteration 2 and calls the same functions.
"""

import argparse
import json
import sys

from .model.locator import Locator
from .resolve import resolve
from .summarize import summarize


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ghostdriver", description="Read-only desktop reconnaissance"
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list-targets", help="List processes that own windows")

    describe = sub.add_parser("describe", help="Summarize a target's window tree")
    describe.add_argument("--pid", type=int, required=True)
    describe.add_argument("--depth", type=int, default=5)
    describe.add_argument("--max-nodes", type=int, default=200)
    describe.add_argument(
        "--all", action="store_true", help="Include hidden windows"
    )

    find = sub.add_parser("find", help="Resolve a locator")
    find.add_argument("--pid", type=int, required=True)
    find.add_argument("--locator", required=True)

    read = sub.add_parser("read", help="Read text of matching elements")
    read.add_argument("--pid", type=int, required=True)
    read.add_argument("--locator", required=True)

    probe = sub.add_parser("probe", help="Emit a phase-1 capability profile")
    probe.add_argument("--pid", type=int, required=True)
    probe.add_argument("--out", default=None)

    return parser


def _main_tree(pid: int):
    from .backends.windows.enumerate import enumerate_process

    trees = enumerate_process(pid)
    if not trees:
        print(f"error: pid {pid} has no windows on this desktop", file=sys.stderr)
        return None
    return max(trees, key=lambda t: sum(1 for _ in t.walk()))


def cmd_list_targets() -> int:
    import psutil

    from .backends.windows.enumerate import top_level_windows

    rows = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            handles = top_level_windows(proc.info["pid"])
        except Exception:
            continue
        if handles:
            rows.append((proc.info["pid"], proc.info["name"], len(handles)))

    print(f"{'PID':>8}  {'WINDOWS':>7}  NAME")
    for pid, name, count in sorted(rows):
        print(f"{pid:>8}  {count:>7}  {name}")
    return 0


def cmd_describe(pid: int, depth: int, max_nodes: int, show_all: bool) -> int:
    tree = _main_tree(pid)
    if tree is None:
        return 2
    summary = summarize(
        tree, max_depth=depth, visible_only=not show_all, max_nodes=max_nodes
    )
    print(summary.text)
    print(f"\n{summary.node_count} nodes shown, truncated={summary.truncated}")
    if summary.suggested_locators:
        print("\nSuggested locators:")
        for locator in summary.suggested_locators[:30]:
            print(f"  {locator}")
    return 0


def cmd_find(pid: int, expr: str) -> int:
    tree = _main_tree(pid)
    if tree is None:
        return 2
    matches = resolve(tree, Locator.parse(expr))
    if not matches:
        print("no matches", file=sys.stderr)
        return 1
    for node in matches:
        print(
            f"0x{node.handle:08X}  {node.class_name:<32} "
            f"visible={str(node.visible):<5} rect={node.rect}  {node.text!r}"
        )
    print(f"\n{len(matches)} match(es)")
    return 0


def cmd_read(pid: int, expr: str) -> int:
    tree = _main_tree(pid)
    if tree is None:
        return 2
    matches = resolve(tree, Locator.parse(expr))
    if not matches:
        print("no matches", file=sys.stderr)
        return 1
    for node in matches:
        print(node.text)
    return 0


def cmd_probe(pid: int, out: str | None) -> int:
    from .probe.runner import run_phase1

    try:
        document = run_phase1(pid)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    payload = json.dumps(document.to_dict(), indent=2)
    if out:
        document.save(out)
        print(f"profile written to {out}")
        print(f"matched_profile={document.matched_profile} "
              f"toolkit={document.toolkit.get('inferred')} "
              f"uia={document.uia.get('verdict')} "
              f"windows={document.window_count}")
    else:
        print(payload)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.command:
        print("error: a subcommand is required", file=sys.stderr)
        return 2
    if args.command == "list-targets":
        return cmd_list_targets()
    if args.command == "describe":
        return cmd_describe(args.pid, args.depth, args.max_nodes, args.all)
    if args.command == "find":
        return cmd_find(args.pid, args.locator)
    if args.command == "read":
        return cmd_read(args.pid, args.locator)
    if args.command == "probe":
        return cmd_probe(args.pid, args.out)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: PASS — 6 tests

- [ ] **Step 5: Run the whole suite**

Run: `pytest -v`
Expected: PASS — all tests; Windows-only tests skip on other platforms

- [ ] **Step 6: Commit**

```bash
git add src/ghostdriver/cli.py tests/test_cli.py
git commit -m "feat: add read-only reconnaissance CLI"
```

---

## Task 12: Validation runbook

**Files:**
- Create: `docs/VALIDATION.md`
- Create: `README.md`

**Interfaces:**
- Consumes: the CLI from Task 11
- Produces: documentation only

- [ ] **Step 1: Write `docs/VALIDATION.md`**

````markdown
# Iteration 1 Validation Runbook

Run this in a Windows session against a real Profile L1 application. Every
command here is **read-only**: the tool sends only `WM_GETTEXT` and
`WM_GETTEXTLENGTH`, and never a message that can actuate a control.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest -v
```

All tests must pass before proceeding. The Windows-specific tests drive a
Tk window in a subprocess and need no external application.

## Gate 1 — Target discovery

```bash
ghostdriver list-targets
```

**Pass:** the target application appears with a non-zero window count.

## Gate 2 — Profile correctness

```bash
ghostdriver probe --pid <PID> --out profile.json
```

**Pass:** all of the following are true in `profile.json`.

| Field | Expected for a Profile L1 target |
|---|---|
| `matched_profile` | `L1` |
| `toolkit.inferred` | The target's actual toolkit, with `confidence` `high` or `medium` |
| `toolkit.evidence` | Names the specific signature modules that drove the inference |
| `executable.bitness` | Matches the target's real bitness |
| `dpi.awareness` | `unaware` for a DPI-virtualized target |
| `uia.verdict` | `unusable` if no element supports a pattern |
| `uia.control_view.with_patterns` | Consistent with the verdict |
| `uia.raw_view.element_count` | Recorded, so an empty tree is attributable to the provider rather than the walker |
| `msaa.verdict` | `identification-only` when captions exist but default actions do not |
| `window_count` | Within an order of magnitude of the real control count |
| `class_census` | Top entries are the target's real window classes |

**Fail conditions worth reporting rather than working around:**

- `toolkit.inferred` is `unknown` on an application whose toolkit is known.
  The signature table in `probe/toolkit.py` needs an entry.
- `window_count` is small (under 20) for a large application. Enumeration
  is not reaching child windows.
- `uia.raw_view.element_count` is 0 while `window_count` is large. The UIA
  walker is failing rather than the provider being empty.

## Gate 3 — Scale, the context-budget question

```bash
ghostdriver describe --pid <PID> --depth 5
ghostdriver describe --pid <PID> --depth 5 --max-nodes 60
```

**Pass:**

- Output is legible and bounded — hundreds of lines, not thousands.
- Repeated sibling controls appear as `[N x ClassName]` rather than N lines.
- Captions survive collapsing.
- With `--max-nodes 60`, output ends with an explicit truncation line.
- `Suggested locators:` lists usable `class=... text="..."` expressions.

**This is the scalability gate.** If a real target's tree cannot be
described within a sensible budget, the summarization thresholds in
`summarize.py` need tuning before Iteration 2 builds an MCP tool on it.

## Gate 4 — Locator correctness

Pick a caption from the suggested locators, then:

```bash
ghostdriver find --pid <PID> --locator "class=<Class> text=\"<Caption>\""
```

**Pass:** matches are correct and the handle, class, rect, and text
columns are populated.

Now the discriminating test. Find a caption that appears on more than one
tab page:

```bash
ghostdriver find --pid <PID> --locator "text=\"<Repeated Caption>\" visible=false"
```

This should return several matches. Scope it to one:

```bash
ghostdriver find --pid <PID> --locator "text=\"<Repeated Caption>\" visible=false within..."
```

`within` is not expressible in the shorthand parser, so verify it from a
Python shell instead:

```python
from ghostdriver.backends.windows.enumerate import enumerate_process
from ghostdriver.model.locator import Locator
from ghostdriver.resolve import resolve

tree = max(enumerate_process(PID), key=lambda t: sum(1 for _ in t.walk()))
loc = Locator(
    text="<Repeated Caption>", visible=None,
    within=Locator(class_name="<TabPageClass>", text="<Tab Caption>", visible=None),
)
print([hex(n.handle) for n in resolve(tree, loc)])
```

**Pass:** exactly one handle is returned, and it differs from the handle
returned when scoping to a different tab page.

**This is the capability gate.** Ancestor scoping is what distinguishes
controls that coordinates cannot tell apart.

## Gate 5 — Text reading

```bash
ghostdriver read --pid <PID> --locator "class=<EditClass> visible=true"
```

**Pass:** real field values are returned, and they match what is on screen.
No OCR is involved.

## Gate 6 — Non-interference

While every command above runs, confirm:

- The mouse cursor does not move.
- The foreground window does not change.
- The target's on-screen state does not change.

Any violation is a defect: Iteration 1 sends no message capable of causing
one, so an observed change means an unintended message is being sent.

## Reporting

Record for each gate: pass or fail, the evidence, and anything surprising.
Attach `profile.json`. Note the target only by its technology profile —
toolkit, bitness, control classes — never by product or vendor name.
````

- [ ] **Step 2: Write `README.md`**

````markdown
# ghostdriver

An MCP server for driving desktop applications — for automated testing and
unattended tasks — without contending with a human working on the same
machine.

## Status

Iteration 1: read-only reconnaissance. A CLI that enumerates a target's
window tree, resolves declarative locators, reads control text, and emits a
capability profile. No actuation. The MCP server arrives in Iteration 2.

See `docs/superpowers/specs/2026-09-01-desktop-automation-mcp-design.md`.

## Why

Most desktop automation assumes UI Automation works. For a large class of
enterprise line-of-business software it does not: applications built on
pre-UIA toolkits expose a tree in which every element is a `Pane` and no
element supports any pattern. Those applications remain drivable through
window messages, and that tier is what this tool implements.

## Install

```bash
pip install -e ".[dev]"
pytest
```

## Use

```bash
ghostdriver list-targets
ghostdriver probe --pid 1234 --out profile.json
ghostdriver describe --pid 1234 --depth 5
ghostdriver find --pid 1234 --locator 'class=VendorButton text="Expand All"'
ghostdriver read --pid 1234 --locator 'class=VendorEdit visible=true'
```

## Design notes

- **Locators, not handles.** The OS recycles window handles and voids them
  when a process exits, so elements are re-resolved from a declarative
  query on every call.
- **Input-shaped messages, not semantic ones.** Semantic messages such as
  `BM_CLICK` are implemented by a specific window class and are discarded
  by anything else. Input-shaped messages only assume the toolkit handles
  mouse and keyboard input.
- **Pure logic separated from platform calls.** The Windows backend
  produces plain `WindowNode` trees; matching, summarization, and inference
  operate on those and are testable on any platform.
````

- [ ] **Step 3: Commit**

```bash
git add README.md docs/VALIDATION.md
git commit -m "docs: add validation runbook and README"
```

---

## Self-Review Notes

**Spec coverage.** Iteration 1 of spec §11 has four items: core model (Task 1), Windows enumeration and locator resolution (Tasks 2, 5), `read` via `WM_GETTEXT` (Task 6), and probe phase 1 (Tasks 4, 7–10). Spec §6.1's `describe` budgeting is Task 3. Spec §5.1's read-only probe constraint is enforced by the Global Constraints and verified at Gate 6. Spec §9's `ActionResult` is Task 1. Spec §4.4's postcondition rule is encoded in `ActionResult.__post_init__`; the verbs that consume it arrive in Iteration 3.

**Deliberately deferred within Iteration 1.** `Locator.role` matches nothing because role mapping requires a curated profile (Iteration 2). `Locator.parse` has no `within` syntax; the runbook uses the Python API for it, and shorthand syntax is an Iteration 2 concern once the MCP tool schema exists.

**Known rough edge.** `assess_msaa` probes handles directly rather than walking, which is correct for count honesty but means it cannot see child elements that exist only in the MSAA tree. For Profile L1 targets that tree is fabricated chrome, so nothing of value is lost; for a target where MSAA is genuinely richer than the window tree, this under-reports. Revisit if a target's `msaa.verdict` disagrees with observation.
