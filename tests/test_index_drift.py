"""index= drift (#198): the same locator, in the same session, picking a
different control than before while the earlier one is still there.
Backend-free: the window trees are built by hand."""

from types import SimpleNamespace

import pytest

from ghostdriver.model.window import WindowNode
from ghostdriver.operator import ENV_VAR
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox


def edit(handle):
    return WindowNode(handle=handle, class_name="TEdit", text="", rect=(0, handle, 100, handle + 20),
                      visible=True, enabled=True, pid=1)


def form(*handles):
    return WindowNode(handle=0x1, class_name="TForm", text="Plan", rect=(0, 0, 500, 500),
                      visible=True, enabled=True, pid=1, children=tuple(edit(h) for h in handles))


@pytest.fixture
def box(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "ops"))
    return Toolbox(SessionManager())


SESSION = SimpleNamespace(session_id="s")


def test_a_reordered_sibling_list_is_reported_once(box, monkeypatch):
    trees = {"now": [form(0x10, 0x20)]}
    monkeypatch.setattr(box, "_trees", lambda session, all_windows: trees["now"])

    first = box._resolve(SESSION, "class=TEdit index=0", False)
    assert first[0].handle == 0x10 and box._drift_note(SESSION, "class=TEdit index=0") is None

    trees["now"] = [form(0x20, 0x10)]          # the toolkit moved the focused field
    second = box._resolve(SESSION, "class=TEdit index=0", False)
    assert second[0].handle == 0x20
    note = box._drift_note(SESSION, "class=TEdit index=0")
    assert note and "0x00000010 then, 0x00000020 now" in note and "region=" in note
    assert box._drift_note(SESSION, "class=TEdit index=0") is None, "said once"


def test_a_control_that_went_away_is_not_drift(box, monkeypatch):
    trees = {"now": [form(0x10, 0x20)]}
    monkeypatch.setattr(box, "_trees", lambda session, all_windows: trees["now"])
    box._resolve(SESSION, "class=TEdit index=0", False)
    trees["now"] = [form(0x20)]                 # the first field is gone, not moved
    box._resolve(SESSION, "class=TEdit index=0", False)
    assert box._drift_note(SESSION, "class=TEdit index=0") is None


def test_a_locator_without_index_is_never_drift(box, monkeypatch):
    trees = {"now": [form(0x10)]}
    monkeypatch.setattr(box, "_trees", lambda session, all_windows: trees["now"])
    box._resolve(SESSION, "class=TEdit", False)
    trees["now"] = [form(0x20)]
    box._resolve(SESSION, "class=TEdit", False)
    assert box._drift_note(SESSION, "class=TEdit") is None
