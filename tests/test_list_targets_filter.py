"""`list_targets(name=, visible_only=)` (#254). Platform-neutral by
construction: the backend and the process list are stood in, so what is
checked is the filtering, not any one desktop."""

from types import SimpleNamespace

import psutil
import pytest

import ghostdriver.backends as backends
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox

#: pid -> (process name, {window handle: visible})
DESKTOP = {
    101: ("olk.exe", {1: True, 2: False}),
    102: ("VendorApp.Exe", {3: True}),
    103: ("tray-agent.exe", {4: False}),
}


class Process:
    def __init__(self, pid):
        self.info = {"pid": pid, "name": DESKTOP[pid][0]}


@pytest.fixture
def box(monkeypatch):
    visible = {h: v for _, windows in DESKTOP.values() for h, v in windows.items()}
    fake = SimpleNamespace(
        winapi=SimpleNamespace(class_name=lambda h: "Window",
                               is_visible_style=lambda h: visible[h]),
        top_level_windows=lambda pid: list(DESKTOP[pid][1]),
        parent_map=lambda: {},
        application_name=lambda pid: None,
    )
    monkeypatch.setattr(backends, "current", lambda: fake)
    monkeypatch.setattr(psutil, "process_iter",
                        lambda attrs=None: [Process(pid) for pid in DESKTOP])
    return Toolbox(sessions=SessionManager())


def names(result):
    return sorted(t["name"] for t in result["targets"])


def test_unfiltered_is_the_whole_list(box):
    result = box.list_targets()
    assert names(result) == ["VendorApp.Exe", "olk.exe", "tray-agent.exe"]
    assert "filter" not in result


def test_name_is_a_case_insensitive_glob(box):
    result = box.list_targets(name="OLK*")
    assert names(result) == ["olk.exe"]
    assert result["filter"] == {"name": "OLK*", "visible_only": False}
    assert names(box.list_targets(name="vendorapp.exe")) == ["VendorApp.Exe"]


def test_visible_only_drops_processes_with_nothing_on_screen(box):
    assert names(box.list_targets(visible_only=True)) == ["VendorApp.Exe", "olk.exe"]
