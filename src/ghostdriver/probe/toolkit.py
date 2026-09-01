"""Infer a GUI toolkit from the modules a process has loaded.

Every framework drags in a signature runtime, which makes the loaded-module
list a reliable fingerprint. Pure function over a list of paths: the caller
supplies the list, so this is testable without a running process.

When multiple frameworks' signatures are present, the one with the most
independent signature files is selected. If a tie remains (e.g., both have
2 files), SIGNATURES order (most-specific-first) breaks the tie.

Confidence is "ambiguous" whenever a second framework matched at all, not
only when the counts tie: the selected label is then a ranking, and the
caller needs to know the answer is contested rather than clean. With a
single match, confidence is "high" for two or more signature files and
"medium" for one. With no match at all the toolkit is "unknown" and
confidence is "low".
"""

import fnmatch
import os
from dataclasses import dataclass, field

#: Ordered most-specific first. Each entry maps a toolkit label to the
#: filename globs that identify it.
SIGNATURES: list[tuple[str, tuple[str, ...]]] = [
    ("delphi-vcl", ("vcl*.bpl", "rtl*.bpl", "borlndmm.dll", "midas.dll")),
    ("powerbuilder", ("pbvm*.dll", "libpb*.dll")),
    ("vb6", ("msvbvm60.dll", "msvbvm50.dll")),
    ("mfc", ("mfc*.dll",)),
    ("dotnet", ("mscoree.dll", "clr.dll", "coreclr.dll")),
    ("java", ("jvm.dll", "awt.dll", "jawt.dll")),
    ("qt", ("qt5core.dll", "qt6core.dll")),
    ("wxwidgets", ("wxmsw*.dll", "wxbase*.dll")),
]

#: Not host toolkits — these coexist with one and are reported separately.
SECONDARY_SIGNATURES: list[tuple[str, tuple[str, ...]]] = [
    ("embedded-webview", ("webview2loader.dll", "embeddedbrowserwebview.dll")),
    ("embedded-cef", ("libcef.dll",)),
]


@dataclass
class ToolkitInference:
    toolkit: str
    confidence: str  # "high" | "medium" | "low" | "ambiguous"
    evidence: list[str] = field(default_factory=list)
    secondary: list[str] = field(default_factory=list)
    competing: list[str] = field(default_factory=list)


def _basename(path: str) -> str:
    """Extract basename, handling both forward and backward slashes."""
    normalized = path.replace("\\", "/")
    return os.path.basename(normalized).lower()


def _matches(names: list[str], patterns: tuple[str, ...]) -> list[str]:
    hits = []
    for name in names:
        for pattern in patterns:
            if fnmatch.fnmatchcase(name, pattern):
                hits.append(name)
                break
    return hits


def infer_toolkit(module_paths: list[str]) -> ToolkitInference:
    names = [_basename(p) for p in module_paths]

    secondary = [
        label for label, patterns in SECONDARY_SIGNATURES
        if _matches(names, patterns)
    ]

    matched: list[tuple[str, list[str]]] = []
    for label, patterns in SIGNATURES:
        hits = _matches(names, patterns)
        if hits:
            matched.append((label, sorted(set(hits))))

    if not matched:
        return ToolkitInference(
            toolkit="unknown", confidence="low", evidence=[], secondary=secondary
        )

    # Rank by how many independent signature files each framework contributed.
    # Ties keep SIGNATURES order, which is most-specific-first, so the result is
    # deterministic rather than dependent on dict or set iteration.
    matched.sort(key=lambda entry: -len(entry[1]))
    label, hits = matched[0]
    competing = [other_label for other_label, _ in matched[1:]]

    if competing:
        # Two frameworks' signatures coexist. Name the strongest, name the
        # others, and never claim high confidence: the caller needs to know
        # the answer is contested rather than being handed a clean guess.
        confidence = "ambiguous"
    else:
        confidence = "high" if len(hits) >= 2 else "medium"

    return ToolkitInference(
        toolkit=label, confidence=confidence, evidence=hits,
        secondary=secondary, competing=competing,
    )
