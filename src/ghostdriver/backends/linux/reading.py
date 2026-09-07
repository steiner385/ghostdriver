"""Reading a control, under the deadline and the disclosure policy.

Slice 2 of #40. Three contract names, and one of them carries a decision that
the measurements set up but did not settle.

**`is_protected` stays narrow**, meaning role `password text` and nothing
else. It is tempting to widen it to the whole withheld class -- an editable
text entry might be a password and nothing distinguishes them (D#34b) -- and
it would be wrong, because `is_protected` is also what refuses to *type* into
a field (D38, `tools/acting.py`). Widened, the driver could never type into
any text field at all, which is most of what it exists to do. So the
disclosure policy governs *reading* and the role governs *typing*, and they
are deliberately different questions.

**`read_window_text` returns `None` for a field it will not disclose**, and
does not fetch the value to decide. `None` already means "did not answer" in
this contract, which on Windows is unambiguous: the OS refuses the read only
for password fields, so `is_protected` tells the two apart (D37).

Here `None` has three causes -- withheld, protected, and a real timeout
(D#9) -- and `is_protected` separates only one. **A plain text field
therefore reads as though it did not answer**, which is exactly the confusion
D37 was written to prevent, and this slice does not fix it: the fix is a
disclosure opt-in through the contract, which changes a signature Windows
shares. Filed rather than smuggled in.
"""

from __future__ import annotations

import subprocess
from typing import Any

from . import protection
from .deadline import call_with_deadline
from .tree import _accessible


class CaptureError(RuntimeError):
    """A window could not be captured, with the reason the platform gave."""


def _role_and_states(accessible: Any) -> tuple[str, frozenset[str]]:
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    role = call_with_deadline(accessible.get_role_name) or ""
    got = call_with_deadline(accessible.get_state_set)
    states: frozenset[str] = frozenset()
    if got is not None:
        states = frozenset(
            name for name in ("EDITABLE", "FOCUSABLE", "SENSITIVE", "SHOWING")
            if got.contains(getattr(Atspi.StateType, name))
        )
    return role, states


def is_protected(handle: int) -> bool:
    """Whether the toolkit says this control hides its own contents.

    Narrow on purpose: `Gtk.PasswordEntry` carries role `password text` and
    an ordinary entry told not to show its characters carries nothing at all
    (D#34b). This answers the *typing* question, and a wider answer would
    refuse to type into every text field on screen.
    """
    role, _ = _role_and_states(_accessible(handle))
    return role == "password text"


def read_window_text(handle: int, timeout_ms: int = 200) -> str | None:
    """The control's text, or `None` if it did not answer or is not disclosed.

    The value is not fetched for a field that will not be disclosed. Not
    disclosing a value that has already been read is not enough: it exists in
    this process from then on, and reaches a traceback or a log without
    anyone deciding it should (D#34b).
    """
    accessible = _accessible(handle)
    role, states = _role_and_states(accessible)

    def fetch() -> str | None:
        """The contents if the control has any, else its caption.

        Not every control implements `Text` -- a button does not (D#34a) --
        and `WM_GETTEXT` on Windows answers such a window with its caption
        rather than failing. The accessible name is that caption, so the
        fallback keeps the two platforms answering the same question.

        A control that implements `Text` and raises anyway is a control that
        did not answer, and `None` says so.
        """
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi

        if "Text" not in accessible.get_interfaces():
            return accessible.get_name()
        try:
            count = Atspi.Text.get_character_count(accessible)
            return Atspi.Text.get_text(accessible, 0, count)
        except Exception:
            return None

    verdict, value = protection.read(
        role, states,
        read=lambda: call_with_deadline(fetch, timeout_s=timeout_ms / 1000),
    )
    if verdict is not protection.Disclosure.ALLOWED:
        return None
    return value


def capture_window(
    handle: int, *, region: tuple[int, int, int, int] | None = None
) -> tuple[bytes, int, int]:
    """PNG bytes for the window this handle sits in, with its width and height.

    Only toplevels have an X id, and only an X id can be captured -- a
    control is an accessible with no drawable of its own (D#8). So a handle
    anywhere in the tree captures its *window*, and `region` crops to the
    part asked for, which is how a caller gets a picture of one control.

    Captures survive iconification under a compositor, measured pixel-
    identical (D#13) -- which is what makes the minimized strategy possible
    here, and is a property of the compositor rather than of X11.
    """

    xid = _toplevel_xid(_accessible(handle))
    if xid is None:
        raise CaptureError(
            "no X window behind this handle. Only a toplevel has one; a "
            "control is an accessible with no drawable of its own."
        )
    return capture_xid(xid, region=region)


def capture_xid(
    xid: int, *, region: tuple[int, int, int, int] | None = None
) -> tuple[bytes, int, int]:
    """The same capture, for a caller that already knows the X window.

    The watchdog knows its target by xid and must not re-resolve it: picking
    the tree with the most visible nodes flips to a proxy once the target is
    put away, and the watch would then photograph the wrong window forever
    (the reason the Windows watch locks its handle once).
    """
    crop = []
    if region is not None:
        left, top, right, bottom = region
        crop = ["-crop", f"{right - left}x{bottom - top}+{left}+{top}"]
    try:
        done = subprocess.run(
            ["convert", f"x:{xid}", *crop, "png:-"],
            capture_output=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CaptureError(f"the capture command failed: {exc}") from exc
    if done.returncode != 0 or not done.stdout:
        raise CaptureError(
            "the window could not be captured: "
            + (done.stderr.decode("utf-8", "replace").strip() or "no output")
        )
    return done.stdout, *_png_size(done.stdout)


def _toplevel_xid(accessible: Any) -> int | None:
    """Walk up to the frame, and ask X for the window carrying its pid."""

    node = accessible
    while node is not None:
        if (call_with_deadline(node.get_role_name) or "") == "frame":
            break
        node = call_with_deadline(node.get_parent)
    if node is None:
        return None
    pid = call_with_deadline(node.get_process_id)
    try:
        listing = subprocess.run(["xwininfo", "-root", "-children", "-int"],
                                 capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in listing.stdout.splitlines():
        parts = line.split()
        if not parts or not parts[0].isdigit():
            continue
        candidate = int(parts[0])
        if _pid_of(candidate) == pid:
            return candidate
    return None


def _pid_of(xid: int) -> int | None:

    try:
        got = subprocess.run(["xprop", "-id", str(xid), "_NET_WM_PID"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if "=" not in got.stdout:
        return None
    try:
        return int(got.stdout.rsplit("=", 1)[1].strip())
    except ValueError:
        return None


def _png_size(data: bytes) -> tuple[int, int]:
    """Width and height out of the IHDR chunk, so the caller is told the size
    of what it actually got rather than what was asked for."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise CaptureError("the capture is not a PNG")
    return (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))
