"""Which platform backend this process drives the desktop with.

Everything above this package is platform-neutral and asks for the
backend by name: `current()` returns the one for the platform this
process runs on, and every backend answers the same set of names -- the
contract in `CONTRACT` below, which is also the list a new platform has
to fill. The tool layer never imports a platform package directly; a test
holds that line.

Today one backend exists, Windows. Linux is specified (docs/LINUX.md) and
its package answers every name with the same clear refusal until it is
built on a machine that can measure it.
"""

import sys
from typing import Any

#: Every name a backend provides, grouped by what it is for. The Windows
#: package binds each to the module that implements it; a new platform
#: binds each to its own. Missing one is a startup error, not a runtime
#: surprise.
CONTRACT: tuple[str, ...] = (
    # the window tree
    "enumerate_process", "top_level_windows", "process_facts", "descendants",
    "parent_map",
    # reading
    "read_window_text", "is_protected", "capture_window", "CaptureError",
    # modality and state
    "top_level_state", "blocking_ancestor", "snapshot", "surface_of",
    "restore_process",
    # elements that are not windows
    "walk_elements_awake", "is_selected", "_current_value",
    # regions, hosting and assessment
    "region_evidence", "resolve_hosted_app", "assess_uia", "assess_msaa",
    # acting
    "verbs", "NAMED_KEYS", "EDIT_ACTIONS", "button_pair", "read_clipboard_text", "snapshot_clipboard", "restore_clipboard", "deepest_child_at", "ink_fraction", "copy_route", "focus_route",
    # isolation and interference
    "MinimizedWatch", "WatchError", "HiddenDesktop", "InterferenceWatch",
    # the one thing this tool ever puts on the operator's screen
    "OperatorNotice",
    # the raw platform API, for the few callers that need a class name or
    # a foreground handle and nothing more
    "winapi",
)


class UnsupportedPlatform(RuntimeError):
    """No backend drives this platform yet."""


_current: Any = None


def current() -> Any:
    """The backend for this platform, loaded once."""
    global _current
    if _current is None:
        _current = load(sys.platform)
    return _current


def load(platform: str) -> Any:
    """The backend for `platform`; separated from `current` so it is testable."""
    if platform == "win32":
        from .windows import BACKEND as windows_backend
        return windows_backend
    if platform.startswith("linux"):
        from .linux import BACKEND as linux_backend
        return linux_backend
    raise UnsupportedPlatform(
        f"no backend for platform {platform!r}; Windows is implemented and "
        "Linux is specified in docs/LINUX.md"
    )
