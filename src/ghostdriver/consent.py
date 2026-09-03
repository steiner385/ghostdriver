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
"""

from __future__ import annotations

import json
import os
import time
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
        for path in sorted(self.folder.glob("*.json")):
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
                path.unlink(missing_ok=True)
                continue
            now = self.fingerprint(pid)
            if now is None or abs(now - started) > 0.01:
                path.unlink(missing_ok=True)  # that process is gone; the pid may be reused
                continue
            kept.append(grant)
        return kept
