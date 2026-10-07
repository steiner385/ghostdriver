"""describe and the summarizer at the size the gate was written for (#28,
#210): 108 to 20,000 windows, on trees shaped like a business application.

Synthetic, so it runs anywhere and proves the *bounds*; whether a real
target's tree has this shape is what the real-target gate (#28) is for.
"""

import random
from types import SimpleNamespace

import pytest

from ghostdriver.model.window import WindowNode
from ghostdriver.operator import ENV_VAR
from ghostdriver.session import SessionManager
from ghostdriver.summarize import summarize
from ghostdriver.tools import Toolbox
from ghostdriver.tools.discovery import MAX_SUGGESTED


def node(handle, cls, text="", children=()):
    return WindowNode(handle=handle, class_name=cls, text=text, rect=(0, 0, 10, 10),
                      visible=True, enabled=True, pid=1, children=tuple(children))


def application(total: int, *, captioned: float = 0.5, seed: int = 7) -> WindowNode:
    """A shell of forms of panels of controls, `total` windows in all."""
    rng = random.Random(seed)
    handle = [1]

    def new():
        handle[0] += 1
        return handle[0]

    classes = ["Panel", "Edit", "Button", "Grid", "Label", "Combo", "Toolbar", "Pager"]
    forms, made = [], 1
    while made < total:
        panels = []
        for _ in range(rng.randint(3, 8)):
            kids = []
            for _ in range(rng.randint(5, 40)):
                if made >= total:
                    break
                cls = rng.choice(classes)
                kids.append(node(new(), cls, f"{cls} {made}" if rng.random() < captioned else ""))
                made += 1
            panels.append(node(new(), "Panel", children=kids))
            made += 1
            if made >= total:
                break
        forms.append(node(new(), "Form", f"View {len(forms)}", children=panels))
        made += 1
    return node(1, "Shell", "Main", children=forms)


def count(tree: WindowNode) -> int:
    return sum(1 for _ in tree.walk())


#: What one describe may cost a caller at any target size: about a thousand
#: tokens of tree. Measured: ~40 tokens at 1,100 windows, ~560 at 20,000.
BUDGET_CHARS = 4000


@pytest.mark.parametrize("total", [108, 1100, 5000, 20000])
@pytest.mark.parametrize("captioned", [0.1, 1.0])
def test_the_summary_stays_inside_the_budget_and_says_what_it_hid(total, captioned):
    tree = application(total, captioned=captioned)

    summary = summarize(tree)

    assert len(summary.text) <= BUDGET_CHARS, len(summary.text)
    assert summary.truncated is True
    assert summary.elided_nodes > 0 and "descendants not shown" in summary.text
    assert summary.elided_nodes < count(tree), "what was hidden is a count of real windows"


@pytest.fixture
def box(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "ops"))
    box = Toolbox(SessionManager())
    session = SimpleNamespace(session_id="s", pid=1, run=lambda f: f())
    monkeypatch.setattr(box.sessions, "authorize", lambda sid, tool: session)
    monkeypatch.setattr(box, "_blocking", lambda s: [])
    monkeypatch.setattr("ghostdriver.tools.discovery.current",
                        lambda: SimpleNamespace(winapi=SimpleNamespace(is_hung=lambda h: False)))
    return box


def test_a_collapsed_group_says_how_to_get_back_in(box, monkeypatch):
    tree = application(1100)
    monkeypatch.setattr(box, "_trees", lambda session, all_windows: [tree])

    first = box.describe("s")

    assert first["truncated"] and first["elided_by_collapsing"] > 1000
    assert "within=" in first["expand_hint"]
    assert 'class=Form text="View 3"' in first["suggested_locators"]


def test_within_roots_the_summary_at_one_window(box, monkeypatch):
    tree = application(1100)
    monkeypatch.setattr(box, "_trees", lambda session, all_windows: [tree])

    inside = box.describe("s", within='class=Form text="View 3"')

    assert inside["ok"] and inside["within"] == 'class=Form text="View 3"'
    text = inside["windows"][0]["tree"]
    assert text.startswith('Form "View 3"')
    assert "View 2" not in text and "Panel" in text
    assert len(text) <= BUDGET_CHARS


def test_within_must_name_exactly_one_window(box, monkeypatch):
    tree = application(1100)
    monkeypatch.setattr(box, "_trees", lambda session, all_windows: [tree])

    many = box.describe("s", within="class=Form")
    none = box.describe("s", within="class=NoSuchClass")

    assert many["error"]["kind"] == "ambiguous" and "exactly one" in many["error"]["message"]
    assert none["error"]["kind"] == "not_found"


def test_the_locator_cap_says_how_many_it_left_out(box, monkeypatch):
    forms = [node(10 + i, "Form", f"View {i}") for i in range(MAX_SUGGESTED + 12)]
    monkeypatch.setattr(box, "_trees",
                        lambda session, all_windows: [node(1, "Shell", "Main", children=forms)])

    result = box.describe("s")

    assert len(result["suggested_locators"]) == MAX_SUGGESTED
    assert result["suggested_locators_omitted"] == 13   # the shell's own is the 43rd


def test_a_small_tree_carries_neither_note(box, monkeypatch):
    small = node(1, "Shell", "Main", children=[node(2, "Edit", "Name"), node(3, "Button", "Ok")])
    monkeypatch.setattr(box, "_trees", lambda session, all_windows: [small])
    result = box.describe("s")
    assert "expand_hint" not in result and "suggested_locators_omitted" not in result
