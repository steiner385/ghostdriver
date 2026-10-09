"""The minimized watch, as the tool layer uses it (issue 218).

`tools/lifecycle.py` builds `MinimizedWatch(pid, family=...)` and reads
`start`, `stop`, `drain`, `events`, `put_away`, `main_hwnd` and
`suspended_reason` off it -- the Windows class's shape. The Linux class took
`(pid, main_xid)` instead, so `attach(isolation="minimized")` raised
`TypeError` on every Linux desktop before a watch existed.

Platform-neutral: the Linux class is built and started against fakes, so
this runs on Windows too, where the drift would otherwise go unseen. The
Windows class cannot be imported off Windows, so the contract is the list
the tool layer reads, stated once here.
"""

import pytest

#: Everything the tool layer touches on a minimized watch.
TOOL_LAYER_USES = ("start", "stop", "drain", "events", "put_away",
                   "main_hwnd", "suspended_reason")


@pytest.fixture
def x11(monkeypatch):
    from ghostdriver.backends.linux import desktop_claim
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setattr(desktop_claim, "_environments", {})


def test_the_linux_watch_is_built_the_way_attach_builds_it(x11):
    from ghostdriver.backends.linux.isolate import MinimizedWatch

    watch = MinimizedWatch(1234, family=lambda: [1234])

    missing = [name for name in TOOL_LAYER_USES if not hasattr(watch, name)]
    assert missing == []


def test_start_finds_the_main_window_itself_and_says_it_put_it_away(x11, monkeypatch):
    from ghostdriver.backends.linux import display, isolate, tree

    class Node:
        handle = 1073741824

    hidden = set()
    monkeypatch.setattr(tree, "enumerate_process", lambda pid: [Node()])
    monkeypatch.setattr(isolate, "select_main_tree", lambda trees: trees[0])
    monkeypatch.setattr(tree, "frame_xid_of", lambda handle: 0x500 if handle == Node.handle else None)
    monkeypatch.setattr(display, "exists", lambda xid: True)
    monkeypatch.setattr(display, "is_hidden", lambda xid: xid in hidden)
    monkeypatch.setattr(display, "iconify", lambda xid: hidden.add(xid))
    monkeypatch.setattr(isolate, "watch_once", lambda pid, xid, dog, family=None: None)

    watch = isolate.MinimizedWatch(1234, family=lambda: [1234])
    watch.start()
    try:
        assert watch.main_hwnd == Node.handle  # what reads lock onto (core.py)
        assert watch.main_xid == 0x500
        assert watch.put_away is True
        assert watch.drain() == []
        assert watch.suspended_reason == ""
    finally:
        watch.stop()


def test_a_main_window_with_no_x_window_behind_it_is_a_watch_error(x11, monkeypatch):
    from ghostdriver.backends.linux import isolate, tree

    class Node:
        handle = 7

    monkeypatch.setattr(tree, "enumerate_process", lambda pid: [Node()])
    monkeypatch.setattr(isolate, "select_main_tree", lambda trees: trees[0])
    monkeypatch.setattr(tree, "frame_xid_of", lambda handle: None)

    watch = isolate.MinimizedWatch(1234)
    with pytest.raises(isolate.WatchError, match="X window"):
        watch.start()
