"""The clipboard is the person's (D70).

Setting text never touches it: the whole-value rung inserts through the
control's own edit path. The one route that must write it -- a grid's
own Copy -- is off unless the session was attached with clipboard=true,
and then every format is saved and put back. None of these tests writes
the clipboard; the sequence number proves it.
"""

import ctypes
import json
import subprocess
import sys
import time

import psutil
import pytest

from ghostdriver.consent import ConsentStore
from ghostdriver.policy import ConsentSource, Tier
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox
from tests.conftest import on_windows

pytestmark = on_windows

GRID = "class=GhostFixtureDataGrid"
EDIT = "class=GhostFixturePlainEdit"


def sequence() -> int:
    return ctypes.windll.user32.GetClipboardSequenceNumber()


def untouched_by(action, attempts: int = 3) -> bool:
    """Run `action` and report whether the clipboard sequence number stayed
    put. The person may copy something in the window, which moves it too, so
    a moved number is retried: a person copying in three windows in a row is
    not the tool."""
    for _ in range(attempts):
        before = sequence()
        action()
        if sequence() == before:
            return True
    return False

def start(*args):
    proc = subprocess.Popen([sys.executable, "-m", "tests.fixtureapp", *args],
                            stdout=subprocess.PIPE, text=True)
    handles = json.loads(proc.stdout.readline())
    time.sleep(0.4)
    return proc, handles


def stop(proc, handles):
    if handles["pid"] != proc.pid:
        try:
            psutil.Process(handles["pid"]).terminate()
        except psutil.Error:
            pass
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def app():
    proc, handles = start()
    yield handles
    stop(proc, handles)


def session_for(pid, tier=Tier.INTERACTIVE, clipboard=False):
    box = Toolbox(SessionManager(store=ConsentStore(None)))
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    return box, box.sessions.attach(pid, command_line=["fixtureapp"], tier=tier,
                                    clipboard=clipboard).session_id


def test_the_whole_value_rung_inserts_without_the_clipboard(app):
    from ghostdriver.backends.windows.input import insert_text
    from ghostdriver.backends.windows.text import read_window_text

    def insert():
        assert insert_text(app["plain_edit"], "INSERTED-0001")
        time.sleep(0.2)

    assert untouched_by(insert), "the clipboard was not touched"
    assert read_window_text(app["plain_edit"]) == "INSERTED-0001"


def test_set_value_never_touches_the_clipboard(app):
    box, session = session_for(app["pid"])
    results = []

    assert untouched_by(lambda: results.append(box.set_value(session, EDIT, "typed-and-clean")))

    assert results[-1]["ok"] and results[-1]["route"] == "typed"


def test_the_insert_rung_is_named_when_typing_falls_short(app):
    """The fixture's plain edit refuses past twenty characters when typed
    (no ES_AUTOHSCROLL); the insert rung then delivers the value whole and
    the read-back decides. Either way, the clipboard is untouched."""
    box, session = session_for(app["pid"])
    results = []

    assert untouched_by(lambda: results.append(box.set_value(session, EDIT, "x" * 40)))

    result = results[-1]
    assert "inserted" in (result.get("route") or "") or not result["ok"]
    assert "pasting" not in json.dumps(result)


def test_probe_grid_does_not_copy_unless_the_session_allows_it(app):
    box, session = session_for(app["pid"], tier=Tier.FULL)
    reports = []

    assert untouched_by(lambda: reports.append(box.probe_grid(session, GRID, allow_clipboard=True)))

    report = reports[-1]
    assert report["ok"] and report["grid_strategy"] == "unknown"
    assert "clipboard=true" in report["clipboard"]


def test_grid_seek_is_refused_unless_the_session_allows_the_clipboard(app):
    box, session = session_for(app["pid"], tier=Tier.FULL)

    refused = box.grid_seek(session, GRID)

    assert not refused["ok"] and "clipboard=true" in refused["error"]["message"]


def test_attach_records_the_choice(app):
    box, session = session_for(app["pid"], clipboard=True)

    assert box.sessions.get(session).clipboard is True
    other, plain = session_for(app["pid"])
    assert other.sessions.get(plain).clipboard is False


def test_a_snapshot_round_trips_every_global_format():
    """Pure: the save/restore pair, on whatever the clipboard holds now, put
    back exactly. Reads then writes the same bytes; the person sees no change."""
    from ghostdriver.backends.windows.grid import restore_clipboard, snapshot_clipboard

    before = snapshot_clipboard()
    restored = restore_clipboard(before)
    after = snapshot_clipboard()

    assert restored == len(before["formats"])
    assert [f for f, _ in after["formats"]] == [f for f, _ in before["formats"]]
    assert [d for _, d in after["formats"]] == [d for _, d in before["formats"]]


# --- a copy answered after the route gave up (#186) ----------------------------

def test_a_late_answer_owned_by_the_target_is_put_back():
    from ghostdriver.backends.windows.grid import drain_late_copies, watch_for_a_late_answer

    drain_late_copies()
    seqs = iter([5, 5, 6])
    restored = []
    note = watch_for_a_late_answer(
        42, {"formats": ["prior"]}, 5, watch_s=1.0,
        sequence=lambda: next(seqs), owner_pid=lambda: 42,
        snapshot=lambda: {"formats": ["other"]}, restore=restored.append,
        sleep=lambda s: None)

    assert restored == [{"formats": ["prior"]}]
    assert "put back" in note and drain_late_copies() == [note]


def test_a_change_the_target_does_not_own_is_left_alone_and_becomes_the_new_before():
    """The person copied something while the late answer was pending: it is
    theirs, and it is what a late answer would now destroy."""
    from ghostdriver.backends.windows.grid import drain_late_copies, watch_for_a_late_answer

    drain_late_copies()
    seqs = iter([6, 7])            # the person's copy, then the target's late answer
    owners = iter([999, 42])
    restored = []
    watch_for_a_late_answer(
        42, {"formats": ["prior"]}, 5, watch_s=1.0,
        sequence=lambda: next(seqs), owner_pid=lambda: next(owners),
        snapshot=lambda: {"formats": ["the person's copy"]}, restore=restored.append,
        sleep=lambda s: None)

    assert restored == [{"formats": ["the person's copy"]}], "their copy is what is put back"


def test_nothing_arriving_in_time_records_nothing():
    from ghostdriver.backends.windows.grid import drain_late_copies, watch_for_a_late_answer

    drain_late_copies()
    clock = iter(x * 0.5 for x in range(100))
    assert watch_for_a_late_answer(
        42, {}, 5, watch_s=1.0, sequence=lambda: 5, owner_pid=lambda: 0,
        snapshot=dict, restore=lambda p: None, sleep=lambda s: None,
        now=lambda: next(clock)) is None
    assert drain_late_copies() == []


def test_a_grid_that_answers_after_the_timeout_does_not_keep_the_clipboard(monkeypatch):
    """End to end against a fixture grid that copies 600 ms late, with the
    route giving up at 200 ms: the rows land after the route returned, and
    the clipboard ends up holding what it held before."""
    from ghostdriver.backends.windows import grid
    from ghostdriver.backends.windows.enumerate import enumerate_process

    monkeypatch.setattr(grid, "COPY_TIMEOUT_S", 0.2)
    monkeypatch.setattr(grid, "LATE_COPY_WATCH_S", 4.0)
    proc, handles = start("--grid-copy-after", "600")
    try:
        node = next(n for tree in enumerate_process(handles["pid"]) for n in tree.walk()
                    if n.class_name == "GhostFixtureDataGrid")
        grid.drain_late_copies()
        before = grid.snapshot_clipboard()

        result = grid.copy_route(node, want_text=True)

        assert not result.worked and "late answer" in result.detail
        deadline = time.monotonic() + 4.0
        late: list[str] = []
        while not late and time.monotonic() < deadline:
            late = grid.drain_late_copies()
            time.sleep(0.05)
        after = grid.snapshot_clipboard()

        assert late and "put back" in late[0], late
        assert [d for _, d in after["formats"]] == [d for _, d in before["formats"]]
    finally:
        stop(proc, handles)
