"""The capability profile document.

A profile is data, not code: onboarding an application means producing one
of these, not writing a driver. Fields that only supervised actuation can
determine are present and empty in a phase-1 document rather than absent,
so a partial profile is never mistaken for a complete one.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..model.window import WindowNode


def class_census(tree: WindowNode) -> dict[str, int]:
    """Count window classes in a tree, most frequent first."""
    counts: dict[str, int] = {}
    for node in tree.walk():
        counts[node.class_name] = counts.get(node.class_name, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def match_profile(
    *,
    uia_verdict: str,
    msaa_verdict: str,
    window_count: int,
    toolkit: str,
    hosts_web_content: bool = False,
) -> tuple[str, str]:
    """Classify a target into a capability profile, and say why.

    Returns (profile, reason). The reason exists because this is a ladder of
    heuristics over partial evidence: a reader who disagrees needs to see
    which rung answered, not just the answer.

    "indeterminate" means *the assessment did not conclude* -- COM
    unavailable, an empty tree, a target at higher integrity than this
    process. It must never be used as a fallthrough for "we have evidence
    but no rule matched", which is a different thing and was being reported
    as the same thing: an application with a working provider exposing 43
    elements came back as "indeterminate", telling an operator nothing was
    known about a target that was plainly drivable.
    """
    if uia_verdict in ("unavailable", "empty", "unknown"):
        return "indeterminate", (
            f"the UIA assessment did not conclude ({uia_verdict}); nothing "
            "downstream can be inferred from its silence"
        )

    if hosts_web_content and uia_verdict != "rich":
        # A web view inside a native shell, whose renderer accessibility is
        # not exposing a usable tree. The native techniques do not reach the
        # document; a browser driver, or waking the renderer, does.
        return "W1", (
            "hosts an embedded web view whose accessibility surface is not "
            f"rich ({uia_verdict}); the document needs a browser driver "
            "rather than native-window techniques"
        )

    if uia_verdict == "rich":
        # Includes a Chromium-family app whose renderer accessibility *is*
        # on: the tree is there, so drive it directly rather than reaching
        # for a separate driver.
        return "M1", "a rich UIA tree with working patterns"

    if window_count >= 50:
        return "L1", (
            f"{window_count} windows: one per control, drivable by window "
            "messages even without a usable accessibility surface"
        )

    if msaa_verdict == "actionable":
        return "M1", (
            "few windows, but the legacy accessibility surface offers "
            "actuation"
        )

    if uia_verdict == "partial":
        # Degraded, not unknown. Some elements carry patterns and some do
        # not, which is worth reporting as a weak M1 rather than as no
        # answer at all.
        return "M1", (
            "a partial UIA tree: some elements carry patterns, so the "
            "surface is usable but not uniformly"
        )

    if toolkit != "unknown" and window_count > 0:
        return "O1", (
            f"a known toolkit ({toolkit}) with no usable accessible surface "
            "and too few windows to drive by message"
        )

    return "indeterminate", (
        "no rule matched: the accessibility surfaces are unusable, the "
        "toolkit is unidentified, and there are too few windows to drive "
        "by message"
    )


@dataclass
class ProfileDocument:
    profile_id: str
    matched_profile: str
    executable: dict = field(default_factory=dict)
    toolkit: dict = field(default_factory=dict)
    integrity_level: str | None = None
    dpi: dict = field(default_factory=dict)
    command_line: list[str] = field(default_factory=list)
    window_count: int = 0
    unresponsive_count: int = 0
    class_census: dict[str, int] = field(default_factory=dict)
    uia: dict = field(default_factory=dict)
    msaa: dict = field(default_factory=dict)

    #: Which rung of the classification ladder answered. A profile without
    #: this is an assertion; with it, a reader can disagree.
    classification_reason: str = ""

    #: Set when this process owns windows on behalf of another process -- a frame
    #: host. Everything else in this document then describes the frame
    #: rather than the application, which runs in a different process.
    hosting_note: str = ""

    #: Modal dialogs holding the target while it was profiled. Non-empty
    #: means the numbers above may describe the dialog rather than the
    #: application: a modal is a separate top-level window, and on a real
    #: target a one-window "Tip of the Day" dialog was profiled as though it
    #: were the whole program.
    blocked_by: list[str] = field(default_factory=list)

    # Populated by supervised phase-2 learning (Iteration 4) or by operator
    # curation. Empty here because nothing read-only can determine them.
    actuation_map: dict = field(default_factory=dict)
    grid_strategy: str = "unknown"
    focus_behavior: dict = field(default_factory=dict)
    denylist: list[str] = field(default_factory=list)
    environment_allowlist: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "matched_profile": self.matched_profile,
            "executable": self.executable,
            "toolkit": self.toolkit,
            "integrity_level": self.integrity_level,
            "dpi": self.dpi,
            "command_line": self.command_line,
            "window_count": self.window_count,
            "unresponsive_count": self.unresponsive_count,
            "classification_reason": self.classification_reason,
            "hosting_note": self.hosting_note,
            "blocked_by": self.blocked_by,
            "class_census": self.class_census,
            "uia": self.uia,
            "msaa": self.msaa,
            "actuation_map": self.actuation_map,
            "grid_strategy": self.grid_strategy,
            "focus_behavior": self.focus_behavior,
            "denylist": self.denylist,
            "environment_allowlist": self.environment_allowlist,
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: str | Path) -> "ProfileDocument":
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))
