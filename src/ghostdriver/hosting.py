"""When the process that owns a window is not the process that owns the app.

`list_targets` presents a mapping from process to windows and treats it as
the whole truth. It is not. Some processes own windows on behalf of *other*
processes, and the application whose UI you can see may be running somewhere
else entirely.

The case this module knows about is the UWP frame host. Measured live:

    ApplicationFrameHost   ApplicationFrameWindow      rect (-7,-7,1543,919)
    SystemSettings.exe     Windows.UI.Core.CoreWindow  rect (-25600,-25600,...)

Both are top-level; **neither is the other's parent or owner**. The frame you
see belongs to the host, the application's own window is parked off-screen,
and nothing in the window tree connects them. So a caller who attaches to the
pid owning the visible window profiles a title bar, and nothing says so.

This module does not try to pair them -- there is nothing to follow. It
recognises both ends and says what each is.

**Two strengths of claim, deliberately kept apart.** A process owning a frame
window is a weak signal: a shell can own one among dozens of windows of its
own, and telling its user that "anything measured here describes a frame"
would be false. The strong claim applies to a single window: when the window
actually selected for measurement *is* a hosted frame, everything measured
from it describes the frame. Only the second is a warning.

The general problem is larger than UWP -- process-per-tab browsers and other
broker architectures have the same shape. See docs/DECISIONS.md.
"""

import fnmatch

#: Classes belonging to a window hosted on behalf of another process.
FRAME_HOST_CLASSES: tuple[str, ...] = ("ApplicationFrameWindow",)

#: Classes belonging to an application whose visible frame is hosted
#: elsewhere. This is the process worth attaching to.
HOSTED_APP_CLASSES: tuple[str, ...] = ("Windows.UI.Core.CoreWindow",)


def _matches(class_name: str, patterns: tuple[str, ...]) -> bool:
    lowered = class_name.lower()
    return any(fnmatch.fnmatch(lowered, p.lower()) for p in patterns)


def is_frame_host(class_name: str) -> bool:
    return _matches(class_name, FRAME_HOST_CLASSES)


def is_hosted_app(class_name: str) -> bool:
    return _matches(class_name, HOSTED_APP_CLASSES)


#: The strong claim: this window belongs to somebody else's application.
MEASURED_A_FRAME_NOTE = (
    "The window measured here is a frame hosted on behalf of another "
    "process. Everything in this result describes the frame, not the "
    "application -- which runs elsewhere, in a process owning a "
    "Windows.UI.Core.CoreWindow. Attach to that instead."
)

#: The weak claim: some of this process's windows are not its own.
HOSTS_FRAMES_NOTE = (
    "Some of this process's windows are frames hosted for other "
    "applications, so not every window here belongs to it. It may also have "
    "a UI of its own."
)

HOSTED_APP_NOTE = (
    "An application whose visible frame is hosted by another process. This "
    "is the process worth attaching to; its own window may be parked "
    "off-screen while the application is suspended."
)


def classify_process(class_names: list[str]) -> tuple[str | None, str]:
    """The weak, process-level claim, for a target listing.

    Returns (kind, note) where kind is "hosts-frames", "hosted-app" or None.
    Never asserts that a measurement is wrong -- a process can host frames
    and still have windows of its own, and a shell does exactly that.
    """
    if any(is_frame_host(c) for c in class_names):
        return "hosts-frames", HOSTS_FRAMES_NOTE
    if any(is_hosted_app(c) for c in class_names):
        return "hosted-app", HOSTED_APP_NOTE
    return None, ""


def note_for_measured_window(root_class: str) -> str:
    """The strong claim, for a result measured from one specific window.

    Empty unless that window is itself a hosted frame, in which case
    everything measured from it describes the frame.
    """
    return MEASURED_A_FRAME_NOTE if is_frame_host(root_class) else ""
