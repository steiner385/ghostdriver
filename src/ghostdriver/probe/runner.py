"""Phase-1 probe: gather everything determinable without touching the target.

Phase 1 sends no message that can actuate a control. Its output is a
profile document plus enough evidence for a human to disagree with it.
"""

import hashlib

from ..model.window import WindowNode
from .profile import ProfileDocument, class_census, match_profile
from .toolkit import infer_toolkit


def _profile_id(executable: str, version: str) -> str:
    digest = hashlib.sha256(f"{executable}|{version}".encode()).hexdigest()
    return digest[:16]


def run_phase1(pid: int, *, msaa_sample: int = 40) -> ProfileDocument:
    """Profile a running process. Read-only.

    `msaa_sample` caps how many controls the legacy-accessibility probe
    touches. The sample is taken at an even stride across the whole tree,
    and the profile records both the sample size and the population it was
    drawn from, so a surprising MSAA verdict can be checked against how
    much of the tree it actually saw.
    """
    import psutil

    from ..backends.windows.enumerate import enumerate_process
    from ..backends.windows.msaa import assess_msaa
    from ..backends.windows.process import process_facts
    from ..backends.windows.uia import assess_uia

    facts = process_facts(pid)
    trees: list[WindowNode] = enumerate_process(pid)
    if not trees:
        raise RuntimeError(f"pid {pid} has no top-level windows on this desktop")

    # Profile the largest tree: an application's main window is the one
    # with the most controls beneath it.
    main = max(trees, key=lambda t: sum(1 for _ in t.walk()))
    nodes = list(main.walk())

    toolkit = infer_toolkit(facts.modules)

    uia_control = assess_uia(main.handle, view="control")
    uia_raw = assess_uia(main.handle, view="raw")
    # Spread the sample across the tree rather than taking the first N in
    # pre-order: a contiguous head slice is the root plus one early branch,
    # which is not representative of a tree with a thousand controls.
    # Floor the cap at 1: a caller passing 0 or a negative would divide by
    # zero here, losing the whole profile to an argument mistake.
    cap = max(1, msaa_sample)
    step = max(1, len(nodes) // cap)
    sampled = [n.handle for n in nodes[::step]][:cap]
    msaa = assess_msaa(sampled)

    try:
        command_line = psutil.Process(pid).cmdline()
    except (psutil.Error, OSError):
        command_line = []

    matched = match_profile(
        uia_verdict=uia_control.verdict,
        msaa_verdict=msaa.verdict,
        window_count=len(nodes),
        toolkit=toolkit.toolkit,
    )

    return ProfileDocument(
        profile_id=_profile_id(facts.executable, facts.bitness),
        matched_profile=matched,
        executable={
            "path": facts.executable,
            "bitness": facts.bitness,
            "wow64": facts.wow64,
        },
        toolkit={
            "inferred": toolkit.toolkit,
            "confidence": toolkit.confidence,
            "evidence": toolkit.evidence,
            "secondary": toolkit.secondary,
            "competing": toolkit.competing,
        },
        integrity_level=facts.integrity_level,
        dpi={"awareness": facts.dpi_awareness},
        command_line=command_line,
        window_count=len(nodes),
        unresponsive_count=sum(1 for n in nodes if not n.responsive),
        class_census=class_census(main),
        uia={
            "control_view": {
                "element_count": uia_control.element_count,
                "with_patterns": uia_control.with_patterns,
                "richness": round(uia_control.richness, 4),
                "control_types": uia_control.control_type_histogram,
                "patterns": uia_control.pattern_histogram,
                "max_depth_reached": uia_control.max_depth_reached,
            },
            # The raw view bypasses control-view filtering. Recording both is
            # what lets an empty result be attributed to the provider rather
            # than to the walker.
            "raw_view": {
                "element_count": uia_raw.element_count,
                "with_patterns": uia_raw.with_patterns,
                "max_depth_reached": uia_raw.max_depth_reached,
                # The runbook tells the operator to react to a zero raw-view
                # count. Without this they cannot tell "the provider is
                # genuinely empty" from "the raw walk failed".
                "error": uia_raw.error,
            },
            "verdict": uia_control.verdict,
            "error": uia_control.error,
            "sample": uia_control.sample,
        },
        msaa={
            "probed": msaa.probed,
            "named": msaa.named,
            "with_default_action": msaa.with_default_action,
            "verdict": msaa.verdict,
            # Both numbers, so a surprising verdict can be recognised as a
            # sampling artefact rather than a property of the target.
            "sample_size": len(sampled),
            "sampled_of": len(nodes),
            "error": msaa.error,
            "sample": msaa.sample,
        },
    )
