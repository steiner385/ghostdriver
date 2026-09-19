"""The clipboard tool choice (#105, D#105a) -- untested before this file.

`clipboard.py` reads and writes through whichever tool actually reaches the
compositor's own clipboard: `xclip` under X11, `wl-paste`/`wl-copy` under
Wayland, chosen by `WAYLAND_DISPLAY`. `subprocess.run` is faked throughout
so this exercises the choice itself -- not a real clipboard tool, a
display, or a bus -- and the two tools are asserted as a choice, not a
fallback chain: a Wayland session with `wl-paste` missing never reaches for
`xclip`, because that would silently read the wrong clipboard.

This module is pure Python at import time (no `gi`, no live bus); it is
Linux-only because `clipboard.py` lives under `backends/linux/`, with the
rest of that backend, per D59's platform boundary. The backend import is
inside each function, never at module scope
(`test_no_test_module_binds_a_platform_at_import_time`).
"""

from tests.conftest import on_linux

pytestmark = on_linux


class _Completed:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout


class _FakeRun:
    """Records every `subprocess.run` call and answers a scripted result,
    in order. An entry that is an `Exception` instance is raised instead --
    the shape a missing binary takes."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        outcome = self._results.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        returncode, stdout = outcome
        return _Completed(returncode, stdout)


def _clipboard(monkeypatch, *, wayland, results):
    from ghostdriver.backends.linux import clipboard

    if wayland:
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    else:
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    fake = _FakeRun(results)
    monkeypatch.setattr(clipboard.subprocess, "run", fake)
    return clipboard, fake


def test_x11_session_reads_through_xclip(monkeypatch):
    clipboard, fake = _clipboard(monkeypatch, wayland=False, results=[(0, b"hello")])
    assert clipboard.read_clipboard_text() == "hello"
    assert fake.calls == [["xclip", "-selection", "clipboard", "-o"]]


def test_wayland_session_reads_through_wl_paste(monkeypatch):
    clipboard, fake = _clipboard(monkeypatch, wayland=True, results=[(0, b"hello")])
    assert clipboard.read_clipboard_text() == "hello"
    assert fake.calls == [["wl-paste"]]


def test_a_wayland_session_with_no_wl_paste_reads_nothing_not_x11(monkeypatch):
    """The two tools are a choice by session, not a fallback chain (D#105a):
    a missing `wl-paste` means no clipboard read at all, not a quiet reach
    for an X selection that is not the Wayland compositor's own clipboard."""
    clipboard, fake = _clipboard(
        monkeypatch, wayland=True, results=[FileNotFoundError("wl-paste")])
    assert clipboard.read_clipboard_text() is None
    assert fake.calls == [["wl-paste"]]


def test_snapshot_reports_non_text_targets_as_lost_under_x11(monkeypatch):
    clipboard, fake = _clipboard(
        monkeypatch, wayland=False,
        results=[(0, b"UTF8_STRING\nimage/png"), (0, b"kept")])
    assert clipboard.snapshot_clipboard() == {"text": "kept", "lost": ["image/png"]}
    assert fake.calls == [
        ["xclip", "-selection", "clipboard", "-o", "-t", "TARGETS"],
        ["xclip", "-selection", "clipboard", "-o"],
    ]


def test_snapshot_reports_non_text_targets_as_lost_under_wayland(monkeypatch):
    clipboard, fake = _clipboard(
        monkeypatch, wayland=True,
        results=[(0, b"text/plain\nimage/png"), (0, b"kept")])
    assert clipboard.snapshot_clipboard() == {"text": "kept", "lost": ["image/png"]}
    assert fake.calls == [["wl-paste", "--list-types"], ["wl-paste"]]


def test_restore_writes_back_through_xclip_under_x11(monkeypatch):
    clipboard, fake = _clipboard(monkeypatch, wayland=False, results=[(0, b"")])
    assert clipboard.restore_clipboard({"text": "back again"}) == 1
    assert fake.calls == [["xclip", "-selection", "clipboard", "-i"]]


def test_restore_writes_back_through_wl_copy_under_wayland(monkeypatch):
    clipboard, fake = _clipboard(monkeypatch, wayland=True, results=[(0, b"")])
    assert clipboard.restore_clipboard({"text": "back again"}) == 1
    assert fake.calls == [["wl-copy"]]


def test_restore_with_no_prior_text_leaves_the_clipboard_alone(monkeypatch):
    clipboard, fake = _clipboard(monkeypatch, wayland=False, results=[])
    assert clipboard.restore_clipboard({"text": None}) == 0
    assert fake.calls == []
