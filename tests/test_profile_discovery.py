"""Which profiles exist and which fit a target; describe's notes; find's
look elsewhere; the server generation (#242). Backend-free."""

import json
import os
import sys
from types import SimpleNamespace

import pytest

from ghostdriver.model.window import WindowNode
from ghostdriver.operator import ENV_VAR
from ghostdriver.policy import ConsentSource
from ghostdriver.session import Profile, SessionManager
from ghostdriver.tools import Toolbox
from ghostdriver.tools.profiles import profile_candidates, profile_names, server_generation


@pytest.fixture
def opdir(tmp_path, monkeypatch):
    root = tmp_path / "ops"
    (root / "profiles").mkdir(parents=True)
    monkeypatch.setenv(ENV_VAR, str(root))
    profiles = root / "profiles"
    (profiles / "vendorapp.json").write_text(json.dumps({"executables": ["VendorApp.Exe"]}))
    (profiles / "sandbox.json").write_text(json.dumps(
        {"executable": {"path": "C:\\Program Files (x86)\\VendorApp\\VendorApp.Exe"}}))
    (profiles / "other.json").write_text(json.dumps({"executables": ["notepad.exe"]}))
    (profiles / "vendorapp.json.bak").write_text("{}")
    return profiles


def test_profiles_are_listed_by_bare_name_and_backups_are_not_profiles(opdir):
    assert profile_names() == ["other", "sandbox", "vendorapp"]


def test_candidates_match_by_executable_file_name_either_way(opdir):
    assert profile_candidates(r"C:\Elsewhere\vendorapp.exe") == ["sandbox", "vendorapp"]
    assert profile_candidates("notepad.exe") == ["other"]
    assert profile_candidates("calc.exe") == [] and profile_candidates(None) == []


def attach(box, **kw):
    pid = os.getpid()
    box.sessions.record_grant(pid, allowed=True, source=ConsentSource.ELICITED)
    return box.attach(pid, tier="read_only", **kw)


def test_attach_names_a_missing_profile_and_lists_the_ones_there(opdir):
    result = attach(Toolbox(SessionManager()), profile_path="no-such")
    assert not result["ok"] and result["error"]["kind"] == "not_found"
    assert "it has: other, sandbox, vendorapp" in result["error"]["message"]


def test_the_offer_names_the_candidates_and_how_to_take_one(opdir):
    """Through its own seam, so it runs on any platform (#242)."""
    from ghostdriver.tools.profiles import profile_offer

    offer = profile_offer(r"C:\Program Files (x86)\VendorApp\VendorApp.Exe")

    assert offer["profile_candidates"] == ["sandbox", "vendorapp"]
    assert 'profile_path="sandbox"' in offer["profile_hint"]
    assert "vendorapp" in offer["profile_hint"]
    assert profile_offer("calc.exe") == {} and profile_offer(None) == {}


@pytest.mark.skipif(sys.platform != "win32",
                    reason="a full attach of this process needs a backend that can see it")
def test_attach_offers_a_profile_for_this_executable_but_does_not_load_it(opdir):
    import psutil

    exe = os.path.basename(psutil.Process().cmdline()[0])
    (opdir / "mine.json").write_text(json.dumps({"executables": [exe]}))

    result = attach(Toolbox(SessionManager()))

    assert result["ok"] and result["matched_profile"] == "unknown", result
    assert result["profile_candidates"] == ["mine"]
    assert 'profile_path="mine"' in result["profile_hint"]
    assert result["server_generation"] == server_generation()


def test_the_server_generation_names_this_process():
    assert server_generation().startswith(f"{os.getpid()}-")


# --- describe carries the notes; find looks elsewhere ---------------------------------

def node(handle, cls, text="", children=()):
    return WindowNode(handle=handle, class_name=cls, text=text, rect=(0, 0, 10, 10),
                      visible=True, enabled=True, pid=1, children=tuple(children))


@pytest.fixture
def box(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "ops2"))
    box = Toolbox(SessionManager())
    profile = Profile(notes={"THtLeftPanel": "a mouse affordance; use the keys"})
    session = SimpleNamespace(session_id="s", pid=1, run=lambda f: f(), profile=profile)
    monkeypatch.setattr(box.sessions, "authorize", lambda sid, tool: session)
    monkeypatch.setattr(box, "_blocking", lambda s: [])
    monkeypatch.setattr(box, "_frame_note", lambda: {})
    monkeypatch.setattr("ghostdriver.tools.discovery.current",
                        lambda: SimpleNamespace(winapi=SimpleNamespace(is_hung=lambda h: False)))
    return box


def test_describe_carries_the_profile_notes_for_classes_it_saw(box, monkeypatch):
    tree = node(1, "TShell", "Main", children=[node(2, "THtLeftPanel"), node(3, "TEdit")])
    monkeypatch.setattr(box, "_trees", lambda session, all_windows: [tree])

    result = box.describe("s")

    assert result["notes"] == {"THtLeftPanel": "a mouse affordance; use the keys"}


def test_find_says_how_many_matches_are_in_other_windows(box, monkeypatch):
    def resolve(session, locator, all_windows):
        return [node(9, "THtObjectToolBar")] if all_windows else []

    monkeypatch.setattr(box, "_resolve", resolve)

    result = box.find("s", "class=THtObjectToolBar")

    assert result["match_count"] == 0 and result["matches_in_other_windows"] == 1
    assert "1 match(es) are in other top-level windows" in result["hint"]


def test_find_says_when_no_other_window_has_it_either(box, monkeypatch):
    monkeypatch.setattr(box, "_resolve", lambda session, locator, all_windows: [])
    result = box.find("s", "class=THtObjectToolBar")
    assert result["matches_in_other_windows"] == 0
    assert "gone between calls" in result["hint"]
