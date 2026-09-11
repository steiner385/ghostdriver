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
    "enumerate_process", "top_level_windows", "direct_children", "process_facts", "descendants",
    "parent_map",
    # what the accessibility bus calls a target, when better than the process
    # name -- a sandboxed application's a11y pid is its proxy's, so the two
    # differ (D#101, D#110); None when the process name already suffices.
    "application_name",
    # reading. `disclosure` names the third state: a read can come back
    # empty-handed because the control did not answer, because the platform
    # protects it, or -- on a platform that cannot tell those apart by
    # inspection -- because the driver declined to look (D#43).
    "read_window_text", "is_protected", "disclosure", "capture_window",
    "CaptureError",
    # `confirms_value` answers "does this control show this string" as a
    # yes/no, so a locator can select a control by its current value without
    # the value being disclosed -- the safe half of a place-plus-value
    # locator on a platform that withholds a field's contents (D#34b, D#105).
    "confirms_value",
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


class AccessibilityUnavailable(RuntimeError):
    """The platform is supported; its accessibility service is not running.

    Distinct from `UnsupportedPlatform`, which says this backend does not
    implement something. Here the backend implements it perfectly well and
    the service it depends on is absent -- a headless box, a container, a
    session with no `DISPLAY`, or a desktop where nobody enabled
    accessibility. That is an ordinary condition, not a defect, and the two
    call for completely different things from a caller.

    It exists because the alternative was **the process dying**. AT-SPI
    reports a failed bus connection through GLib's `g_error()`, which is
    fatal by contract: it aborts with SIGTRAP, with no Python exception to
    catch and no result to return (#58). So the bus is checked before it is
    reached for, and this is what that check raises.

    Not a CONTRACT name: nothing on Windows can raise it, and a name every
    backend must implement is the wrong shape for a condition only one of
    them has.
    """


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
