"""The operator's directory: where everything that names a target lives.

Profile documents with real endpoints, curated denylists and safe-control
lists, workflow files, run reports. None of it belongs in a repository --
not this one, and not a private one either -- so the product reads it from
one configured directory and refuses a directory that is inside a git
checkout. That refusal is the rule made mechanical: target knowledge cannot
be committed by a path that the tool will not read from.

Layout, all optional until used:

    <dir>/profiles/<name>.json     profile documents (denylist, safe_controls, ...)
    <dir>/workflows/<name>.json    workflow files the runner executes
    <dir>/reports/                 what the runner writes back
    <dir>/consent/<pid>.json       decisions kept while their process runs (D65)
    <dir>/standing-consent.json    executables the operator declared (D#125)

The last two are opposites and the difference matters: `consent/` is
written by this server and records what someone was asked, while
`standing-consent.json` is written only by the operator and records what
they decided in advance. Nothing here will ever create or amend it.

Configured by the GHOSTDRIVER_OPERATOR_DIR environment variable or an
explicit path. Nothing here reads from the source tree, and a test guards
that the source tree holds nothing of these shapes.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

ENV_VAR = "GHOSTDRIVER_OPERATOR_DIR"


class OperatorDirError(RuntimeError):
    """The operator directory is missing, misconfigured, or inside a repository."""


def inside_git_checkout(path: Path) -> Path | None:
    """The checkout root `path` lies under, if any."""
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def virtualized_app_data(path: Path) -> Path | None:
    r"""The packaged-app cache root `path` lies under, if any.

    A process inside a packaged (MSIX) application -- which the desktop
    client that hosts this tool is -- has its AppData writes redirected to
    `...\Packages\<app>\LocalCache\...`. Path resolution sees through
    the redirection, which is how this can tell. Measured: a directory
    created under %LOCALAPPDATA% from here landed in the package cache,
    where the operator's own shell would never find it.
    """
    parts = [p.lower() for p in path.parts]
    if "packages" in parts and "localcache" in parts:
        index = parts.index("localcache")
        return Path(*path.parts[: index + 1])
    return None


@dataclass(frozen=True)
class OperatorDir:
    root: Path

    @classmethod
    def resolve(cls, explicit: str | os.PathLike | None = None) -> "OperatorDir":
        """The configured directory, checked.

        Explicit beats the environment. A directory inside a git checkout
        is refused outright: the point of the directory is that what it
        holds is never versioned, and a path under a repository would make
        committing it a matter of one careless `git add`.
        """
        raw = explicit if explicit is not None else os.environ.get(ENV_VAR)
        if not raw:
            raise OperatorDirError(
                f"no operator directory: set {ENV_VAR} or pass one explicitly. "
                "It holds profiles, workflows and reports, and must not be "
                "inside any repository."
            )
        root = Path(raw).expanduser().resolve()
        virtualized = virtualized_app_data(root)
        if virtualized is not None:
            raise OperatorDirError(
                f"operator directory {raw} resolves to {root}, a packaged "
                "application's private copy of AppData: this process runs inside "
                "one, and Windows redirects its AppData writes there, so files "
                "put here would be invisible to every other process on the "
                "machine. Use a directory outside AppData -- under the user "
                "profile root, for example."
            )
        checkout = inside_git_checkout(root)
        if checkout is not None:
            raise OperatorDirError(
                f"operator directory {root} is inside the git checkout at "
                f"{checkout}; target knowledge must not live in any repository. "
                "Point it somewhere that is not versioned."
            )
        return cls(root=root)

    # --- layout --------------------------------------------------------------

    @property
    def profiles(self) -> Path:
        return self.root / "profiles"

    @property
    def workflows(self) -> Path:
        return self.root / "workflows"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def captures(self) -> Path:
        return self.root / "captures"

    def ensure(self) -> None:
        for folder in (self.profiles, self.workflows, self.reports):
            folder.mkdir(parents=True, exist_ok=True)

    # --- lookups ---------------------------------------------------------------

    def profile_path(self, name_or_path: str) -> Path:
        """A profile by bare name in the directory, or a path as given.

        A bare name (no separator, no suffix) is looked up under profiles/;
        anything that looks like a path is used as one, so a caller with a
        profile elsewhere is not forced through the directory.
        """
        candidate = Path(name_or_path)
        if len(candidate.parts) > 1:
            return candidate  # a path (has a directory), used as given
        # A bare name in profiles/: with a .json suffix used as the file name,
        # otherwise .json appended -- so a dotted stem like
        # target-profile.redacted resolves, not read as a path.
        if candidate.suffix == ".json":
            return self.profiles / name_or_path
        return self.profiles / f"{name_or_path}.json"

    def workflow_path(self, name: str) -> Path:
        path = self.workflows / f"{name}.json"
        if not path.exists():
            known = ", ".join(self.list_workflows()) or "none"
            raise OperatorDirError(
                f"no workflow named {name!r} in {self.workflows} (known: {known})")
        return path

    def list_workflows(self) -> list[str]:
        if not self.workflows.exists():
            return []
        return sorted(p.stem for p in self.workflows.glob("*.json"))

    @property
    def workflow_archive(self) -> Path:
        """Where a deleted macro goes, out of the listing but recoverable
        (a leading-dot folder `glob("*.json")` does not descend into)."""
        return self.workflows / ".archive"

    @staticmethod
    def _bare_name(name: str) -> str:
        """A macro name is a bare name the operator chose, never a path -- the
        folder is the operator's and the file goes in it, nowhere else."""
        if not name or any(sep in name for sep in ("/", "\\")) or name in (".", ".."):
            raise OperatorDirError(
                f"a macro name is a bare name, not a path; got {name!r}")
        return name

    def save_workflow(self, name: str, data: dict) -> tuple[Path, bool]:
        """Write a macro to workflows/<name>.json. Returns (path, replaced):
        `replaced` says whether a macro of that name was already there, so a
        save that overwrites is never silent."""
        self._bare_name(name)
        self.workflows.mkdir(parents=True, exist_ok=True)
        path = self.workflows / f"{name}.json"
        replaced = path.exists()
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return path, replaced

    def archive_workflow(self, name: str, stamp: str) -> Path:
        """Move a macro to the archive. `workflow_path` raises if it is not
        there, so a delete of nothing is a clear error, not a silent no-op."""
        source = self.workflow_path(name)
        self.workflow_archive.mkdir(parents=True, exist_ok=True)
        dest = self.workflow_archive / f"{name}-{stamp}.json"
        source.rename(dest)
        return dest

    # --- reports ---------------------------------------------------------------

    def write_report(self, name: str, stamp: str, data: dict) -> Path:
        self.reports.mkdir(parents=True, exist_ok=True)
        path = self.reports / f"{name}-{stamp}.json"
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return path


def profile_location(name_or_path: str) -> str:
    """A bare profile name is looked up in the operator directory, when one is
    configured; a path is used as given. So a client says `profile_path=
    "sandbox"` and never types a path that names a machine."""
    if os.environ.get(ENV_VAR):
        try:
            return str(OperatorDir.resolve().profile_path(name_or_path))
        except OperatorDirError:
            pass  # a misconfigured directory falls back to the literal path
    return name_or_path


def save_capture(name: str, png: bytes) -> Path:
    """Keep a capture under the operator directory's captures/ folder.

    A bare file name, never a path: the folder is the operator's and the
    name is all a caller chooses. Returns where it went (D65).
    """
    if not name or any(sep in name for sep in ("/", "\\")) or name in (".", ".."):
        raise ValueError("save_as is a file name, not a path; the file goes under "
                         "the operator directory's captures/ folder")
    if not os.environ.get(ENV_VAR):
        raise ValueError(f"saving needs an operator directory ({ENV_VAR}); the "
                         "image is still returned inline")
    folder = OperatorDir.resolve().captures
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (name if name.lower().endswith(".png") else f"{name}.png")
    path.write_bytes(png)
    return path
