"""Infer a GUI toolkit from the modules a process has loaded.

Every framework drags in a signature runtime, which makes the loaded-module
list a reliable fingerprint. Pure function over a list of paths: the caller
supplies the list, so this is testable without a running process.
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
    confidence: str  # "high" | "medium" | "low"
    evidence: list[str] = field(default_factory=list)
    secondary: list[str] = field(default_factory=list)


def _matches(names: list[str], patterns: tuple[str, ...]) -> list[str]:
    hits = []
    for name in names:
        for pattern in patterns:
            if fnmatch.fnmatchcase(name, pattern):
                hits.append(name)
                break
    return hits


def infer_toolkit(module_paths: list[str]) -> ToolkitInference:
    # Extract basenames, handling both forward and backward slashes
    names = []
    for p in module_paths:
        # Replace backslashes with forward slashes for consistent basename extraction
        normalized = p.replace("\\", "/")
        names.append(os.path.basename(normalized).lower())

    secondary = [
        label for label, patterns in SECONDARY_SIGNATURES
        if _matches(names, patterns)
    ]

    for label, patterns in SIGNATURES:
        hits = _matches(names, patterns)
        if not hits:
            continue
        # Two or more independent signature files is materially stronger
        # evidence than one, which could be an incidental dependency.
        confidence = "high" if len(hits) >= 2 else "medium"
        return ToolkitInference(
            toolkit=label, confidence=confidence,
            evidence=sorted(set(hits)), secondary=secondary,
        )

    return ToolkitInference(
        toolkit="unknown", confidence="low", evidence=[], secondary=secondary
    )
