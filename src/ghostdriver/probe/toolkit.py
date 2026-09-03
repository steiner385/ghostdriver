"""Infer which GUI toolkit an application is built on.

Two kinds of evidence, and the ordering between them is the whole design.

**Window classes come first.** A plugin can load a DLL into a process; a
plugin cannot change the class of the application's own windows. That makes
window classes the stronger evidence of what an application is *built on*,
where loaded modules answer the different question of what is *running
inside it*. Measured: a word processor reported itself as .NET because it
loads the CLR for add-ins, while its windows were unmistakably its own
framework's.

**Modules corroborate.** For most frameworks the runtime is definitive --
a JVM, a VCL runtime package, a VB6 virtual machine -- so when the two
agree, the answer is stronger than either alone. When they disagree, that
is reported rather than resolved silently: the caller is told which source
said what, and confidence drops to ambiguous.

Pure functions over lists of names, so this is testable without a running
process.

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
    # Version-numbered deliberately. `mfc*.dll` also matches `mfcore.dll`,
    # which is Windows Media Foundation Core and no relation -- and Media
    # Foundation is loaded by anything that touches audio or video, so the
    # loose pattern mislabelled a large share of ordinary applications as
    # MFC, at medium confidence. Every real MFC runtime carries its version
    # (mfc140.dll, mfc42u.dll).
    ("mfc", ("mfc[0-9]*.dll",)),
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
    ("office", ("opusapp", "netuihwnd", "mso*", "nuipane",
                "framework::cframe", "xlmain", "ppframeclass")),
    ("mfc", ("afx:*",)),
    ("dotnet", ("windowsforms10*", "hwndwrapper*")),
    ("java", ("sunawt*",)),
    ("qt", ("qt5*", "qt6*", "qwidget*")),
    ("chromium", ("chrome_widgetwin_*", "chrome_renderwidgethosthwnd")),
    ("wxwidgets", ("wxwindow*",)),
]

#: Secondary frameworks detectable from window classes. An embedded browser
#: is the case the profile calls significant, because those regions of the
#: UI are a web document the window tree cannot see into.
SECONDARY_CLASS_SIGNATURES: list[tuple[str, tuple[str, ...]]] = [
    ("embedded-webview", ("chrome_widgetwin_*",)),
    # Hosting UWP content is not the same as being a UWP application, and
    # the distinction was learned the hard way: a Win32 shell that hosts
    # XAML islands owns both of these classes, and was briefly reported as
    # a UWP application on the strength of them. Same category error as
    # judging a host by a plugin's runtime.
    ("hosts-uwp-content",
     ("applicationframewindow", "windows.ui.core.corewindow")),
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
    #: Set when window classes and loaded modules point at different
    #: frameworks. Said rather than resolved silently: the caller may know
    #: something about this application that the signature tables do not.
    disagreement: str = ""


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
        hits = sorted(set(_matches(lowered, patterns)))
        if hits:
            scored.append((label, hits))
    if not scored:
        return None
    scored.sort(key=lambda entry: -len(entry[1]))
    label, hits = scored[0]
    # Cap the evidence: a tree can contain hundreds of distinct matching
    # class names, and a profile document is meant to be read.
    return label, [f"class:{h}" for h in hits[:6]]


def _infer_from_modules(
    names: list[str],
) -> tuple[str, list[str], list[str]] | None:
    """Best module match, as (label, evidence, competing), or None."""
    matched: list[tuple[str, list[str]]] = []
    for label, patterns in SIGNATURES:
        hits = _matches(names, patterns)
        if hits:
            matched.append((label, sorted(set(hits))))
    if not matched:
        return None
    # Rank by how many independent signature files each framework
    # contributed. Ties keep SIGNATURES order, which is most-specific-first,
    # so the result is deterministic rather than dependent on set iteration.
    matched.sort(key=lambda entry: -len(entry[1]))
    label, hits = matched[0]
    return label, hits, [other for other, _ in matched[1:]]


def infer_toolkit(
    module_paths: list[str] | None,
    class_names: list[str] | None = None,
) -> ToolkitInference:
    """Identify the host toolkit. Window classes lead; modules corroborate.

    `module_paths` of None means the module list could not be read; that is
    reported rather than being allowed to look like "nothing matched".
    """
    modules_readable = module_paths is not None
    names = [_basename(p) for p in (module_paths or [])]
    classes = list(class_names or [])
    lowered_classes = [c.lower() for c in classes]

    secondary = [
        label for label, patterns in SECONDARY_SIGNATURES
        if _matches(names, patterns)
    ]
    for label, patterns in SECONDARY_CLASS_SIGNATURES:
        if label not in secondary and _matches(lowered_classes, patterns):
            secondary.append(label)

    from_classes = _infer_from_classes(classes)
    from_modules = _infer_from_modules(names)

    if from_classes is None and from_modules is None:
        return ToolkitInference(
            toolkit="unknown", confidence="low", evidence=[],
            secondary=secondary, source="none",
            modules_readable=modules_readable,
        )

    if from_classes is None:
        assert from_modules is not None  # the both-None case returned above
        # No class signature matched -- the table does not know this
        # application's framework. The loaded runtime is then all there is,
        # and for most frameworks it is definitive.
        label, hits, competing = from_modules
        return ToolkitInference(
            toolkit=label,
            confidence="ambiguous" if competing
            else ("high" if len(hits) >= 2 else "medium"),
            evidence=hits,
            secondary=secondary,
            competing=competing,
            source="modules",
            modules_readable=modules_readable,
        )

    label, evidence = from_classes

    if from_modules is None:
        # Statically linked, or a framework with no signature runtime.
        return ToolkitInference(
            toolkit=label,
            confidence="medium" if len(evidence) >= 2 else "low",
            evidence=evidence,
            secondary=secondary,
            source="window-classes",
            modules_readable=modules_readable,
        )

    module_label, module_hits, module_competing = from_modules
    if module_label == label:
        # Both kinds of evidence agree, which is stronger than either alone.
        return ToolkitInference(
            toolkit=label,
            confidence="high",
            evidence=evidence + module_hits,
            secondary=secondary,
            competing=module_competing,
            source="window-classes+modules",
            modules_readable=modules_readable,
        )

    # They disagree. The classes win, because a plugin cannot change a
    # window's class -- but saying so is more useful than quietly picking,
    # since the caller may know something about this application that the
    # signature tables do not.
    return ToolkitInference(
        toolkit=label,
        confidence="ambiguous",
        evidence=evidence,
        secondary=secondary,
        competing=[module_label] + module_competing,
        source="window-classes",
        modules_readable=modules_readable,
        disagreement=(
            f"window classes indicate {label!r} while loaded modules "
            f"indicate {module_label!r} ({', '.join(module_hits[:3])}). "
            "Classes are preferred: a plugin can load a runtime into a "
            "process but cannot change the class of its windows."
        ),
    )
