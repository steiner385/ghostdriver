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
    *, uia_verdict: str, msaa_verdict: str, window_count: int, toolkit: str
) -> str:
    """Classify a target into a capability profile (spec section 2).

    Returns "indeterminate" rather than guessing when the UIA assessment did
    not actually produce a usable answer. That distinction is the whole point:
    an assessment that failed for an environmental reason -- COM unavailable,
    the target running at higher integrity than this process -- looks nothing
    like a target that genuinely ships no provider, but both leave the tree
    empty. Reporting the first as the second hands the operator a confident
    answer built on no evidence, in the one field they act on.
    """
    if uia_verdict in ("unavailable", "empty", "unknown"):
        # The assessment did not run to a conclusion. Nothing downstream can
        # be inferred from its silence.
        return "indeterminate"
    if uia_verdict == "rich":
        return "M1"
    if window_count >= 50:
        # One window per control: drivable by window messages even with no
        # usable accessibility surface.
        return "L1"
    if msaa_verdict == "actionable":
        # Few windows, but the legacy surface still offers actuation.
        return "M1"
    if toolkit != "unknown" and window_count > 0:
        return "O1"
    return "indeterminate"


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
