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

#: Window-class fingerprints, used when no module signature matches.
#:
#: A statically linked application drags in no framework runtime at all, so
#: the module list -- the primary evidence above -- cannot identify it even
#: in principle. Observed on a real target: 122 modules loaded, not one of
#: them a framework signature, while the window classes named the toolkit
#: unambiguously. The tree is the evidence that survives static linking.
#:
#: Patterns are lowercase and matched against lowercased class names.
CLASS_SIGNATURES: list[tuple[str, tuple[str, ...]]] = [
    ("delphi-vcl", ("tapplication", "tform*", "tpanel", "tadv*", "tsf*")),
    ("mfc", ("afx:*",)),
    ("dotnet", ("windowsforms10*", "hwndwrapper*")),
    ("java", ("sunawt*",)),
    ("qt", ("qt5*", "qt6*", "qwidget*")),
    ("wxwidgets", ("wxwindow*",)),
]

#: Secondary frameworks detectable from window classes. An embedded browser
#: is the case the profile calls significant, because those regions of the
#: UI are a web document the window tree cannot see into.
SECONDARY_CLASS_SIGNATURES: list[tuple[str, tuple[str, ...]]] = [
    ("embedded-webview", ("chrome_widgetwin_*",)),
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
    #: Which evidence produced `toolkit`: "modules", "window-classes", or
    #: "none". A reader weighing the answer needs to know that a
    #: window-class inference rests on weaker evidence than a module one.
    source: str = "none"
    #: False when the module list could not be read. `unknown` then means
    #: "not determined" rather than "no signature present".
    modules_readable: bool = True


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


def _infer_from_classes(class_names: list[str]) -> tuple[str, list[str]] | None:
    """Best window-class match, as (label, evidence), or None."""
    lowered = [c.lower() for c in class_names]
    scored: list[tuple[str, list[str]]] = []
    for label, patterns in CLASS_SIGNATURES:
        hits = sorted({h for h in _matches(lowered, patterns)})
        if hits:
            scored.append((label, hits))
    if not scored:
        return None
    scored.sort(key=lambda entry: -len(entry[1]))
    label, hits = scored[0]
    # Cap the evidence: a tree can contain hundreds of distinct matching
    # class names, and a profile document is meant to be read.
    return label, [f"class:{h}" for h in hits[:6]]


def infer_toolkit(
    module_paths: list[str] | None,
    class_names: list[str] | None = None,
) -> ToolkitInference:
    """Identify the host toolkit from loaded modules, falling back to classes.

    `module_paths` of None means the module list could not be read; that is
    reported rather than being allowed to look like "nothing matched".
    """
    modules_readable = module_paths is not None
    names = [_basename(p) for p in (module_paths or [])]
    classes = list(class_names or [])

    secondary = [
        label for label, patterns in SECONDARY_SIGNATURES
        if _matches(names, patterns)
    ]
    lowered_classes = [c.lower() for c in classes]
    for label, patterns in SECONDARY_CLASS_SIGNATURES:
        if label not in secondary and _matches(lowered_classes, patterns):
            secondary.append(label)

    matched: list[tuple[str, list[str]]] = []
    for label, patterns in SIGNATURES:
        hits = _matches(names, patterns)
        if hits:
            matched.append((label, sorted(set(hits))))

    if not matched:
        # No framework runtime is loaded. That is itself informative for a
        # statically linked target, so fall through to the window classes
        # rather than giving up.
        from_classes = _infer_from_classes(classes)
        if from_classes is not None:
            label, evidence = from_classes
            return ToolkitInference(
                toolkit=label,
                # Never "high": window classes are a weaker fingerprint than
                # a loaded runtime, and a theme or component library can
                # borrow another toolkit's naming convention.
                confidence="medium" if len(evidence) >= 2 else "low",
                evidence=evidence,
                secondary=secondary,
                source="window-classes",
                modules_readable=modules_readable,
            )
        return ToolkitInference(
            toolkit="unknown", confidence="low", evidence=[],
            secondary=secondary, source="none",
            modules_readable=modules_readable,
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
        secondary=secondary, competing=competing, source="modules",
        modules_readable=modules_readable,
    )
