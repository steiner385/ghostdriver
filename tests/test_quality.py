"""The lint and type gate, run as part of the ordinary test command.

One command -- `pytest` -- is the whole gate. A contributor who runs the
tests has also run the linter and the type checker, and a gate that lives
here cannot be forgotten the way a separate command can. Both tools are in
the `dev` extra, so a missing one is a broken environment and fails loudly
rather than passing silently.

The configuration for both lives in pyproject.toml, so what these tests
enforce is exactly what an editor integration shows.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def test_ruff_finds_nothing():
    result = _run("ruff", "check", "src", "tests")
    assert result.returncode == 0, (
        "ruff reported problems (run `ruff check src tests` to see them):\n"
        + result.stdout + result.stderr
    )


def test_mypy_finds_nothing():
    result = _run("mypy")
    assert result.returncode == 0, (
        "mypy reported problems (run `mypy` to see them):\n"
        + result.stdout + result.stderr
    )
