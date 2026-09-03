"""Hot reload for development: implementation re-imported on change, live
state kept (D68).

The host spawns this server once and asks for its tool list once, at
`initialize`. After that an edit changes nothing in the running process,
and the only way new code reached a chat was a host restart -- which also
dropped every open session, the very loss the field reports kept
counting. This module is the middle way for development: with
`GHOSTDRIVER_DEV` set, the tool closures resolve the *current* toolbox on
every call, and the toolbox is rebuilt from freshly imported modules
whenever a file under the package changes.

Three layers, and only one reloads:

- **Implementation** -- `tools/`, `backends/`, and the pure modules they
  use -- is re-imported whole. Purging every reloadable module and
  importing again, rather than `importlib.reload` one file at a time,
  because a `from x import y` in a third module keeps the old `y`
  otherwise, and a half-new generation is worse than an old one.
- **State and its types** -- `session`, `policy`, `consent`, `model`,
  and the modules that hold a person's decisions -- is never reloaded. A
  new class for an old instance is a bug waiting; every reloaded module
  re-imports these and gets the same classes the state is made of. An
  edit there is reported as needing a reconnect, not silently ignored.
- **The server itself** -- the tool list and schemas -- is fixed at
  `initialize`. A new tool or parameter needs a reconnect; that is the
  host's cache, not this process's.

The toolbox's live state (`_desktops`, `_watches`, `_tree_cache`, the
trace) is carried from the old instance to the new one, so an isolated
session's desktop thread and a minimized-watch keep running across a
reload. Retired module objects are kept referenced, not released: a
window class registered by the old `notice` module points at a callback
the old module owns, and freeing it would leave the class pointing at
nothing. Memory is the price, paid only in development.

An edit that does not import -- a typo, mid-save -- leaves the previous
generation in place and says so in the next result, rather than taking
the server down with it.
"""

from __future__ import annotations

import importlib
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

ENV_VAR = "GHOSTDRIVER_DEV"

#: Modules that hold live state or define the types that state is made of.
STABLE = frozenset({
    "ghostdriver",
    "ghostdriver.session",
    "ghostdriver.policy",
    "ghostdriver.consent",
    "ghostdriver.ledger",
    "ghostdriver.sensitivity",
    "ghostdriver.mcp_server",
    "ghostdriver.devreload",
    "ghostdriver.model",
    "ghostdriver.model.element",
    "ghostdriver.model.locator",
    "ghostdriver.model.result",
    "ghostdriver.model.window",
})

#: Toolbox attributes that are live state, carried across a rebuild.
CARRY = ("_desktops", "_watches", "_tree_cache", "_trace")


def enabled() -> bool:
    return os.environ.get(ENV_VAR, "").strip().lower() not in ("", "0", "false", "no", "off")


class HotReloader:
    """Rebuild an object from freshly imported modules when files change.

    `package` is the top-level package name and `root` its directory;
    `stable` names modules never reloaded; `build` constructs the object
    from the current modules; `carry` names attributes copied from the old
    object to the new one.
    """

    CHECK_INTERVAL_S = 0.25

    def __init__(self, package: str, root: Path, *, build: Callable[[], Any],
                 stable: frozenset[str] = STABLE, carry: tuple[str, ...] = ()) -> None:
        self.package = package
        self.root = Path(root)
        self.build = build
        self.stable = stable
        self.carry = carry
        self.generation = 0
        self.events: list[dict] = []
        self._retired: list[dict] = []  # kept alive on purpose; see the module docstring
        self._last_check = 0.0
        self._mtimes = self._scan()
        self.current = build()

    # --- files -----------------------------------------------------------------

    def _scan(self) -> dict[Path, float]:
        out: dict[Path, float] = {}
        for path in self.root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                out[path] = path.stat().st_mtime
            except OSError:
                continue
        return out

    def module_name(self, path: Path) -> str:
        rel = path.relative_to(self.root.parent).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    # --- the check ------------------------------------------------------------------

    def check(self, *, force: bool = False) -> dict | None:
        """Reload if any file changed since the last check. Returns what
        happened, or None when nothing did. Throttled, since it runs on
        every tool call."""
        now = time.monotonic()
        if not force and now - self._last_check < self.CHECK_INTERVAL_S:
            return None
        self._last_check = now
        fresh = self._scan()
        changed = ([p for p, m in fresh.items() if self._mtimes.get(p) != m]
                   + [p for p in self._mtimes if p not in fresh])
        if not changed:
            return None
        self._mtimes = fresh
        names = sorted({self.module_name(p) for p in changed})
        event: dict = {"changed": names}
        reloadable = [n for n in names if n not in self.stable]
        stable = [n for n in names if n in self.stable]
        if reloadable:
            try:
                self._rebuild()
            except Exception as exc:  # the old generation stays; say why
                event["error"] = f"{type(exc).__name__}: {exc}"
                event["kept"] = f"generation {self.generation}"
            else:
                self.generation += 1
                event["reloaded"] = reloadable
                event["generation"] = self.generation
        if stable:
            event["needs_reconnect"] = stable
            event["note"] = (
                "these hold live state or define its types and are never "
                "hot-reloaded; reconnect the server to pick them up"
            )
        self.events.append(event)
        print(f"ghostdriver dev reload: {event}", file=sys.stderr, flush=True)
        return event

    def _rebuild(self) -> None:
        prefix = self.package + "."
        purged = {name: mod for name, mod in list(sys.modules.items())
                  if (name == self.package or name.startswith(prefix))
                  and name not in self.stable}
        for name in purged:
            del sys.modules[name]
        try:
            fresh = self.build()
        except Exception:
            sys.modules.update(purged)  # the working generation, back in place
            raise
        self._retired.append(purged)
        for attr in self.carry:
            if hasattr(self.current, attr):
                setattr(fresh, attr, getattr(self.current, attr))
        self.current = fresh

    def take_events(self) -> list[dict]:
        """Events since last taken: what the next result should mention."""
        out, self.events = self.events, []
        return out


class LiveToolbox:
    """The toolbox the server's tool closures call through.

    Outside development this is a plain pass-through. With `GHOSTDRIVER_DEV`
    set, every attribute access first gives the reloader a chance to rebuild
    the toolbox, and a public tool's result carries `dev_reload` whenever
    something happened since the last result.
    """

    def __init__(self, sessions: Any, *, dev: bool | None = None) -> None:
        import ghostdriver

        self.sessions = sessions
        self.dev = enabled() if dev is None else dev
        root = Path(ghostdriver.__file__).parent

        def build() -> Any:
            tools = importlib.import_module("ghostdriver.tools")
            return tools.Toolbox(sessions=sessions)

        if self.dev:
            self._reloader: HotReloader | None = HotReloader(
                "ghostdriver", root, build=build, carry=CARRY)
            self._box = None
        else:
            self._reloader = None
            self._box = build()

    @property
    def current(self) -> Any:
        return self._reloader.current if self._reloader is not None else self._box

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        reloader = self._reloader
        if reloader is None:
            return getattr(self._box, name)
        reloader.check()
        target = getattr(reloader.current, name)
        if name.startswith("_") or not callable(target):
            return target

        def traced(*args: Any, **kwargs: Any) -> Any:
            result = target(*args, **kwargs)
            events = reloader.take_events()
            if events and isinstance(result, dict):
                result["dev_reload"] = events if len(events) > 1 else events[0]
            return result

        return traced
