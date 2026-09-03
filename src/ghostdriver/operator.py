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
        if candidate.suffix or len(candidate.parts) > 1:
            return candidate
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

    # --- reports ---------------------------------------------------------------

    def write_report(self, name: str, stamp: str, data: dict) -> Path:
        self.reports.mkdir(parents=True, exist_ok=True)
        path = self.reports / f"{name}-{stamp}.json"
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return path
