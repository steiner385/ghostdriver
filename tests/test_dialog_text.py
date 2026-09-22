"""A dialog's text, per control and capped (#196). Backend-free: the
window tree and the text reader are stood in for."""

from types import SimpleNamespace

import pytest

from ghostdriver.tools.dialogtext import DIALOG_CONTROL_CHARS, dialog_controls, join_dialog_text

TRACE = "java.lang.RuntimeException: boom\n" + "\n".join(f"  at frame{i}()" for i in range(300))


@pytest.fixture
def dialog(monkeypatch):
    children = {0x1: [0x10, 0x11, 0x12], 0x10: [], 0x11: [], 0x12: []}
    texts = {0x10: "Error", 0x11: "Message: the plan already exists", 0x12: TRACE}
    rects = {0x10: (0, 0, 100, 20), 0x11: (0, 30, 400, 50), 0x12: (0, 60, 400, 400)}
    classes = {0x10: "TLabel", 0x11: "TLabel", 0x12: "TMemo"}
    winapi = SimpleNamespace(window_rect=lambda h: rects[h], class_name=lambda h: classes[h])
    monkeypatch.setattr("ghostdriver.backends.current", lambda: SimpleNamespace(
        direct_children=lambda h: children.get(h, []),
        read_window_text=lambda h: texts.get(h), winapi=winapi))


def test_each_control_is_reported_and_the_long_one_is_cut(dialog):
    controls = dialog_controls(0x1)

    assert [c["class"] for c in controls] == ["TLabel", "TLabel", "TMemo"]
    assert controls[1]["text"] == "Message: the plan already exists" and "cut" not in controls[1]
    memo = controls[2]
    assert memo["chars"] == len(TRACE)
    assert len(memo["text"]) == DIALOG_CONTROL_CHARS and memo["cut"] == len(TRACE) - DIALOG_CONTROL_CHARS
    assert memo["text"].startswith("java.lang.RuntimeException: boom")


def test_full_text_returns_everything(dialog):
    controls = dialog_controls(0x1, per_control=None)
    assert controls[2]["text"] == TRACE and "cut" not in controls[2]


def test_the_joined_text_is_built_from_the_capped_pieces(dialog):
    joined = join_dialog_text(dialog_controls(0x1))
    assert joined.startswith("Error\nMessage: the plan already exists\njava.lang")
    assert joined.endswith(" ...") and len(joined) < 800
