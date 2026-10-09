"""One X connection, and the handful of facts the watches ask of it.

The watches poll -- whether the target is on screen, whether it holds the
front, where the pointer is -- and they poll often. Asking `xprop` per sample
would spawn two processes per poll, so this keeps a real connection open and
answers from it.

Every fact here was measured before it was coded:

* **Hidden, not unmapped.** A compositing window manager leaves an iconified
  window `IsViewable`, so map state does not move and `_NET_WM_STATE_HIDDEN`
  is the signal (D#13).
* **Un-hiding focuses.** There is no route that reveals a window without
  activating it, so `restore` hands over the foreground by necessity rather
  than by choice (D#14).
* **One connection per claimant, not one connection total.** `HiddenDesktop`
  (#40 slice 5b) needs its own, to a different `DISPLAY`, from inside the
  same process that may already hold one to the operator's -- unlike AT-SPI
  (`desktop_claim.py`), Xlib has no vendor limit on that, so the cache below
  is keyed by `desktop_claim.effective_owner()` rather than being a single
  slot.
"""

from __future__ import annotations

import contextlib
import os
import threading
from collections.abc import Iterator
from typing import Any

from .. import AccessibilityUnavailable, UnsupportedPlatform
from . import desktop_claim, session_type

_LOCK = threading.Lock()
_DISPLAYS: dict[str, Any] = {}
#: Per claimant: is its X server Xwayland? Asked once (`_is_xwayland`).
_XWAYLAND: dict[str, bool] = {}


@contextlib.contextmanager
def _x_errors_ignored() -> Iterator[None]:
    """`contextlib.suppress(Exception)`, except for a platform refusal.

    Every fact here degrades to a default when X errors -- a window gone
    mid-read is ordinary. A Wayland desktop is not: "not hidden", "gone",
    "not modal" would each be a confident wrong answer, so `X11Only` (an
    `UnsupportedPlatform`) passes through (#215).
    """
    try:
        yield
    except UnsupportedPlatform:
        raise
    except Exception:
        pass


def _display() -> Any:
    """The connection for whoever is asking right now, opened once each.

    Not per-call: opening an X connection costs a round trip, and a watch
    that opened one per sample would spend more time connecting than looking.
    Cached per claimant (see the module docstring) rather than once for the
    whole process, so a hidden-desktop claim gets a connection to its own
    `DISPLAY` without disturbing a connection already open to the operator's.

    The second of this backend's two external dependencies, and the one a
    machine can be missing while having the other. #58 guarded the
    accessibility bus after a box with no bus aborted the process; a box
    *with* a bus and no `DISPLAY` then failed here instead, with a raw
    `Xlib.error.DisplayNameError` reaching the caller as an unexpected
    error. Two services, two preflights -- and each machine hid the other's
    gap, which is why this was found by running on both.

    Reported as the same `AccessibilityUnavailable`, because to a caller it
    is the same fact: the desktop this backend reads is not there.
    """
    owner = desktop_claim.effective_owner()
    if session_type.display_server(owner) == "wayland":
        # XWayland would answer, about X clients only (#215).
        session_type.require_x11("this call")
    return _connect(owner)


def _open(display_name: str | None) -> Any:
    """Open an X connection, or say why not.

    A seam of its own so the probe below can be tested without an X server
    -- and without Xlib, which is why both imports live here: a test that
    replaces this must not need Xlib installed (Windows CI does not have it).
    """
    from Xlib import display, error

    try:
        return display.Display(display_name)
    except (error.DisplayNameError, error.DisplayConnectionError) as exc:
        raise AccessibilityUnavailable(
            f"cannot open the X display: {exc}. This backend reads "
            "the window manager over X, so it needs a DISPLAY "
            "pointing at a running server -- on a headless box that "
            "has to be arranged deliberately, for instance with Xvfb."
        ) from exc


def _is_xwayland(owner: str) -> bool:
    """Whether `owner`'s X server is Xwayland -- asked once, of the server
    itself, for when the environment does not say (#215). A server that
    cannot be reached is not answered here: `_display` reports that."""
    if owner not in _XWAYLAND:
        try:
            conn = _connect(owner)
        except AccessibilityUnavailable:
            return False
        _XWAYLAND[owner] = "XWAYLAND" in conn.list_extensions()
    return _XWAYLAND[owner]


session_type.register_server_probe(_is_xwayland)


def _connect(owner: str) -> Any:
    """The cached connection for `owner`, opened on first use."""
    with _LOCK:
        conn = _DISPLAYS.get(owner)
        if conn is None:
            desktop_claim.claim()
            # Explicit rather than ambient: swapping `os.environ["DISPLAY"]`
            # process-wide would race any other thread reaching for its own
            # first connection (a watch on an unrelated, ordinary session),
            # so a hidden desktop's own DISPLAY, registered at `prepare`
            # time, is passed straight to `Display()` instead. The
            # operator's own claim registers nothing, which is correct --
            # `Display()` with no argument reads the ambient environment,
            # which for the operator's own desktop is exactly right.
            registered = desktop_claim.environment_for(owner)
            display_name = registered.get("DISPLAY")
            cookie = registered.get("XAUTHORITY")
            if cookie is None:
                conn = _open(display_name)
            else:
                # A nested Xwayland wants its own cookie (#217), and Xlib
                # reads it from the environment at connect time with no
                # argument to pass it by. Swapped only for the open, inside
                # the lock every open takes, so no other connection can see
                # it.
                previous = os.environ.get("XAUTHORITY")
                os.environ["XAUTHORITY"] = cookie
                try:
                    conn = _open(display_name)
                finally:
                    if previous is None:
                        os.environ.pop("XAUTHORITY", None)
                    else:
                        os.environ["XAUTHORITY"] = previous
            _DISPLAYS[owner] = conn
        return conn


def _atom(name: str) -> int:
    return _display().intern_atom(name)


def _prop(window: Any, name: str) -> Any:
    with _x_errors_ignored():
        got = window.get_full_property(_atom(name), 0)
        if got is not None:
            return got.value
    return None


def _root() -> Any:
    return _display().screen().root


def window_pid(xid: int) -> int | None:
    """The process behind a window: `_NET_WM_PID`, else what the X server
    itself says.

    A sandboxed application sets no `_NET_WM_PID` at all -- every Bambu
    Studio top-level answers "not found" (D#101) -- and a listing that
    trusted the property alone would never see it. The X server knows the
    pid of every client from the socket it connected on, and the XRes
    extension hands it over (`LocalClientPIDMask`). Measured on Studio:
    1461891, the real application process, where `_NET_WM_PID` had nothing.
    """
    with _x_errors_ignored():
        value = _prop(_display().create_resource_object("window", xid), "_NET_WM_PID")
        if value:
            return int(value[0])
    with _x_errors_ignored():
        from Xlib.ext import res

        reply = res.query_client_ids(
            _display(), [{"client": xid, "mask": res.LocalClientPIDMask}])
        for client in reply.ids:
            if client.spec.mask & res.LocalClientPIDMask and client.value:
                return int(client.value[0])
    return None


# --- the two identifier spaces, bridged (D#101, D#110) -----------------------

#: xids the tree has correlated with an a11y application pid, by matching a
#: frame's accessible name and size against the client list. Filled by
#: `tree.enumerate_process`; read by `windows_of`. A sandboxed application's
#: windows can be attributed no other way, because its a11y pid is its D-Bus
#: proxy's and its X client pid is the real process -- two host pids, one
#: window, and neither on the window itself.
_ATTRIBUTED: dict[int, set[int]] = {}
#: a11y pid -> real pids learned from those windows (XRes), so a caller
#: holding the a11y pid can be told the process family it actually is.
_ALIASES: dict[int, set[int]] = {}


def attribute(pid: int, xid: int) -> None:
    """Record that window `xid` belongs to the target known by `pid`."""
    _ATTRIBUTED.setdefault(pid, set()).add(xid)
    real = window_pid(xid)
    if real is not None and real != pid:
        _ALIASES.setdefault(pid, set()).add(real)


def aliases(pid: int) -> set[int]:
    """The real pids the X server attributes `pid`'s windows to, when they
    differ from `pid` itself. Empty for an ordinary process."""
    return set(_ALIASES.get(pid, ()))


def forget_attributions(pid: int) -> None:
    _ATTRIBUTED.pop(pid, None)
    _ALIASES.pop(pid, None)


def is_hidden(xid: int) -> bool:
    """Whether the window manager considers this window put away.

    `_NET_WM_STATE_HIDDEN`, not map state: under a compositor an iconified
    window stays `IsViewable` and asking the Windows question answers wrongly
    (D#13).
    """
    with _x_errors_ignored():
        window = _display().create_resource_object("window", xid)
        states = _prop(window, "_NET_WM_STATE") or []
        return _atom("_NET_WM_STATE_HIDDEN") in list(states)
    return False


def exists(xid: int) -> bool:
    """Whether the window is still there -- the counterpart of `IsWindow`."""
    try:
        _display().create_resource_object("window", xid).get_attributes()
        return True
    except UnsupportedPlatform:
        raise
    except Exception:
        return False


def connection() -> Any:
    """The shared connection for whoever is asking, exposed for the one
    caller that needs the raw Xlib object rather than a fact read through
    it: `notice.py`, which draws a window instead of reading one."""
    return _display()


def wm_present() -> bool:
    """Whether a window manager has attached to this display yet.

    `_NET_SUPPORTING_WM_CHECK` is what a WM sets on the root window to
    announce itself; a bare `Xvfb` never sets it (D75). `HiddenDesktop`
    polls this while bringing gnome-shell up, since `_NET_CLIENT_LIST` and
    `_NET_ACTIVE_WINDOW` -- what the rest of this module reads -- come from
    the WM, not the server, and answer nothing until one is there.
    """
    return _prop(_root(), "_NET_SUPPORTING_WM_CHECK") is not None


def client_windows() -> list[int]:
    """Every managed top-level, from `_NET_CLIENT_LIST`.

    This comes from the *window manager*, not the X server, which is why a
    bare `Xvfb` has none of it (D75) and why the nested display runs one.
    """
    return [int(x) for x in (_prop(_root(), "_NET_CLIENT_LIST") or [])]


def windows_of(pid: int) -> list[int]:
    """Every managed top-level belonging to `pid`, in client-list order.

    The counterpart of Win32 `top_level_windows`, and deliberately *not*
    routed through AT-SPI: a modal is a window-manager fact, and the
    accessibility tree does not carry one (D#12).

    Three ways a window belongs to `pid`, because a sandboxed target has
    three identities (D#101): the X server attributes it to `pid` (or to a
    real pid the tree has learned is `pid`'s); the tree attributed it by
    matching a frame; or it is *transient for* one that does -- which is how
    a modal dialog, itself never an a11y frame until shown, is found.
    """
    owned = {pid, *_ALIASES.get(pid, ())}
    known = set(_ATTRIBUTED.get(pid, ()))
    listing = client_windows()
    found = {x for x in listing if x in known or window_pid(x) in owned}
    # Transient-for closure, bounded: a dialog of a dialog is still ours.
    for _ in range(4):
        more = {x for x in listing if x not in found and transient_for(x) in found}
        if not more:
            break
        found |= more
    return [x for x in listing if x in found]


def press_key(keysym_name: str) -> bool:
    """One real key press and release through XTest -- tier 4 (D#111).

    Real input, not a sent event: D#11 measured GTK discarding `XSendEvent`
    in every configuration, and XTest is what a person's keyboard is to the
    server. It lands wherever focus is, which is exactly why the only caller
    checks the foreground first and again just before this.
    """
    from Xlib import XK, X
    from Xlib.ext import xtest

    display = _display()
    keysym = XK.string_to_keysym(keysym_name)
    if not keysym:
        return False
    keycode = display.keysym_to_keycode(keysym)
    if not keycode:
        return False
    with _LOCK:
        xtest.fake_input(display, X.KeyPress, keycode)
        xtest.fake_input(display, X.KeyRelease, keycode)
        display.sync()
    return True


def press_chord(letter: str, *, ctrl: bool = False, shift: bool = False) -> bool:
    """A modified keystroke through XTest -- e.g. Ctrl+C. Tier 4 (D#111).

    Real modifiers, held down around the letter and released after, because
    a sent event's modifier state is ignored (D#11); XTest presses the
    actual modifier keys. Used only by the clipboard routes inside a live
    session.
    """
    from Xlib import XK, X
    from Xlib.ext import xtest

    display = _display()
    keycode = display.keysym_to_keycode(XK.string_to_keysym(letter))
    if not keycode:
        return False
    ctrl_kc = display.keysym_to_keycode(XK.string_to_keysym("Control_L"))
    shift_kc = display.keysym_to_keycode(XK.string_to_keysym("Shift_L"))
    with _LOCK:
        if ctrl:
            xtest.fake_input(display, X.KeyPress, ctrl_kc)
        if shift:
            xtest.fake_input(display, X.KeyPress, shift_kc)
        xtest.fake_input(display, X.KeyPress, keycode)
        xtest.fake_input(display, X.KeyRelease, keycode)
        if shift:
            xtest.fake_input(display, X.KeyRelease, shift_kc)
        if ctrl:
            xtest.fake_input(display, X.KeyRelease, ctrl_kc)
        display.sync()
    return True


def window_name(xid: int) -> str:
    """`_NET_WM_NAME`, falling back to `WM_NAME`.

    The EWMH property is UTF-8 and the ICCCM one is Latin-1, and a GTK
    application sets both. Preferring the first is what keeps a non-ASCII
    title readable.
    """
    for prop in ("_NET_WM_NAME", "WM_NAME"):
        value = _prop(_display().create_resource_object("window", xid), prop)
        if value:
            with _x_errors_ignored():
                if isinstance(value, bytes):
                    return value.decode("utf-8", "replace")
                return str(value)
    return ""


def window_class(xid: int) -> str:
    """The application's class, from `WM_CLASS`.

    Two NUL-terminated strings -- the instance name, then the class name --
    and the second is the one that identifies the application.
    """
    value = _prop(_display().create_resource_object("window", xid), "WM_CLASS")
    if not value:
        return ""
    text = value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
    parts = [p for p in text.split("\x00") if p]
    return parts[-1] if parts else ""


def is_modal(xid: int) -> bool:
    """Whether the window declares itself modal.

    This is the whole of the Linux modality signal. Nothing goes disabled --
    the owner keeps `SENSITIVE` for the modal's entire life -- so a driver
    that does not read this cannot tell a held application from a working
    one (D#12).
    """
    with _x_errors_ignored():
        window = _display().create_resource_object("window", xid)
        states = _prop(window, "_NET_WM_STATE") or []
        return _atom("_NET_WM_STATE_MODAL") in list(states)
    return False


def transient_for(xid: int) -> int:
    """The window this one is transient for, or 0.

    `WM_TRANSIENT_FOR` is what a modal names its owner with, and it maps
    straight onto the `owner` field `TopLevel` already carries -- so on this
    platform ownership is *stated* rather than derived, which is a better
    position than Windows (D#12).
    """
    with _x_errors_ignored():
        window = _display().create_resource_object("window", xid)
        value = _prop(window, "WM_TRANSIENT_FOR")
        if value:
            return int(value[0])
    return 0


def geometry(xid: int) -> tuple[int, int, int, int]:
    """The window's size, as `(0, 0, width, height)`.

    Size only, and the zeros are deliberate. AT-SPI reports a top-level
    frame at the origin under GTK4/X11 -- measured 0,0 for both the main
    window and a modal that X placed at (259, 275) -- so a position taken
    from one layer cannot be compared with a position from the other. Size
    is the part both agree on, exactly, and it is the part this backend
    uses to tell two frames of one process apart.
    """
    with _x_errors_ignored():
        got = _display().create_resource_object("window", xid).get_geometry()
        return (0, 0, got.width, got.height)
    return (0, 0, 0, 0)


def active_window() -> int | None:
    """The focused top-level, or None when nothing holds the front."""
    value = _prop(_root(), "_NET_ACTIVE_WINDOW")
    if not value or not int(value[0]):
        return None
    return int(value[0])


def foreground_pid() -> int:
    """The process holding the front, or 0. The shape `InterferenceWatch`
    expects, so 0 means "nothing" rather than raising."""
    xid = active_window()
    if xid is None:
        return 0
    return window_pid(xid) or 0


def cursor() -> tuple[int, int]:
    """Where the pointer is, in root coordinates."""
    with _x_errors_ignored():
        pointer = _root().query_pointer()
        return (pointer.root_x, pointer.root_y)
    return (0, 0)


def iconify(xid: int) -> None:
    """Put a window away without activating it.

    A `WM_CHANGE_STATE` client message to the root, which is what ICCCM
    specifies and what `xdotool windowminimize` sends -- so this is the call
    D#13 actually measured as non-activating. Unmapping the window directly
    would go around the window manager, which then has no idea the window is
    iconic and will not report `_NET_WM_STATE_HIDDEN`.

    There is no counterpart that *un*-hides quietly: restoring is activating
    (D#14).
    """
    from Xlib import X, Xutil

    display = _display()
    window = display.create_resource_object("window", xid)
    with _x_errors_ignored():
        event = _protocol_event(window, _atom("WM_CHANGE_STATE"),
                                [Xutil.IconicState, 0, 0, 0, 0])
        _root().send_event(
            event,
            event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask,
        )
        display.sync()


def activate(xid: int) -> None:
    """Un-hide a window, which also focuses it. There is no other version.

    `_NET_ACTIVE_WINDOW`, because D#14 measured that it is the only route
    that works: a bare `XMapWindow` leaves `_NET_WM_STATE_HIDDEN` in place
    and does nothing at all -- not half a restore, nothing -- while an
    activation restores and focuses in the same motion.

    So this is deliberately not called `restore`. Naming it for the
    un-hiding half would hide the foreground change inside it, and on this
    window manager the foreground change is not separable (D#14). The only
    caller is `restore_process`, which exists to hand the window back to the
    person and is the one place a focus change is legitimate (D4).

    Source indication 2 -- "a pager" -- rather than 1, "an application".
    A window manager applies focus-stealing prevention to applications and
    honours pagers, and this is acting on the operator's explicit request.
    """
    from Xlib import X

    display = _display()
    window = display.create_resource_object("window", xid)
    with _x_errors_ignored():
        event = _protocol_event(
            window, _atom("_NET_ACTIVE_WINDOW"), [2, X.CurrentTime, 0, 0, 0]
        )
        _root().send_event(
            event,
            event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask,
        )
        display.sync()


def _protocol_event(window: Any, message_type: int, data: list[int]) -> Any:
    from Xlib import protocol

    return protocol.event.ClientMessage(
        window=window, client_type=message_type, data=(32, data),
    )
