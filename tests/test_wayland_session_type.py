"""Which display server a claimant's desktop runs (issue 215).

Platform-neutral by construction: the subject reads an environment mapping
and the claim registry, both injected here, so this runs on Windows too.
"""

import pytest

from ghostdriver.backends import UnsupportedPlatform

# Imported in the fixture, not here: a test module may not bind a backend
# package at import time (test_structure.py).
desktop_claim = session_type = None


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch):
    global desktop_claim, session_type
    from ghostdriver.backends.linux import desktop_claim, session_type
    monkeypatch.setattr(desktop_claim, "_environments", {})


def test_xdg_session_type_wayland_is_wayland():
    assert session_type.display_server(
        environ={"XDG_SESSION_TYPE": "wayland"}) == "wayland"


def test_xdg_session_type_wins_over_a_stray_wayland_display():
    # A nested Wayland compositor started from an X session exports
    # WAYLAND_DISPLAY to its children; the session is still X11.
    assert session_type.display_server(environ={
        "XDG_SESSION_TYPE": "x11", "WAYLAND_DISPLAY": "wayland-1"}) == "x11"


def test_wayland_display_alone_is_wayland():
    assert session_type.display_server(
        environ={"WAYLAND_DISPLAY": "wayland-0"}) == "wayland"


def test_nothing_set_is_x11():
    assert session_type.display_server(environ={}) == "x11"


def test_a_hidden_desktop_answers_from_its_own_registration():
    desktop_claim.register("hd-test", DISPLAY=":99")
    with desktop_claim.desktop("hd-test"):
        assert session_type.display_server(
            environ={"XDG_SESSION_TYPE": "wayland"}) == "x11"


def test_a_wayland_hidden_desktop_is_wayland():
    desktop_claim.register("hd-wl", WAYLAND_DISPLAY="gd-wl-1")
    with desktop_claim.desktop("hd-wl"):
        assert session_type.display_server(environ={}) == "wayland"


def test_x11_only_is_an_unsupported_platform():
    # So the tool wrapper turns it into denied_by_environment (#213).
    assert issubclass(session_type.X11Only, UnsupportedPlatform)


def test_require_x11_names_what_refused(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    with pytest.raises(session_type.X11Only, match="the interference watch"):
        session_type.require_x11("the interference watch")


def test_require_x11_is_silent_on_x11(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    session_type.require_x11("anything")
