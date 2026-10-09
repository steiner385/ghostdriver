# Wayland Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Linux backend work on a Wayland desktop. "Work" means
three things. It reads correctly. It drives a target on a nested
compositor with the same structural guarantee the X11 hidden desktop gives
today. And on the operator's own Wayland desktop it does what the
compositor allows, while refusing the rest by name rather than answering
it wrong.

**Architecture:** The plan has four phases, and each phase gates the next.
- **Phase 0** stops silent wrong answers. It is built here, task by task.
- **Phase 1** is the measurements, W1–W11. Each one is a test plus a
  `D#<issue>` record, the way L0–L8 were for X11.
- **Phase 2** builds on what the measurements found. It covers a nested
  `gnome-shell --headless --wayland` hidden desktop, AT-SPI-sourced state,
  and Mutter's RemoteDesktop/ScreenCast D-Bus for input and capture.
- **Phase 3** is other compositors.

Phases 2 and 3 each get their own plan once their measurements land.
Writing their code now would be the model-before-measurement mistake
`docs/LINUX.md` exists to prevent.

**Tech Stack:** Python 3.11+, AT-SPI2 over PyGObject (`gi`, `Atspi 2.0`),
python-xlib (X11 paths only), GNOME Shell / Mutter 50 D-Bus APIs
(`org.gnome.Mutter.RemoteDesktop`, `org.gnome.Mutter.ScreenCast`),
xdg-desktop-portal, PipeWire, `wl-clipboard`. Tests run under pytest, with
ruff and mypy running inside the suite.

**Spec:** `docs/LINUX.md`: the contract table, and the "Wayland" paragraph
under *What is different enough to need its own decision*. Also the
measurements recorded in the next section. No separate spec exists. Where
this plan and `docs/LINUX.md` disagree, the measurement wins and
`docs/LINUX.md` is corrected.

## What was measured before writing this (2026-10-09, linux-host-a)

linux-host-a is the box the MCP is actually used on. It runs **Ubuntu 26.04,
GNOME Shell 50.1, in a Wayland session** (`loginctl`: `Type=wayland`). The
operator's display is `wayland-0`. `Xwayland :0` runs rootless with
`-enable-ei-portal`. Every read below was taken against the real session,
read-only, with nothing opened or focused. The logs are in `/tmp/gd-wayland-*.log`.

| Probe | Result | What it means |
|---|---|---|
| X `_NET_CLIENT_LIST` vs AT-SPI applications | X: **1** client (Conky). AT-SPI: **13** applications, including Chrome (3 frames), 1Password, Tabby | X sees only XWayland clients. A native Wayland window has no xid. |
| `ghostdriver list-targets` | Lists gnome-shell, 1password, gjs, tabby, chrome | **Enumeration already works.** It is AT-SPI-sourced. |
| `display.foreground_pid()` | `154393` (gnome-shell), while AT-SPI said Chrome's frame was `ACTIVE` | **Silently wrong.** The interference watch and the live-actuation guard (D#111) would never see a foreground change. |
| `display.cursor()` | `(3081, 634)` | XWayland's pointer, which is stale whenever the pointer is over a Wayland surface. Silently wrong. |
| `backend.snapshot(<chrome pid>)` | `windows={}, foreground=0, alive=False` | **A live target reads as gone.** Every action would report `target_gone`. |
| `backend.top_level_state(<chrome pid>)` | `[]` | A modal dialog would never be reported as blocking. |
| `backend.capture_window(<chrome frame>)` | `CaptureError: no X window behind this handle ... a control is an accessible` | Refuses, but the message describes the wrong cause. |
| AT-SPI frame `STATE_ACTIVE` | Set on exactly one frame (Chrome's) | A Wayland-safe foreground signal exists. Its latency and coverage are W1. |
| `gnome-shell --x11` | `Unknown option --x11` | **GNOME 50 removed the X11 backend.** `HiddenDesktop` (Xvfb + `gnome-shell --x11`, D75) cannot start. `tests/test_linux_hidden_desktop.py` errors 4/4 on linux-host-a, with or without Wayland variables. linux-host-b has no gnome-shell at all, so those tests skip there. CI is `windows-latest` only, so nothing caught it. |
| `dbus-run-session -- gnome-shell --headless --wayland --no-x11 --virtual-monitor 1280x800 --wayland-display gd-wl-1` | Starts. Its private bus offers `org.gnome.Mutter.RemoteDesktop`, `org.gnome.Mutter.ScreenCast` and `org.a11y.Bus`. Clean exit on kill. | A nested **Wayland** hidden desktop is feasible on this host, with input and capture APIs that need no consent dialog, because the compositor is ours. |
| That headless shell's a11y bus address | `unix:path=$HOME/.cache/at-spi/bus_0` | It did not collide with the operator's (`/run/user/1000/at-spi/bus`). **Two headless instances would both pick `bus_0`.** |

Found while reading, unrelated to Wayland: `tools/lifecycle.py:262` calls
`MinimizedWatch(pid, family=...)`. The Linux class's signature is
`(pid, main_xid, *, now, poll_s)`, so `attach(isolation="minimized")`
raises `TypeError` on Linux under any display server. It needs its own
issue.

## Global Constraints

- Platform-specific code lives **only** under `src/ghostdriver/backends/`
  (D59). The neutral layer reads `WindowNode`s and `AccessibleElement`s.
- No module under `src/ghostdriver/tools/` may exceed 400 lines
  (`TOOL_MODULE_LIMIT`). `core.py` is at 382 and `status.py` at 387, so
  keep additions there small.
- Errors are results, not exceptions (D10). `UnsupportedPlatform` reaching
  the tool wrapper becomes `denied_by_environment` (#213, merged).
- A target the strategy cannot fit is reported as such, not worked around
  (D53). Where GNOME offers no protocol for something, refuse it. Do not
  reach for a privileged hack.
- Refuse ambiguity rather than picking (D33).
- Never gate a guard on the condition it exists to detect. Phase 0's
  tests must run on **every** platform, made to fail on purpose through
  injected environment and fakes, not `@on_linux`.
- New decisions are numbered from their issue: `### D#<issue>.`. Open the
  issue first.
- Tier 4 (real input) is excluded by default (D9). On the operator's
  desktop it exists only under the live-actuation consent (D#111).
- Linux tests are `tests/test_linux_*.py`, skipped where
  `sys.platform != "linux"`. Platform-neutral tests carry no gate.
- Run the suite as `PYTHONPATH=src python3 -m pytest`. On Linux, use a venv
  built with `--system-site-packages`, so `gi` is visible.

## Review Focus

1. **A session type that lies.** If `XDG_SESSION_TYPE=x11` while
   `WAYLAND_DISPLAY` is also set (a nested Wayland compositor started from
   an X session), the result must be `x11`, the variable naming the session
   wins. Pinned in Task 1:
   `test_xdg_session_type_wins_over_a_stray_wayland_display`.
2. **A hidden desktop on a Wayland host.** The operator is on Wayland, but
   a claimant registered by `HiddenDesktop` with only a `DISPLAY` is X11,
   and its X calls must still work. Pinned in Task 1:
   `test_a_hidden_desktop_answers_from_its_own_registration`. Task 2 adds
   `test_a_hidden_desktop_on_a_wayland_host_is_not_refused`.
3. **Enumeration must survive the guard.** `list_targets` works on Wayland
   today, and refusing X must not break it. Pinned in Task 2:
   `test_frame_correlation_is_skipped_not_refused_on_wayland`.
4. **An action must not run blind.** The actuator swallows observer
   failures by design (`Actuator._look`). On Wayland, that would let an
   action run with no disturbance reporting at all. Pinned in Task 3:
   `test_an_observer_the_platform_cannot_supply_stops_the_action_before_it_runs`.
5. **Unknown is not "none".** `describe`, `surfaces` and `attach` report
   `blocked`. On Wayland, until W2, that must be `null` (unknown), never
   `[]` (not blocked). Pinned in Task 4:
   `test_blocking_is_unknown_not_empty_when_the_platform_cannot_read_it`.

---

## Phase 0: stop the silent wrong answers (build now)

What ships: on a Wayland operator desktop, the read-only tools
(`list_targets`, `describe`, `find`, `read`) keep working. Every name that
reads or drives the desktop through X refuses with `denied_by_environment`
and says why. On X11 nothing changes.

### Task 0: Open the issue and branch

- [ ] **Step 1: Open the tracking issue**

```bash
gh issue create --title "Wayland: X-sourced desktop state answers wrong on a Wayland session" \
  --label "env: linux" --body "$(cat <<'EOF'
On a GNOME 50 Wayland session (linux-host-a), the Linux backend reads foreground,
pointer, modality and liveness from XWayland, which only knows X clients:
foreground_pid() names gnome-shell while Chrome is active, snapshot() of a
live Chrome says alive=False, top_level_state() is empty. Enumeration is
AT-SPI-sourced and still correct.

Phase 0 of docs/superpowers/plans/2026-10-09-wayland-support.md: detect the
session type and refuse X-sourced names on a Wayland operator desktop.
EOF
)"
```

Record the number it prints as `<N>`. Tasks 3 and 6 use it.

- [ ] **Step 2: Branch**

```bash
git fetch origin && git checkout -b claude/issue-<N>-wayland-guard origin/main
```

### Task 1: Detect the display server, per claimant

**Files:**
- Create: `src/ghostdriver/backends/linux/session_type.py`
- Test: `tests/test_wayland_session_type.py` (no platform gate: the module
  imports only `desktop_claim` and stdlib)

**Interfaces:**
- Consumes: `desktop_claim.effective_owner() -> str`,
  `desktop_claim.environment_for(owner) -> dict[str, str]`,
  `desktop_claim.OPERATOR_DESKTOP`, `desktop_claim.desktop(name)`,
  `desktop_claim.register(name, **env)`
- Produces:
  - `DisplayServer = Literal["x11", "wayland"]`
  - `display_server(owner: str | None = None, environ: Mapping[str, str] | None = None) -> DisplayServer`
  - `class X11Only(UnsupportedPlatform)`
  - `require_x11(what: str) -> None`, which raises `X11Only` on Wayland

- [ ] **Step 1: Write the failing tests**

```python
"""Which display server a claimant's desktop runs (issue <N>).

Platform-neutral by construction: the subject reads an environment mapping
and the claim registry, both injected here, so this runs on Windows too.
"""

import pytest

from ghostdriver.backends import UnsupportedPlatform
from ghostdriver.backends.linux import desktop_claim, session_type


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch):
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/test_wayland_session_type.py -v`
Expected: collection fails with `ImportError: cannot import name 'session_type'`.

- [ ] **Step 3: Write the module**

```python
"""Which display server a claimant's desktop runs: X11 or Wayland (issue <N>).

Measured on linux-host-a (GNOME 50, Wayland), not assumed: XWayland answers X
queries about X clients only, so on a Wayland session every X-sourced fact
about the desktop is a fact about the wrong desktop. `_NET_ACTIVE_WINDOW`
named gnome-shell while Chrome held the front; `snapshot` of a live Chrome
said `alive=False`. Enumeration is AT-SPI-sourced and was right. So the
question "is this desktop X11" has to be asked before any X call, and per
claimant: a hidden desktop on a Wayland host is still an X server.

`XDG_SESSION_TYPE` wins when it is set, because it names the *session*.
`WAYLAND_DISPLAY` alone also leaks into the children of a nested
compositor started from an X session.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

from .. import UnsupportedPlatform
from . import desktop_claim

DisplayServer = Literal["x11", "wayland"]


class X11Only(UnsupportedPlatform):
    """This name reads or drives the desktop through X, and the desktop is
    a Wayland session, where X sees only XWayland clients."""


def display_server(owner: str | None = None,
                   environ: Mapping[str, str] | None = None) -> DisplayServer:
    """The display server `owner`'s desktop runs (default: whoever is
    asking now). A hidden desktop answers from what it registered; the
    operator's desktop from the process environment."""
    owner = owner or desktop_claim.effective_owner()
    if owner != desktop_claim.OPERATOR_DESKTOP:
        registered = desktop_claim.environment_for(owner)
        return "wayland" if registered.get("WAYLAND_DISPLAY") else "x11"
    env = os.environ if environ is None else environ
    kind = env.get("XDG_SESSION_TYPE", "")
    if kind in ("x11", "wayland"):
        return "x11" if kind == "x11" else "wayland"
    return "wayland" if env.get("WAYLAND_DISPLAY") else "x11"


def require_x11(what: str) -> None:
    """Refuse `what` on a Wayland desktop, saying why."""
    if display_server() == "wayland":
        raise X11Only(
            f"{what} reads the desktop through X11, and this is a Wayland "
            "session, where X sees only XWayland clients -- the answer "
            "would be about the wrong desktop. Reading the window tree "
            "still works. See docs/LINUX.md (Wayland) for what is measured."
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/test_wayland_session_type.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/ghostdriver/backends/linux/session_type.py tests/test_wayland_session_type.py
git commit -m "feat(linux): detect the display server per claimant (#<N>)"
```

Note: `tests/test_structure.py` requires every module to be reachable from
an entry point. Task 2 imports `session_type` from `display.py`, which
makes it reachable. If the structure test runs between the two tasks, it
fails until Task 2 lands. That is expected; do not loosen it.

### Task 2: Refuse X on a Wayland operator desktop, without breaking enumeration

**Files:**
- Modify: `src/ghostdriver/backends/linux/display.py`: `_display()` (line ~37) and the imports
- Modify: `src/ghostdriver/backends/linux/tree.py`: `_correlate_frame` (line ~290)
- Modify: `src/ghostdriver/backends/linux/isolate.py`: `MinimizedWatch.__init__`
- Modify: `src/ghostdriver/backends/linux/interference.py`: `InterferenceWatch.__init__`
- Test: `tests/test_wayland_guard.py` (no platform gate)

**Interfaces:**
- Consumes: `session_type.display_server`, `session_type.require_x11`, `session_type.X11Only` (Task 1)
- Produces: on a Wayland operator desktop, `display._display()` raises
  `X11Only` before importing Xlib. `tree._correlate_frame` returns
  without touching X. Both watches raise `X11Only` at construction.

- [ ] **Step 1: Write the failing tests**

```python
"""On a Wayland operator desktop, X is refused -- except where skipping it
is the honest answer (issue <N>). Platform-neutral: the session type is
injected, and the refusal happens before Xlib is imported."""

import pytest

from ghostdriver.backends.linux import desktop_claim, display, session_type, tree


@pytest.fixture
def wayland(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(desktop_claim, "_environments", {})


def test_the_x_connection_is_refused_on_a_wayland_desktop(wayland):
    with pytest.raises(session_type.X11Only):
        display._display()


def test_a_hidden_desktop_on_a_wayland_host_is_not_refused(wayland, monkeypatch):
    desktop_claim.register("hd-test", DISPLAY=":99")
    # Stop at the point where the real connection would open: reaching it
    # is the proof the guard let the hidden desktop through.
    reached = []
    monkeypatch.setattr(display, "_DISPLAYS", {"hd-test": "a connection"})
    with desktop_claim.desktop("hd-test"):
        reached.append(display._display())
    assert reached == ["a connection"]


def test_frame_correlation_is_skipped_not_refused_on_wayland(wayland, monkeypatch):
    def no_x():
        raise AssertionError("correlation touched X on a Wayland desktop")
    monkeypatch.setattr(display, "client_windows", no_x)

    class Frame:
        handle = 1
        rect = (0, 0, 10, 10)

    tree._correlate_frame(Frame(), pid=1)  # returns, does not raise


def test_the_watches_refuse_at_construction_on_wayland(wayland):
    from ghostdriver.backends.linux.interference import InterferenceWatch
    from ghostdriver.backends.linux.isolate import MinimizedWatch
    with pytest.raises(session_type.X11Only, match="interference watch"):
        InterferenceWatch(1)
    with pytest.raises(session_type.X11Only, match="minimized watch"):
        MinimizedWatch(1, 0)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/test_wayland_guard.py -v`
Expected: 4 failed. The first fails with `AccessibilityUnavailable` or a
real connection instead of `X11Only`. The correlation test fails with
`AssertionError: correlation touched X`. The watch test fails with
`DID NOT RAISE`.

- [ ] **Step 3: Implement**

In `display.py`, add `session_type` to the relative import that already
brings in `desktop_claim`, and make it the first thing `_display()` does:

```python
    owner = desktop_claim.effective_owner()
    if session_type.display_server(owner) == "wayland":
        session_type.require_x11("this call")
```

`_display` is the one choke point every X call goes through, so this one
check covers foreground, the pointer, iconify, activate, key presses and
capture.

In `tree.py`, at the top of `_correlate_frame`, before `_entry(...)`:

```python
    from . import session_type
    if session_type.display_server() == "wayland":
        # No xid exists for a native Wayland window, so there is nothing
        # to correlate. Skipping is the answer, not a refusal:
        # enumeration is AT-SPI-sourced and right on Wayland (issue <N>).
        return
```

In `isolate.py`, as the first line of `MinimizedWatch.__init__`:

```python
        from . import session_type
        session_type.require_x11("the minimized watch")
```

In `interference.py`, as the first line of `InterferenceWatch.__init__`:

```python
        from . import session_type
        session_type.require_x11("the interference watch")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/test_wayland_guard.py tests/test_wayland_session_type.py tests/test_structure.py -v`
Expected: all pass.

- [ ] **Step 5: Run the Linux suite on an X11 host to confirm nothing changed there**

Run on linux-host-b (no Wayland variables set): `PYTHONPATH=src .venv/bin/python -m pytest -p no:warnings -rs tests/test_linux_*.py 2>&1 | tee /tmp/wayland-guard-x11.log | tail -5`
Expected: the same pass and skip counts as on `origin/main`. Run `main`
first and compare. A new failure means the guard fired on X11.

- [ ] **Step 6: Commit**

```bash
git add src/ghostdriver/backends/linux/{display,tree,isolate,interference}.py tests/test_wayland_guard.py
git commit -m "fix(linux): refuse X-sourced desktop state on a Wayland session (#<N>)"
```

### Task 3: A snapshot the platform cannot take stops the action; it is not "target gone"

**Files:**
- Modify: `src/ghostdriver/backends/linux/modality.py`: `snapshot()` (line ~186)
- Modify: `src/ghostdriver/actuate.py`: `Actuator.perform` (line ~142) and the imports
- Test: `tests/test_wayland_guard.py` (append)

**Interfaces:**
- Consumes: `session_type.X11Only` (Task 1), `backends.UnsupportedPlatform`
- Produces: `modality.snapshot` re-raises `X11Only` instead of returning
  `Snapshot(alive=False)`. `Actuator.perform` returns
  `ActionResult(ok=False, error={"kind": "denied_by_environment", ...})`,
  and no attempt runs, when the first observation raises
  `UnsupportedPlatform`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_snapshot_the_platform_cannot_take_is_not_a_dead_target(wayland, monkeypatch):
    from ghostdriver.backends.linux import modality

    def x_only(pid):
        raise session_type.X11Only("no")
    monkeypatch.setattr(modality, "top_level_state", x_only)
    with pytest.raises(session_type.X11Only):
        modality.snapshot(1)


def test_an_observer_the_platform_cannot_supply_stops_the_action_before_it_runs():
    from ghostdriver.actuate import Actuator, Attempt, Tier
    from ghostdriver.backends import UnsupportedPlatform

    def observe():
        raise UnsupportedPlatform("foreground cannot be read on this desktop")

    ran = []
    result = Actuator(observe=observe, sleep=lambda s: None).perform(
        [Attempt(Tier.WINDOW_MESSAGE, lambda: ran.append(1) or True)])

    assert ran == []
    assert result.ok is False
    assert result.error["kind"] == "denied_by_environment"
    assert "foreground cannot be read" in result.error["message"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src python3 -m pytest tests/test_wayland_guard.py -k "snapshot or observer" -v`
Expected: the first fails with `DID NOT RAISE`, because `snapshot` returns
`alive=False`. The second fails with `assert [1] == []`, because the
action ran.

- [ ] **Step 3: Implement**

In `modality.snapshot`, let the platform refusal through before the broad
handler:

```python
    try:
        state = top_level_state(pid)
    except UnsupportedPlatform:
        # Not a dead target: a desktop this cannot read (issue <N>).
        raise
    except Exception:
        return Snapshot(alive=False)
```

Add `from .. import UnsupportedPlatform` to `modality.py`'s imports.

In `actuate.py`, add `from .backends import UnsupportedPlatform`. In
`Actuator.perform`, replace `before = self._look()` with:

```python
        try:
            before = self._look()
        except UnsupportedPlatform as exc:
            # `_look` swallows observer failures so instrumentation cannot
            # stop an action. A platform that cannot observe at all is
            # different: acting blind would break the non-disruption
            # promise with nobody told (issue <N>, D53).
            return ActionResult(
                ok=False,
                elapsed_ms=self._elapsed(started),
                error={"kind": ErrorKind.DENIED_BY_ENVIRONMENT.value,
                       "message": f"nothing was attempted: {exc}"},
            )
```

In `Actuator._look`, add `except UnsupportedPlatform: raise` above
`except Exception: return None`. Also update the docstring: platform
refusals pass through, and everything else is still swallowed.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src python3 -m pytest tests/test_wayland_guard.py tests/test_actuate.py -v`
Expected: all pass. `test_actuate.py` must not regress.

- [ ] **Step 5: Commit**

```bash
git add src/ghostdriver/backends/linux/modality.py src/ghostdriver/actuate.py tests/test_wayland_guard.py
git commit -m "fix: an action the platform cannot observe is refused, not run blind (#<N>)"
```

### Task 4: `blocked` is unknown, not empty, when it cannot be read

**Files:**
- Modify: `src/ghostdriver/tools/core.py`: `_blocking` (line ~270). Mind the 400-line cap: the file is at 382.
- Test: `tests/test_tool_contracts.py` (append; it already builds a backend-free `Toolbox`)

**Interfaces:**
- Consumes: `backends.UnsupportedPlatform`
- Produces: `Toolbox._blocking(session) -> list[str] | None`, where `None`
  means "could not be read". The three callers (`discovery.py:108`,
  `status.py:102`, `lifecycle.py:301`) need no change: each tests
  truthiness or passes the value through, so `None` serialises as `null`
  and adds no `blocked_hint`.

- [ ] **Step 1: Write the failing test**

```python
def test_blocking_is_unknown_not_empty_when_the_platform_cannot_read_it(
        box, monkeypatch):
    """`[]` says "not blocked". On a desktop where modality cannot be read
    (Wayland, issue <N>) that would be a confident wrong answer. `None`
    is the unknown the server instructions already tell callers to
    expect."""
    from ghostdriver import backends
    from ghostdriver.backends import UnsupportedPlatform

    class NoModality:
        def top_level_state(self, pid):
            raise UnsupportedPlatform("modality cannot be read here")

    session_id = _attached(box, Tier.READ_ONLY)
    monkeypatch.setattr(backends, "current", lambda: NoModality())
    session = box.sessions.authorize(session_id, "describe")

    assert box._blocking(session) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m pytest tests/test_tool_contracts.py -k unknown_not_empty -v`
Expected: FAIL with `UnsupportedPlatform: modality cannot be read here`.

- [ ] **Step 3: Implement**

In `core.py`'s `_blocking`, change the return annotation to
`list[str] | None` and wrap the loop:

```python
        try:
            for pid in self._tree_pids(session):
                state = state + session.run(lambda p=pid: top_level_state(p))
        except UnsupportedPlatform:
            return None  # unknown, not "not blocked" (issue <N>)
```

Add `UnsupportedPlatform` to the existing `from ..backends import current`
line inside the method.

- [ ] **Step 4: Run the tests and the size guard**

Run: `PYTHONPATH=src python3 -m pytest tests/test_tool_contracts.py tests/test_structure.py tests/test_quality.py -v`
Expected: all pass, including `TOOL_MODULE_LIMIT` and mypy. If mypy flags
a caller's use of `blocked`, fix it at the caller.

- [ ] **Step 5: Commit**

```bash
git add src/ghostdriver/tools/core.py tests/test_tool_contracts.py
git commit -m "fix: blocked reads null, not [], where modality cannot be read (#<N>)"
```

### Task 5: Verify on the real Wayland desktop

No code. This is the evidence for the decision record. Read-only: open,
focus and click nothing.

- [ ] **Step 1: Run the read path against linux-host-a's live session**

Point the environment at the real session (the `XAUTHORITY` name comes
from `pgrep -a Xwayland`):

```bash
export DISPLAY=:0 WAYLAND_DISPLAY=wayland-0 XDG_SESSION_TYPE=wayland \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
  XAUTHORITY=$(pgrep -a Xwayland | grep -o '/run/user/1000/.mutter-Xwaylandauth\.[A-Z0-9]*')
PYTHONPATH=src .venv/bin/python -m ghostdriver.cli list-targets 2>&1 | tee /tmp/wayland-p0-list.log
PYTHONPATH=src .venv/bin/python - <<'EOF' 2>&1 | tee /tmp/wayland-p0-backend.log
from ghostdriver.backends import current
from ghostdriver.backends.linux.session_type import X11Only
b = current()
# list-targets prints "PID  WINDOWS  NAME"; take any listed target's pid.
rows = [line.split() for line in open("/tmp/wayland-p0-list.log")]
pid = next(int(r[0]) for r in rows if len(r) == 3 and r[0].isdigit())
for name in ("snapshot", "top_level_state"):
    try: print(name, getattr(b, name)(pid))
    except X11Only as e: print(name, "refused:", str(e)[:80])
EOF
```

Expected: `list-targets` lists the same applications as before.
`snapshot` and `top_level_state` print `refused:` instead of
`alive=False` and `[]`.

- [ ] **Step 2: Run the full suite on linux-host-b (X11) and on linux-host-a**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -p no:warnings -rs 2>&1 | tee /tmp/wayland-p0-full.log | tail -15`
Expected: no new failures against `origin/main` on either host. On linux-host-a,
`test_linux_hidden_desktop.py` still errors because of GNOME 50 (Phase
2a). That is pre-existing, so say so in the PR and do not count it as
yours.

### Task 6: Record the decision and correct the docs

**Files:**
- Modify: `docs/DECISIONS.md` (append `### D#<N>.` at the end of the current iteration)
- Modify: `docs/LINUX.md`: the "Wayland" paragraph
- Modify: `README.md`: the "Wayland is unmeasured" bullet under *Platforms*

- [ ] **Step 1: Write `D#<N>`**

Write it in the house shape: Context, Measurement, Decision, Consequence,
Not done. The content is the measurement table at the top of this plan,
plus the decision itself. On a Wayland operator desktop, X-sourced names
refuse. Enumeration and reading are untouched. `blocked` reads `null`. An
action that cannot be observed is refused.

Name what this costs. On a Wayland desktop, nothing can be actuated, and
`await_human` (the notice), `capture`, `restore` and the minimized
strategy all refuse until Phase 2. That is the D53 trade: a refusal a
caller can read, instead of an action that might take the operator's
desktop with nobody told.

- [ ] **Step 2: Update `docs/LINUX.md` and the README**

In LINUX.md's Wayland paragraph, add: "Measured (D#<N>): X-sourced desktop
state is wrong on a Wayland session and is refused there. Enumeration
works." Then point to this plan for W1–W11.

In the README, replace the Wayland bullet with: "**Wayland: read-only for
now.** On a Wayland desktop the tree reads correctly, and everything that
watched or drove the desktop through X refuses (D#<N>). The plan for the
rest is `docs/superpowers/plans/2026-10-09-wayland-support.md`."

- [ ] **Step 3: Run the docs guards and commit**

Run: `PYTHONPATH=src python3 -m pytest tests/test_structure.py tests/test_backends.py -v`
Expected: pass. The decision-numbering guards accept `D#<N>` out of order.

```bash
git add docs/DECISIONS.md docs/LINUX.md README.md
git commit -m "docs: D#<N> -- X-sourced state is refused on a Wayland session"
```

---

## Phase 1: the measurements (W1–W11)

Each measurement gets an issue labelled `env: linux`, a test in
`tests/test_linux_wayland_*.py`, and a `D#<issue>` record. Run them on
linux-host-a, the GNOME 50 Wayland host.

Except W0, every one runs on a **nested headless compositor**, never on
the operator's session, the same rule L0–L8 followed. The focus guard
(`test_zz_focus_guard.py`) must stay green.

W0 comes first, because everything else needs a nested Wayland desktop to
run on. The order after that is the order things unblock.

| # | Question | How to measure | Unblocks |
|---|---|---|---|
| **W0** | Does a nested `gnome-shell --headless --wayland --no-x11 --virtual-monitor WxH --wayland-display gd-wl-N` under `dbus-run-session` host the GTK fixture with its own a11y bus? Does the nested bus hold **only** the fixture (L1's assertion)? Two instances at once collide on `~/.cache/at-spi/bus_0`, measured. Does a per-instance `XDG_RUNTIME_DIR` or `AT_SPI_BUS_ADDRESS` fix it? | Port `tests/test_linux_atspi.py`'s nested-bus assertion. Launch the fixture with `WAYLAND_DISPLAY=gd-wl-N GDK_BACKEND=wayland`. Start two instances concurrently. | Everything below; Phase 2a |
| **W1** | Foreground without X. Is a frame's `STATE_ACTIVE` exactly one at a time? How fast do `window:activate`/`window:deactivate` events arrive? Is it right for native Wayland, XWayland and Flatpak frames? | Raise windows on the nested shell through Mutter RemoteDesktop (W7) or `gdbus` and timestamp the events. Read-only spot checks of the operator's session are allowed. | The interference watch; the live-actuation guard; `snapshot.foreground` |
| **W2** | Modality without X. Does a GTK4 modal on Wayland carry `STATE_MODAL`, and does its role still read `frame` (D#12 on X11)? Is there any AT-SPI route from a dialog to its owner, given there is no `WM_TRANSIENT_FOR`? | The fixture's timer modal on the nested shell. | `top_level_state`, `blocking_ancestor`, `blocked` |
| **W3** | Frame geometry. Under Wayland a client does not know its global position. What do `get_extents(SCREEN)` and `(WINDOW)` return for frames and for controls? On the operator's session, 1Password's frame read `(669, 324, ...)`: real, or invented? | Compare against Mutter's own window geometry on the nested shell (ScreenCast stream metadata, or `org.gnome.Shell.Introspect` when present). | Element identity by position (D#104), `region=` locators, capture cropping |
| **W4** | Minimized and hidden state. Do AT-SPI states (`ICONIFIED`, `SHOWING`, `VISIBLE`) track minimize on Wayland? GNOME sends `xdg_toplevel` *suspended*. Does GTK surface that? | Minimize the fixture through the nested shell, then read its states. | `visible` on `WindowNode`, `surface_of`, the minimized watch's "on screen" |
| **W5** | The pointer. Wayland has no global pointer query. Can anything report operator pointer movement non-invasively: AT-SPI `mouse:*` events, `org.freedesktop.a11y.Manager`? Or does the interference watch lose its pointer half on Wayland? | Probe the APIs on the nested shell. | `InterferenceWatch`, the live guard (D#111). This one may become a *decision* to drop the pointer half and say so. |
| **W6** | Capture. On the nested shell: Mutter `ScreenCast.RecordWindow`, then PipeWire, then one frame. Which Python route is viable (GStreamer `pipewiresrc`, or `org.gnome.Shell.Screenshot` on the private bus)? On the operator's session: the `org.freedesktop.portal.Screenshot` and ScreenCast portals. What dialog does each show, does a `restore_token` persist, and can one *window* be captured without a dialog every time? | Capture the fixture. Compare against what the operator sees. | `capture_window` (both desktops) |
| **W7** | Input on the nested shell. Mutter `RemoteDesktop.CreateSession`, then `NotifyKeyboardKeysym`, `NotifyPointerButton` and `NotifyPointerMotionAbsolute` (the last needs a ScreenCast stream). Do they reach the fixture? Do they need anything but the private bus? Is GTK's handling of this input the *real* input path, so D#11's tier-3 finding does not apply? | Drive the fixture's custom-drawn button and bound entry, D#10/D#11's targets. | Tier 4 inside the hidden desktop; `press_key`; the copy and focus routes |
| **W8** | XWayland targets on the operator's session. For an X11 app on Wayland, X properties are right **for that app**. But is `_NET_ACTIVE_WINDOW` stale when a Wayland window holds the front? Measured: it named gnome-shell. Can X ever be trusted for foreground on a Wayland session? | Read-only, on the operator's session. | Whether Phase 0's blanket X refusal can narrow to "X for X clients only" |
| **W9** | Flatpak identity without XRes. D#101 used XRes to map a sandboxed window to its real pid. On Wayland, can `flatpak ps` or `/run/user/<uid>/.flatpak/<instance>/bwrapinfo.json` (`child-pid`) map the a11y proxy pid to the application? | Bambu Studio (D#101's specimen) on the nested shell. Note whether it forces `GDK_BACKEND=x11`. | `descendants` aliases, `application_name` |
| **W10** | The operator notice. Is a GNOME notification (`org.freedesktop.Notifications`) non-focusing and visible? Does an XWayland override-redirect window still draw on top? Which one does the `await_human` contract need: something a person cannot miss, which never takes focus? | On the operator's session, one notification with the operator present. **Ask first.** | `OperatorNotice`, so `await_human` |
| **W11** | Live actuation on the operator's Wayland desktop (D#111). The tier-4 Enter needs real input. On GNOME Wayland that is the RemoteDesktop **portal**, which shows a consent dialog, or Xwayland's `-enable-ei-portal` XTest, which goes through the same portal. Measure the dialog and whether a `restore_token` makes it once-only. | On the operator's session with the operator present. **Ask first.** | A product decision (below) |

**Decision points Phase 1 will force.** Use `propose_decision` for these,
do not guess.

- **W5:** if no non-invasive pointer signal exists, does the interference
  watch run on foreground alone on Wayland, saying so in every result? Or
  does live actuation refuse on Wayland?
- **W6/W11:** is a one-time GNOME portal dialog ("Allow remote
  interaction" / "Share screen") acceptable for capture and live
  actuation on the operator's desktop? The dialog appears on the
  operator's screen, so it is a disturbance by definition. It is also
  how the compositor asks for exactly the consent D#111 already requires
  from the operator.
- **Minimized strategy on GNOME Wayland:** GNOME exposes no protocol for
  one client to minimize, or watch the minimized state of, another's
  window. `wlr-foreign-toplevel-management` exists on wlroots and KDE, not
  on GNOME. The expected answer is that this strategy is **unfittable on
  GNOME Wayland (D53)** and `hidden_desktop` is the isolation strategy
  there. Confirm with W4 before recording it.

## Phase 2: build what the measurements allow (own plans)

Each item gets its own plan, written after its measurements land:

- **2a: Wayland `HiddenDesktop`** (after W0, W6, W7). Replace Xvfb +
  `gnome-shell --x11` with nested headless `gnome-shell --wayland`. This
  is **also the fix for the GNOME 50 regression**, so treat it as the
  first build item, not the last. Keep Xvfb as the route where
  `gnome-shell --x11` still exists (GNOME ≤ 48), chosen by probing
  `gnome-shell --help` for `--x11`, not by version number.
  - Inside it, `snapshot` and modality come from AT-SPI (W1, W2), input
    from Mutter RemoteDesktop over the private bus (W7), and capture from
    Mutter ScreenCast (W6).
  - `desktop_claim.register` gains `WAYLAND_DISPLAY`, so `session_type`
    (Task 1) already routes it correctly.
- **2b: AT-SPI-sourced state on the operator's Wayland desktop** (after
  W1–W4, W8). Implement `snapshot`, `top_level_state`, `blocking_ancestor`
  and the interference watch's foreground half from AT-SPI states and
  events. Phase 0's refusals narrow name by name as each is replaced.
  Actuation at tier 1 comes back on Wayland once `snapshot` can observe
  again.
- **2c: Capture, notice and live actuation on the operator's desktop**
  (after W6, W10, W11 and the decisions above).
- **2d: Flatpak identity on Wayland** (after W9).

## Phase 3: other compositors (out of scope until GNOME is done)

KDE (KWin) and wlroots compositors (sway, Hyprland) expose different
privileged protocols:
- `wlr-foreign-toplevel-management` for the window list, activation and
  minimize;
- `ext-image-copy-capture` for capture;
- `virtual-keyboard` and `wlr-virtual-pointer` for input;
- `layer-shell` for the notice.

On those compositors the minimized strategy may well be fittable. Until
each one is measured, `session_type` should also report the compositor
(`XDG_CURRENT_DESKTOP`). A non-GNOME Wayland session gets Phase 0's
refusals with "this compositor has not been measured". It must not get
GNOME's answers by assumption.

## Cross-cutting: Linux CI

There is no Linux CI job (`.github/workflows/tests.yml` is
`windows-latest` only). The GNOME 50 break went unseen because of that.
Every phase above can only be verified by hand on linux-host-b and linux-host-a, which
is the silent-skip trap `CLAUDE.md` warns about.

Add an `ubuntu` job that runs the platform-neutral suite. That at least
pins Phase 0's guards, which are neutral by construction. It also lists
the `test_linux_*` skips, so a skipped backend is visible in CI. A job
that can host a nested headless gnome-shell is a separate, later
question.
