"""On a Wayland operator desktop, window state comes from AT-SPI (issue 221).

D#215 refused X-sourced state there, which also refused every action: the
actuator will not act on a desktop it cannot observe. Measured on linux-host-a's
real GNOME 50 session (W1-W4): `STATE_ACTIVE` tracks focus for native and
XWayland clients alike, a modal is a frame with `STATE_MODAL` and no
relation to its owner, and a minimized frame looks exactly like a shown
one. These pin the shapes built from that, against fakes, so they run on
any platform.
"""

import pytest

# Imported in the fixture, not here: a test module may not bind a backend
# package at import time (test_structure.py).
modality = tree = None


class Frame:
    def __init__(self, handle, name, *states):
        self.handle = handle
        self.name = name
        self.states = frozenset(states)


@pytest.fixture
def wayland(monkeypatch):
    global modality, tree
    from ghostdriver.backends.linux import desktop_claim, modality, tree
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(desktop_claim, "_environments", {})


def _frames(monkeypatch, by_pid, active=None):
    monkeypatch.setattr(tree, "frames", lambda pid: by_pid.get(pid, []))
    monkeypatch.setattr(tree, "active_frame", lambda: active)


def test_top_level_state_comes_from_the_frames(wayland, monkeypatch):
    _frames(monkeypatch, {7: [Frame(101, "Main", "SHOWING"),
                              Frame(102, "Confirm", "SHOWING", "MODAL")]})
    state = modality.top_level_state(7)
    assert [(w.handle, w.text, w.modal) for w in state] == [
        (101, "Main", False), (102, "Confirm", True)]


def test_a_modal_is_reported_as_holding_the_application(wayland, monkeypatch):
    """No owner relation exists on Wayland (W2), so the modal is attributed
    to the application's first frame: reported, not dropped."""
    from ghostdriver.modality import find_modal_blocks
    _frames(monkeypatch, {7: [Frame(101, "Main", "SHOWING"),
                              Frame(102, "Confirm", "SHOWING", "MODAL")]})
    blocks, _ = find_modal_blocks(modality.top_level_state(7))
    assert [b.dialog.text for b in blocks] == ["Confirm"]


def test_the_snapshot_names_the_target_frame_that_holds_the_front(wayland, monkeypatch):
    _frames(monkeypatch, {7: [Frame(101, "Main", "SHOWING", "ACTIVE")]}, active=(7, 101))
    snap = modality.snapshot(7)
    assert snap.alive is True
    assert snap.windows == {101: "Main"}
    assert snap.foreground == 101


def test_another_application_at_the_front_is_not_the_target(wayland, monkeypatch):
    """A stable value that is not one of the target's handles, so moving
    from one other application to another is a change, and never reads as
    the target taking the front."""
    _frames(monkeypatch, {7: [Frame(101, "Main", "SHOWING")]}, active=(9, 555))
    snap = modality.snapshot(7)
    assert snap.foreground not in snap.windows
    assert snap.foreground != 0


def test_a_target_with_no_frames_is_gone(wayland, monkeypatch):
    _frames(monkeypatch, {})
    assert modality.snapshot(7).alive is False


def test_a_control_under_a_modal_is_blocked_by_it(wayland, monkeypatch):
    _frames(monkeypatch, {7: [Frame(101, "Main", "SHOWING"),
                              Frame(102, "Confirm", "SHOWING", "MODAL")]})
    monkeypatch.setattr(modality, "_pid_of_handle", lambda handle: 7)
    monkeypatch.setattr(modality, "_frame_handle_of", lambda handle: 101)
    assert modality.blocking_ancestor(5000) == 102


def test_a_control_in_the_modal_itself_is_not_blocked(wayland, monkeypatch):
    _frames(monkeypatch, {7: [Frame(101, "Main", "SHOWING"),
                              Frame(102, "Confirm", "SHOWING", "MODAL")]})
    monkeypatch.setattr(modality, "_pid_of_handle", lambda handle: 7)
    monkeypatch.setattr(modality, "_frame_handle_of", lambda handle: 102)
    assert modality.blocking_ancestor(5001) is None


def test_no_modal_no_block(wayland, monkeypatch):
    _frames(monkeypatch, {7: [Frame(101, "Main", "SHOWING")]})
    monkeypatch.setattr(modality, "_pid_of_handle", lambda handle: 7)
    monkeypatch.setattr(modality, "_frame_handle_of", lambda handle: 101)
    assert modality.blocking_ancestor(5000) is None


def test_the_tool_layer_can_aim_at_a_linux_control(monkeypatch):
    """`click` and `set_value` aim through `winapi.client_centre` /
    `client_to_screen` before acting (the denied-region check), and the Linux
    shim refused both -- so neither tool worked on any Linux desktop (found
    driving linux-host-a, #221). The answers are in AT-SPI's extents, which are the
    space the element rects and the denied regions are already in."""
    from ghostdriver.backends.linux import tree, winapi
    monkeypatch.setattr(tree, "_accessible", lambda handle: object())
    monkeypatch.setattr(tree, "_rect", lambda node: (10, 20, 110, 70))
    assert winapi.client_centre(7) == (50, 25)
    assert winapi.client_to_screen(7, (5, 5)) == (15, 25)
    assert winapi.screen_to_client(7, (15, 25)) == (5, 5)
