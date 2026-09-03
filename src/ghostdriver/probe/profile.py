"""The capability profile document.

A profile is data, not code: onboarding an application means producing one
of these, not writing a driver. Fields that only supervised actuation can
determine are present and empty in a phase-1 document rather than absent,
so a partial profile is never mistaken for a complete one.
"""

import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import ClassVar

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
    #: Both default, because a profile document is not always a probe's
    #: output. An operator may write one that carries policy alone -- a
    #: denylist and some notes -- and never run a probe against it. The
    #: example this project ships is exactly that, and requiring these made
    #: it unreadable.
    profile_id: str = ""
    matched_profile: str = "unknown"
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

    #: What this target is known to be sensitive about: whether it wants
    #: human-paced input, per surface, and whether that was declared by an
    #: operator or learned by a session that ran the differential. Curated
    #: rather than probed -- nothing read-only can determine it, and the
    #: encounter that matters most is the first one, before any session has
    #: had a chance to learn anything.
    input_sensitivity: list[dict] = field(default_factory=list)

    #: Controls an operator has said phase 2 may actuate, each with what
    #: should be true afterwards. Curated only: the probe never adds to this,
    #: because a probe that could extend its own permission to act would not
    #: be constrained by it at all.
    safe_controls: list[dict] = field(default_factory=list)

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
            "input_sensitivity": self.input_sensitivity,
            "safe_controls": self.safe_controls,
            "actuation_map": self.actuation_map,
            "grid_strategy": self.grid_strategy,
            "focus_behavior": self.focus_behavior,
            "denylist": self.denylist,
            "environment_allowlist": self.environment_allowlist,
        }

    #: What a probe measures. Everything else in a profile document belongs
    #: to whoever curated it, and a re-probe must not touch it.
    OBSERVED: ClassVar[tuple[str, ...]] = (
        "profile_id", "matched_profile", "executable", "toolkit",
        "integrity_level", "dpi", "command_line", "window_count",
        "unresponsive_count", "classification_reason", "hosting_note",
        "blocked_by", "class_census", "uia", "msaa",
    )

    def save(self, path: str | Path, *, force: bool = False) -> dict:
        """Write this profile, keeping anything curated that is already there.

        A re-probe used to overwrite the file wholesale and take the curated
        policy with it. That was recorded as a known cost when the only
        curated fields were a denylist someone could retype; it stopped
        being acceptable once the file started carrying notes a session had
        *measured* and could not simply reproduce.

        So only the observed fields are replaced. Curated fields keep their
        values, and keys this code does not model at all are passed through
        untouched -- these documents are hand-edited, and an operator's
        comments and notes are not ours to drop because we have no field for
        them.

        Refuses a file describing a different target unless `force`. The
        alternative is silently rewriting one application's profile with
        another's, and the path is usually typed by hand.

        Written whole and moved into place: an interrupted write that
        truncated a profile would leave every later session unable to
        attach.
        """
        location = Path(path)
        observed = {k: v for k, v in self.to_dict().items()
                    if k in self.OBSERVED}
        existing: dict = {}
        preserved: list[str] = []

        if location.exists():
            try:
                existing = json.loads(location.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"{location} exists but could not be read as a profile "
                    f"({exc}); move it aside rather than losing what is in it"
                ) from exc
            if not isinstance(existing, dict):
                raise ValueError(f"{location} is not a profile document")
            was = existing.get("profile_id")
            if was and was != self.profile_id and not force:
                raise ValueError(
                    f"{location} describes {was!r}, not {self.profile_id!r}. "
                    "Re-probing over it would replace one application's "
                    "profile with another's; pass force to do it anyway"
                )
            preserved = sorted(k for k in existing if k not in observed)

        # Three layers, and the order carries the whole policy. This
        # document's own defaults go down first, so a new file arrives as a
        # full template -- the empty curated fields are what show an
        # operator there is something to fill in -- and so a profile written
        # before a field existed gains it. Then whatever is already on disk,
        # which is how curation and unmodelled keys survive. Then the
        # observed fields, which are the only ones a probe is entitled to
        # replace.
        document = {**self.to_dict(), **existing, **observed}
        temporary = location.with_suffix(location.suffix + ".tmp")
        temporary.write_text(json.dumps(document, indent=2) + "\n",
                             encoding="utf-8")
        temporary.replace(location)
        return {"path": str(location), "preserved": preserved,
                "merged": bool(existing)}

    @classmethod
    def load(cls, path: str | Path) -> "ProfileDocument":
        """Read a profile, ignoring keys this code does not model.

        These files are hand-edited and carry comments and operator notes.
        Passing every key straight to the constructor meant a document with
        one extra line could not be read at all -- including the example
        this project ships, which has a `_comment` block at the top.
        """
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})


def merge_learned(
    path,
    *,
    actuation_map: dict | None = None,
    focus_behavior: dict | None = None,
    grid_strategy: str | None = None,
    grid_evidence: dict | None = None,
) -> bool:
    """Write what a probe learned into a profile, touching nothing else.

    The same read-modify-write as `save`, and for the same reason: these
    documents are hand-curated. A probe owns exactly the fields it learned
    and must not be able to disturb a third -- least of all `safe_controls`,
    which is the list granting phase 2 permission to act. Every argument is
    optional so a probe that learned one thing writes one thing.
    """
    import json
    from pathlib import Path

    location = Path(path)
    document = json.loads(location.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{location} is not a profile document")

    if actuation_map:
        existing = document.get("actuation_map")
        document["actuation_map"] = {
            **(existing if isinstance(existing, dict) else {}),
            **actuation_map,
        }
    if focus_behavior:
        document["focus_behavior"] = focus_behavior
    if grid_strategy:
        document["grid_strategy"] = grid_strategy
    if grid_evidence:
        document["grid_evidence"] = grid_evidence

    temporary = location.with_suffix(location.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(location)
    return True
