"""Phase-1 probe: gather everything determinable without touching the target.

Phase 1 sends no message that can actuate a control. Its output is a
profile document plus enough evidence for a human to disagree with it.
"""

import hashlib

from ..model.window import WindowNode, select_main_tree
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
    from ..backends.windows.modality import top_level_state
    from ..backends.windows.msaa import assess_msaa
    from ..backends.windows.process import process_facts
    from ..backends.windows.uia import assess_uia
    from ..hosting import hosted_frame_note, is_frame_host
    from ..modality import find_modal_blocks
    from ..surface import is_web_host

    facts = process_facts(pid)
    trees: list[WindowNode] = enumerate_process(pid)
    if not trees:
        raise RuntimeError(f"pid {pid} has no top-level windows on this desktop")

    # The window showing the UI, not the largest one. Both matter here:
    # `main.handle` is the root of the UIA walk below, and rooting that at a
    # toolkit's off-screen proxy reports a handful of bridge-provided
    # elements as a rich provider, which classifies an L1 target as M1.
    main = select_main_tree(trees)
    if main is None:
        raise RuntimeError(f"pid {pid} has no window tree to describe")
    nodes = list(main.walk())

    # Class evidence comes from every top-level tree, not just `main`. The
    # class that identifies a toolkit most decisively can be the proxy
    # window's own -- and that window is a different tree from the one
    # showing the UI, so scoping this to `main` would discard the single
    # best piece of evidence available.
    all_classes = [n.class_name for t in trees for n in t.walk()]
    toolkit = infer_toolkit(
        facts.modules if facts.modules_readable else None,
        class_names=all_classes,
    )

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

    # A modal dialog is a separate top-level window, and the main-window
    # selector will rightly pick it -- it is the only window that can be
    # acted on. But everything measured above then describes the dialog. On
    # a real target a one-window "Tip of the Day" was profiled as though it
    # were the whole application, and nothing in the document said so.
    blocks, unexplained = find_modal_blocks(top_level_state(pid))
    blocked_by = [b.describe() for b in blocks] + [
        f"{u.blocked.text or u.blocked.class_name} is disabled with no "
        "visible dialog to account for it"
        for u in unexplained
    ]

    # Whether any window in the process hosts a browser engine. Checked
    # across every tree rather than the selected one: the shell and the web
    # view are usually different top-level windows.
    # Judged on the window actually measured, not on the process. A shell
    # can own a hosted frame among dozens of windows of its own, and warning
    # that "this describes a frame" would then be false. The warning belongs
    # only where the selected window *is* the frame -- and there it names the
    # application inside, so the reader gets a pid rather than a search.
    hosting_note = ""
    if is_frame_host(main.class_name):
        from ..backends.windows.hosted import resolve_hosted_app

        found = resolve_hosted_app(main.handle, pid)
        app_name = ""
        if found is not None:
            try:
                app_name = psutil.Process(found.pid).name()
            except (psutil.Error, OSError):
                app_name = ""
        hosting_note = hosted_frame_note(
            found.pid if found else None, app_name,
            found.share if found else 0.0,
        )

    hosts_web_content = any(
        is_web_host(n.class_name) for t in trees for n in t.walk()
    ) or bool(toolkit.secondary)

    matched, reason = match_profile(
        uia_verdict=uia_control.verdict,
        msaa_verdict=msaa.verdict,
        window_count=len(nodes),
        toolkit=toolkit.toolkit,
        hosts_web_content=hosts_web_content,
    )

    return ProfileDocument(
        profile_id=_profile_id(facts.executable, facts.bitness),
        matched_profile=matched,
        classification_reason=reason,
        hosting_note=hosting_note,
        blocked_by=blocked_by,
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
            # Which evidence carried the answer, and whether the primary
            # evidence was even legible. Without these, "unknown" from an
            # unreadable module list is indistinguishable from "unknown"
            # after a clean look at a full one.
            "source": toolkit.source,
            "modules_readable": toolkit.modules_readable,
            "disagreement": toolkit.disagreement,
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
