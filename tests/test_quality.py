"""The lint and type gate, run as part of the ordinary test command.

One command -- `pytest` -- is the whole gate. A contributor who runs the
tests has also run the linter and the type checker, and a gate that lives
here cannot be forgotten the way a separate command can. Both tools are in
the `dev` extra, so a missing one is a broken environment and fails loudly
rather than passing silently.

The shared configuration for both lives in pyproject.toml. The type check is
the one exception to "exactly what an editor integration shows": it runs
**once per backend**, because one mypy run assumes one platform and this
project has two. See `BACKEND_PLATFORMS` below and D#23.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BACKENDS = ROOT / "src" / "ghostdriver" / "backends"

#: The `--platform` mypy is told to assume, per backend package. A run with
#: no `platform` set assumes the *host*, and typeshed is conditional on it:
#: on Linux `ctypes.WinDLL` genuinely does not exist, so the same tree gets
#: 39 errors on one box and none on the other. Setting `platform` globally
#: is wrong the other way round -- it would check `backends/linux` as though
#: it were Windows. So each backend names its own, and the shared tree is
#: checked under every one of them (D#23).
BACKEND_PLATFORMS = {"windows": "win32", "linux": "linux"}


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def _backend_packages() -> list[str]:
    return sorted(
        p.name for p in BACKENDS.iterdir()
        if p.is_dir() and not p.name.startswith("__")
    )


def test_ruff_finds_nothing():
    result = _run("ruff", "check", "src", "tests")
    assert result.returncode == 0, (
        "ruff reported problems (run `ruff check src tests` to see them):\n"
        + result.stdout + result.stderr
    )


def test_every_backend_declares_a_platform():
    """A backend with no entry here would never be type-checked by any pass,
    and nothing else would say so -- the gate would stay green while a whole
    package went unchecked. That is the same silent-success failure the
    platform gates already cause once (D74), so it is a test."""
    packages = _backend_packages()
    undeclared = [p for p in packages if p not in BACKEND_PLATFORMS]
    assert not undeclared, (
        "backend package with no mypy platform target; add it to "
        "BACKEND_PLATFORMS or it is never type-checked: " + ", ".join(undeclared)
    )
    stale = [b for b in BACKEND_PLATFORMS if b not in packages]
    assert not stale, (
        "BACKEND_PLATFORMS names a backend that is gone; remove it: "
        + ", ".join(sorted(stale))
    )


@pytest.mark.parametrize("backend", sorted(BACKEND_PLATFORMS))
def test_mypy_finds_nothing(backend):
    """One pass per backend: the shared tree plus that backend, with that
    backend's platform assumed.

    `--exclude` alone is not enough. It filters the directory crawl, but
    `backends.load()` imports every backend, so the excluded one is pulled
    into the build anyway and reports its errors under the wrong platform.
    `follow_imports = "silent"` (pyproject) is what separates them: modules
    named on the command line are always checked in full, so the shared tree
    still reports; a followed-but-excluded backend is still *analysed*, so
    its types stay correct for callers, without its errors landing here.
    """
    excludes = [
        arg
        for other in sorted(BACKEND_PLATFORMS)
        if other != backend
        for arg in ("--exclude", f"/backends/{other}/")
    ]
    result = _run("mypy", "--platform", BACKEND_PLATFORMS[backend], *excludes, "src")
    assert result.returncode == 0, (
        f"mypy reported problems for the {backend} backend (run "
        f"`mypy --platform {BACKEND_PLATFORMS[backend]} "
        + " ".join(excludes) + " src` to see them):\n"
        + result.stdout + result.stderr
    )
