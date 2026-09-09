"""Dev hot reload (D68): implementation re-imported on change, live state kept.

The reloader is proven on a scratch package in a temp directory rather
than by editing this repository's own sources under a running test. The
LiveToolbox is proven to pass through outside dev mode and to survive a
no-change check inside it.
"""

import importlib
import os
import sys
import textwrap
import time
from types import SimpleNamespace

import pytest

from ghostdriver.devreload import HotReloader, LiveToolbox


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    """A package with one reloadable module and one stable one."""
    pkg = tmp_path / "hotpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "impl.py").write_text("def answer():\n    return 1\n", encoding="utf-8")
    (pkg / "state.py").write_text("class Store:\n    pass\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in [n for n in sys.modules if n == "hotpkg" or n.startswith("hotpkg.")]:
        del sys.modules[name]
    yield pkg
    for name in [n for n in sys.modules if n == "hotpkg" or n.startswith("hotpkg.")]:
        del sys.modules[name]


def bump(path, text):
    """Write, and make sure the mtime moves even on a coarse clock."""
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    later = time.time() + 2
    os.utime(path, (later, later))


def reloader_for(pkg):
    def build():
        impl = importlib.import_module("hotpkg.impl")
        return SimpleNamespace(answer=impl.answer, keep={"opened": 1})

    return HotReloader("hotpkg", pkg, build=build,
                       stable=frozenset({"hotpkg", "hotpkg.state"}), carry=("keep",))


def test_an_edit_to_an_implementation_module_takes_effect_on_the_next_check(scratch):
    reloader = reloader_for(scratch)
    assert reloader.current.answer() == 1
    kept = reloader.current.keep

    bump(scratch / "impl.py", "def answer():\n    return 2\n")
    event = reloader.check(force=True)

    assert event and event["reloaded"] == ["hotpkg.impl"] and event["generation"] == 1
    assert reloader.current.answer() == 2
    assert reloader.current.keep is kept, "live state carried to the new generation"


def test_an_edit_that_does_not_import_keeps_the_previous_generation(scratch):
    reloader = reloader_for(scratch)

    bump(scratch / "impl.py", "def answer(:\n    return 3\n")  # a typo, mid-save
    event = reloader.check(force=True)

    assert event and "error" in event and "SyntaxError" in event["error"]
    assert reloader.current.answer() == 1, "the old generation still answers"
    assert importlib.import_module("hotpkg.impl").answer() == 1, "sys.modules restored"


def test_an_edit_to_a_stable_module_asks_for_a_reconnect_and_reloads_nothing(scratch):
    reloader = reloader_for(scratch)

    bump(scratch / "state.py", "class Store:\n    kind = 2\n")
    event = reloader.check(force=True)

    assert event and event["needs_reconnect"] == ["hotpkg.state"]
    assert "reloaded" not in event and reloader.generation == 0


def test_no_change_means_no_event(scratch):
    reloader = reloader_for(scratch)

    assert reloader.check(force=True) is None
    assert reloader.take_events() == []


def test_events_are_taken_once(scratch):
    reloader = reloader_for(scratch)
    bump(scratch / "impl.py", "def answer():\n    return 5\n")
    reloader.check(force=True)

    first, second = reloader.take_events(), reloader.take_events()

    assert len(first) == 1 and second == []


# --- the live toolbox --------------------------------------------------------------------

def test_outside_dev_mode_the_live_toolbox_is_a_pass_through():
    from ghostdriver.consent import ConsentStore
    from ghostdriver.session import SessionManager

    live = LiveToolbox(SessionManager(store=ConsentStore(None)), dev=False)

    assert live.dev is False
    assert live.describe("nope")["error"]["kind"] == "not_found"
    assert "dev_reload" not in live.describe("nope")


def test_in_dev_mode_a_call_passes_through_and_a_quiet_check_adds_nothing():
    from ghostdriver.consent import ConsentStore
    from ghostdriver.session import SessionManager

    live = LiveToolbox(SessionManager(store=ConsentStore(None)), dev=True)

    result = live.describe("nope")

    assert live.dev is True
    assert result["error"]["kind"] == "not_found"
    assert "dev_reload" not in result, "nothing changed, nothing to say"
    assert live.sessions is live.current.sessions


def test_a_stable_change_holds_the_implementation_until_a_reconnect(scratch):
    """Measured on the desktop server: tools reloaded against a session module
    that had not been, and called it with a keyword it did not take. Once a
    stable module changes, the implementation is held at its generation."""
    reloader = reloader_for(scratch)
    bump(scratch / "state.py", "class Store:\n    kind = 2\n")
    reloader.check(force=True)

    bump(scratch / "impl.py", "def answer():\n    return 9\n")
    event = reloader.check(force=True)

    assert event and "held" in event and "reloaded" not in event
    assert reloader.current.answer() == 1 and reloader.generation == 0


# --- a generation is whole or it is not taken (D#70) ------------------------------

@pytest.fixture
def lazy(tmp_path, monkeypatch):
    """A package whose implementation imports its backend at call time,
    the way the tools import `backends.current()` inside each call."""
    pkg = tmp_path / "lazypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "impl.py").write_text(textwrap.dedent("""
        def answer():
            from . import backend
            return backend.VALUE
        """), encoding="utf-8")
    (pkg / "backend.py").write_text("VALUE = 1\n", encoding="utf-8")
    (pkg / "state.py").write_text("class Store:\n    pass\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in [n for n in sys.modules if n == "lazypkg" or n.startswith("lazypkg.")]:
        del sys.modules[name]
    yield pkg
    for name in [n for n in sys.modules if n == "lazypkg" or n.startswith("lazypkg.")]:
        del sys.modules[name]


def lazy_reloader(pkg):
    def build():
        impl = importlib.import_module("lazypkg.impl")
        return SimpleNamespace(answer=impl.answer)

    return HotReloader("lazypkg", pkg, build=build,
                       stable=frozenset({"lazypkg", "lazypkg.state"}))


def test_a_rebuild_imports_what_the_old_generation_had_loaded(lazy):
    """Measured 2026-09-08: a rebuild took a generation whose backend had
    never been imported, and every later call imported the new backend
    file against the held contract and raised. Five hours, no session.
    Now a module the old generation had loaded must import for the new
    one to be taken."""
    reloader = lazy_reloader(lazy)
    assert reloader.current.answer() == 1  # the backend is loaded lazily, now

    bump(lazy / "backend.py", "assert False, {'disclosure'}\nVALUE = 2\n")
    event = reloader.check(force=True)

    assert event and "AssertionError" in event["error"], event
    assert event["kept"] == "generation 0"
    assert reloader.current.answer() == 1, "the old backend, still in sys.modules"


def test_a_rebuild_that_can_import_its_backend_is_taken(lazy):
    reloader = lazy_reloader(lazy)
    assert reloader.current.answer() == 1

    bump(lazy / "backend.py", "VALUE = 2\n")
    event = reloader.check(force=True)

    assert event and event["generation"] == 1, event
    assert reloader.current.answer() == 2


def test_a_call_that_raises_while_held_says_the_implementation_is_held():
    """The held event surfaces once; the call that then fails because of
    the hold needs the note again, or it reads as a bare traceback name."""
    from ghostdriver.consent import ConsentStore
    from ghostdriver.session import SessionManager

    live = LiveToolbox(SessionManager(store=ConsentStore(None)), dev=True)
    reloader = live._reloader
    assert reloader is not None
    reloader.held_for.append("ghostdriver.session")
    reloader.current = SimpleNamespace(
        boom=lambda: {"ok": False, "error": {"kind": "exception",
                                             "message": "AssertionError: {'disclosure'}"}},
        fine=lambda: {"ok": True})

    failed, worked = live.boom(), live.fine()

    assert "held" in failed["dev_reload"]
    assert "Reconnect" in failed["dev_reload"]["held"]
    assert "dev_reload" not in worked, "a call that worked has nothing to add"
