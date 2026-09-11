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


def disclosure(handle: int) -> str:
    """Why a read of this control may come back empty-handed: the third state.

    `"allowed"`, `"protected"` or `"withheld"`. The last is the one this
    platform has and Windows does not: an editable entry whose contents are
    hidden is *identical* to a plain one across every surface AT-SPI
    exposes, so the driver declines to look at either (D#34b).

    Without this name, `None` from `read_window_text` meant three different
    things at once and `is_protected` separated only the declared widget --
    so a perfectly healthy text field read exactly like a hung one, which is
    the confusion D37 exists to prevent, arriving from the other direction.

    Answering this costs no read of the value: the verdict comes from the
    role and states alone, so asking is safe on a field whose contents must
    not be fetched (D#43).
    """
    role, states = _role_and_states(_accessible(handle))
    return protection.classify(role, states).value


def read_window_text(handle: int, timeout_ms: int = 200, *,
                     disclose: bool = False) -> str | None:
    """The control's text, or `None` if it did not answer or is not disclosed.

    The value is not fetched for a field that will not be disclosed. Not
    disclosing a value that has already been read is not enough: it exists in
    this process from then on, and reaches a traceback or a log without
    anyone deciding it should (D#34b).

    `disclose=True` is a caller saying it has thought about it and wants the
    contents of a *withheld* field anyway. It does **not** override
    `protected`: a control the toolkit declares a password field is never
    disclosed, at any grain, because that one is not a guess (D#34b).

    The asking is what belongs in the trace, never the answer (D62) -- the
    tool layer records that disclosure was requested, so an operator reading
    back a session can see a value was exposed without the value itself
    being written down.
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
        disclose=disclose,
    )
    if verdict is protection.Disclosure.PROTECTED:
        return None
    if verdict is protection.Disclosure.WITHHELD and not disclose:
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


def confirms_value(handle: int, expected: str) -> bool | None:
    """Whether the control currently shows `expected`, without disclosing it.

    This is what makes a place-plus-value locator safe on a platform that
    withholds a field's contents by class (D#34b, D#105): the answer is a
    yes or a no, so the value never reaches a result, a trace or a model's
    context. `None` means the control did not answer within the deadline
    (D#9) -- not a match, and not a mismatch either.

    A *protected* field (role `password text`) answers None: its contents
    are never fetched at any grain, so they cannot be confirmed, and a
    caller must not be able to probe a password by guessing values.
    """
    accessible = _accessible(handle)
    role, states = _role_and_states(accessible)

    def fetch() -> str | None:
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

    return protection.confirms(
        role, states, expected=expected,
        read=lambda: call_with_deadline(fetch),
    )


def ink_fraction(handle: int, *,
                 region: tuple[int, int, int, int] | None = None) -> float:
    """How much of the window's rendering is not its background colour.

    The same question the Windows `ink_fraction` answers (D66): a control
    that reads empty but paints content has a broken read path, not empty
    content. The most common colour is the background; every other pixel is
    ink. Computed over a downscaled capture so a large region is bounded
    work -- the question is "blank or not", not "what".
    """
    xid = _toplevel_xid(_accessible(handle))
    if xid is None:
        return 0.0
    return ink_fraction_xid(xid, region=region)


def ink_fraction_xid(xid: int, *,
                     region: tuple[int, int, int, int] | None = None) -> float:
    crop = []
    if region is not None:
        left, top, right, bottom = region
        crop = ["-crop", f"{right - left}x{bottom - top}+{left}+{top}"]
    try:
        done = subprocess.run(
            ["convert", f"x:{xid}", *crop, "-resize", "128x128>", "ppm:-"],
            capture_output=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0.0
    return _ink_of_ppm(done.stdout)


def _ink_of_ppm(data: bytes) -> float:
    """1 - (most common pixel fraction), from a binary PPM (P6)."""
    if not data.startswith(b"P6"):
        return 0.0
    # header: P6 <w> <h> <maxval>, whitespace-separated, then binary
    fields: list[bytes] = []
    i = 2
    while len(fields) < 3 and i < len(data):
        while i < len(data) and data[i] in b" \t\n\r":
            i += 1
        start = i
        while i < len(data) and data[i] not in b" \t\n\r":
            i += 1
        fields.append(data[start:i])
    i += 1  # the single whitespace after maxval
    try:
        width, height, _maxval = (int(f) for f in fields)
    except ValueError:
        return 0.0
    pixels = data[i:i + width * height * 3]
    counts: dict[bytes, int] = {}
    total = 0
    for p in range(0, len(pixels) - 2, 3):
        px = pixels[p:p + 3]
        counts[px] = counts.get(px, 0) + 1
        total += 1
    if not total:
        return 0.0
    return round(1.0 - max(counts.values()) / total, 3)
