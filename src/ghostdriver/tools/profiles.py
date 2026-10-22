"""Which profiles exist, and which fit a target (#242).

A target with a profile on disk was driven unprofiled for two days because
`attach` without `profile_path` loads nothing and said nothing. The match is
offered, never applied: a profile carries policy (a denylist, a cadence), and
silently applying the wrong one is worse than asking for the right one.
"""

import json
import os


def profile_names() -> list[str]:
    """Every profile in the operator directory, by the bare name `attach`
    takes. Backups (anything not ending in .json) are not profiles."""
    from ..operator import OperatorDir, OperatorDirError

    try:
        folder = OperatorDir.resolve().profiles
    except OperatorDirError:
        return []
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.glob("*.json"))


def profile_candidates(executable: str | None) -> list[str]:
    """Profiles for this executable, declared ones first (#246): those whose
    `executables` list names it, then those that only matched through the
    `executable.path` a probe wrote. Case-insensitive, by file name, so the
    same client installed elsewhere still matches."""
    return [name for name, _how in matching_profiles(executable)]


def matching_profiles(executable: str | None) -> list[tuple[str, str]]:
    """(name, "declared" | "probed") for each profile that fits, declared
    first -- a person listing the executable beats a probe having recorded
    it (D35)."""
    if not executable:
        return []
    from ..operator import OperatorDir, OperatorDirError

    try:
        folder = OperatorDir.resolve().profiles
    except OperatorDirError:
        return []
    wanted = _file_name(executable)
    declared_matches, probed_matches = [], []
    for name in profile_names():
        try:
            document = json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if wanted in [_file_name(str(e)) for e in document.get("executables") or []]:
            declared_matches.append((name, "declared"))
            continue
        probed = (document.get("executable") or {}).get("path") if isinstance(
            document.get("executable"), dict) else None
        if probed and _file_name(str(probed)) == wanted:
            probed_matches.append((name, "probed"))
    return declared_matches + probed_matches


def _file_name(path: str) -> str:
    """The file name of a path written for either platform, lower-cased. A
    Windows path read on Linux is one name with backslashes in it to
    `pathlib` there; split on both separators so a profile written on one
    machine matches on the other."""
    return path.replace("\\", "/").rsplit("/", 1)[-1].lower()


def profile_offer(executable: str | None) -> dict:
    """The fields `attach` adds when no profile was loaded: the candidates
    and how to take one. Empty when nothing matches."""
    matches = matching_profiles(executable)
    if not matches:
        return {}
    candidates = [name for name, _how in matches]
    return {
        "profile_candidates": candidates,
        "profile_matched_by": dict(matches),
        "profile_hint": (
            "no profile was loaded, and the operator directory has one for this "
            f"executable: attach again with profile_path=\"{candidates[0]}\""
            + (f" (or one of {candidates[1:]})" if len(candidates) > 1 else "")
            + " to get its control notes, cadences and menu routes."),
    }


def server_generation() -> str:
    """This server process, as a string that changes when it restarts (#242):
    a client holding sessions can tell a restart before its next call fails."""
    import psutil

    pid = os.getpid()
    try:
        started = int(psutil.Process(pid).create_time())
    except psutil.Error:
        started = 0
    return f"{pid}-{started}"
