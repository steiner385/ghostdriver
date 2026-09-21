"""Consent kept for as long as the target process lives (R1a, D65).

A decision about a target used to die with the server run that recorded
it. In the field that meant every relaunch of the operator app -- and
every deploy of this server -- asked the person again about a target
that had not changed, and a session found out only on its next call.
The person's answer was about *that application, running*; keeping it
for exactly that long is what they meant.

The store is a folder of small files under the operator directory, one
per pid, each naming the process start time as the fingerprint. A pid is
reused after a process ends; a pid with the same start time is the same
process. An entry whose process is gone, or whose start time differs, is
dropped on read. Without an operator directory there is no store and
nothing changes: decisions live for one server run, as before.

Alongside it, and deliberately unlike it, is the operator's *standing
declaration* (D#125): one hand-written file naming executables, not
processes, so a target that restarts is not asked about again. It is
read and never written -- no tool in this server can create or amend it
-- because that is the only thing separating a declaration the operator
made from one the agent would like them to have made. It answers last,
only where nobody has decided about the running process or its
ancestors, so a file edited last week cannot overturn "leave that one
alone" said a minute ago.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path

import psutil

from .policy import ConsentSource, Grant


class ConsentStore:
    def __init__(self, folder: Path | None) -> None:
        self.folder = folder

    @property
    def enabled(self) -> bool:
        return self.folder is not None

    @classmethod
    def from_environment(cls) -> ConsentStore:
        from .operator import ENV_VAR, OperatorDir, OperatorDirError

        if not os.environ.get(ENV_VAR):
            return cls(None)
        try:
            return cls(OperatorDir.resolve().root / "consent")
        except OperatorDirError:
            return cls(None)

    @staticmethod
    def fingerprint(pid: int) -> float | None:
        """When the process started; None when there is no such process."""
        try:
            return psutil.Process(pid).create_time()
        except psutil.Error:
            return None

    def save(self, grant: Grant) -> None:
        """Keep `grant` for the life of its process. Inherited decisions are
        not kept: they follow from their ancestor's, which is."""
        if self.folder is None or grant.inherited_from is not None:
            return
        started = self.fingerprint(grant.pid)
        if started is None:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / f"{grant.pid}.json").write_text(json.dumps({
            "pid": grant.pid, "started": started, "allowed": grant.allowed,
            "source": grant.source.value, "note": grant.note, "at": grant.at,
        }, indent=2), encoding="utf-8")

    def load(self) -> list[Grant]:
        """Every kept decision whose process is still the one it was about."""
        if self.folder is None or not self.folder.is_dir():
            return []
        kept: list[Grant] = []
        try:
            paths = sorted(self.folder.glob("*.json"))
        except OSError:
            return []
        for path in paths:
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
                pid = int(entry["pid"])
                started = float(entry["started"])
                grant = Grant(
                    pid=pid, allowed=bool(entry["allowed"]),
                    source=ConsentSource(entry.get("source", "operator_tool")),
                    note=str(entry.get("note", "")),
                    at=float(entry.get("at", time.time())), restored=True,
                )
            except (OSError, ValueError, KeyError, TypeError):
                _discard(path)
                continue
            now = self.fingerprint(pid)
            if now is None or abs(now - started) > 0.01:
                _discard(path)  # that process is gone; the pid may be reused
                continue
            kept.append(grant)
        return kept


def _discard(path: Path) -> None:
    """Remove a stale entry, or leave it for next time. Another server may
    hold the file open at this instant (two runs starting together), and
    Windows then refuses the delete; a store that cannot tidy itself must
    not take the server down with it -- measured on a desktop relaunch."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


# --- the operator's standing declaration (D#125) -------------------------

#: The file, under the operator directory's root beside `profiles/`. Named
#: for what it is rather than for consent generally, so it is not confused
#: with the per-pid store in `consent/`, which this server does write.
STANDING_FILE = "standing-consent.json"


def _key(path: str) -> str:
    """A declared path and an observed one, comparable.

    `normcase` is the whole point: on Windows it lowercases and settles the
    separator, so a path typed by hand matches the one the process reports;
    on POSIX it is the identity, because two paths differing in case really
    are two files. Symlinks are deliberately *not* resolved -- `exe()` is
    already the resolved target, and resolving the declared side as well
    would silently widen a declaration to every name pointing at that file.
    """
    return os.path.normcase(os.path.normpath(path))


def _stamp(path: Path | None) -> tuple[float, int] | None:
    """What this read of the file was of. None means there was no file --
    which is a state worth telling apart from an empty one, since creating
    the file is how an operator turns the feature on."""
    if path is None:
        return None
    try:
        info = path.stat()
    except OSError:
        return None
    return (info.st_mtime, info.st_size)


class StandingApprovals:
    """What the operator declared about executables, read from their file.

    Absent file, no operator directory, or a file this cannot read: no
    standing decisions at all. The last of those is a `problem`, carried
    rather than raised, so the operator is told their declaration is not in
    force instead of quietly getting the fail-closed behaviour and assuming
    it worked.
    """

    def __init__(self, path: Path | None,
                 entries: dict[str, tuple[bool, str]] | None = None,
                 problem: str | None = None,
                 exe_of: Callable[[int], str | None] | None = None) -> None:
        self.path = path
        #: normalized executable path -> (allowed, note)
        self.entries = entries or {}
        self.problem = problem
        # Injectable for the same reason `SessionManager.parent_of` is: the
        # ordering this class takes part in is platform-neutral policy, and
        # a test of it should not have to start a process to ask about one.
        self._exe_of = exe_of or self.executable
        self._stamp = _stamp(path)

    @property
    def enabled(self) -> bool:
        return bool(self.entries)

    def refresh(self) -> None:
        """Re-read the file if it has changed since it was last read.

        Withdrawing a standing approval must not need a server restart. An
        operator who deletes a line has revoked something, and a revocation
        that waits for a redeploy is one they will believe has taken effect
        when it has not -- the same class of silence D#62 was about. Costs
        one `stat` on the path this server already knows, and only where
        nobody has decided about the target (see `SessionManager.grant_for`);
        nothing at all when no operator directory is configured.
        """
        if self.path is None:
            return
        now = _stamp(self.path)
        if now == self._stamp:
            return
        fresh = self.load(self.path, self._exe_of)
        self.entries, self.problem, self._stamp = (
            fresh.entries, fresh.problem, fresh._stamp)

    @classmethod
    def from_environment(cls) -> StandingApprovals:
        from .operator import ENV_VAR, OperatorDir, OperatorDirError

        if not os.environ.get(ENV_VAR):
            return cls(None)
        try:
            return cls.load(OperatorDir.resolve().root / STANDING_FILE)
        except OperatorDirError:
            return cls(None)

    @classmethod
    def load(cls, path: Path | None,
             exe_of: Callable[[int], str | None] | None = None) -> StandingApprovals:
        if path is None or not path.is_file():
            return cls(path, exe_of=exe_of)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                raise ValueError("expected an object with allow/restrict lists")
            entries: dict[str, tuple[bool, str]] = {}
            # Restrict is applied second so that an executable named in both
            # lists ends up restricted. A declaration that contradicts itself
            # is a mistake, and the safe reading of a mistake is the refusal.
            for allowed, field_name in ((True, "allow"), (False, "restrict")):
                for item in document.get(field_name) or []:
                    declared, note = _entry(item)
                    if declared:
                        entries[_key(declared)] = (allowed, note)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return cls(path, exe_of=exe_of, problem=(
                f"the standing declaration at {path} could not be read "
                f"({exc}); no target is standing-approved until it is fixed"
            ))
        return cls(path, entries, exe_of=exe_of)

    @staticmethod
    def executable(pid: int) -> str | None:
        """The image `pid` is running, or None when it cannot be read.

        A process this server may not open answers nothing, and nothing is
        not a match: an unreadable target is asked about, not approved.
        """
        try:
            return psutil.Process(pid).exe() or None
        except (psutil.Error, OSError):
            return None

    def decide(self, pid: int) -> Grant | None:
        """The declared decision about `pid`'s executable, or None.

        None covers every uncertain case -- no declaration, no file, an
        executable that cannot be read -- because the caller's next move for
        None is to ask a person, which is the right move for all of them.
        """
        self.refresh()
        if not self.entries:
            return None
        image = self._exe_of(pid)
        if image is None:
            return None
        found = self.entries.get(_key(image))
        if found is None:
            return None
        allowed, note = found
        return Grant(pid=pid, allowed=allowed, source=ConsentSource.DECLARED,
                     note=note, standing_for=image)


def _entry(item: object) -> tuple[str, str]:
    """One list entry: a bare path, or an object with `path` and `note`.

    Both spellings are accepted because this file is typed by a person, and
    the shortest thing they will write is the path on its own.
    """
    if isinstance(item, str):
        return item.strip(), ""
    if isinstance(item, dict):
        path = item.get("path") or item.get("exe") or ""
        if not isinstance(path, str):
            raise ValueError(f"path must be a string, got {path!r}")
        return path.strip(), str(item.get("note", ""))
    raise ValueError(f"expected a path or an object with one, got {item!r}")
