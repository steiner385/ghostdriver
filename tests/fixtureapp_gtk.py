"""The Linux fixture: a GTK application built to be hostile in the ways the
primary target is, and the counterpart of `tests/fixtureapp.py`.

Every shape here exists because a Windows decision was forced by that shape,
and the Linux backend has to be measured against the same ones (docs/LINUX.md).
GTK rather than Qt because GTK ships on every desktop; GTK **4** because that
is what PyGObject offers now, which costs one shape -- `Gtk.Toolbar` was
removed in GTK4, so the icon-only toolbar is a box of icon-only buttons. It
is the same thing for D56's purposes: a row of controls that are not windows
and carry no caption of their own.

Two contracts this file must keep, both easy to break by accident:

* It announces its pid and its X window ids on stdout as one JSON line, like
  the Windows one, so a harness can attach deterministically.
* It **never presents its window.** `present()` raises and focuses, which is
  what a foreground grab *is*; `set_visible(True)` maps without either. The
  grab exists here only as the opt-in disruption, never incidentally, or the
  measurement in L6 -- that the operator's foreground never moves -- could
  not be trusted.

Unlike the Windows fixture, only *toplevels* have X ids: a GTK control is an
AT-SPI accessible, not a window. So the announce carries one xid per toplevel
and the accessible names for everything else, which is what a locator will
have to resolve against.

Run it: `python -m tests.fixtureapp_gtk [flags]`, on a display with an AT-SPI
bus. Nothing here is imported by the test process.
"""

import argparse
import json
import os
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkX11", "4.0")
from gi.repository import Gdk, GdkX11, GLib, Gtk  # noqa: E402

#: The rows the owner-drawn grid paints. It has no children, so nothing but a
#: copy route can give their exact text (D50) -- which is the Linux half of
#: the question issue #1 asks on Windows.
GRID_ROWS = [
    ("BR-1041", "Widget, brass", "12", "4.75"),
    ("BR-1042", "Widget, steel", "3", "11.20"),
    ("BR-1043", "Bracket, long", "40", "0.95"),
]

STATE: dict = {}


def _event(**payload):
    """State changes go to stdout as JSON lines, after the announce line.

    The Windows fixture announces its child pid the same way. It matters more
    here: until the AT-SPI bus is in play (L1) there is no way to read this
    application's labels from outside, so a measurement that needs to know
    whether a control *acted* has nowhere else to look.
    """
    print(json.dumps(payload), flush=True)


def _label(widget, text):
    """An explicit accessible label, so the name a locator matches is chosen
    here rather than inferred from whatever the theme happens to render."""
    widget.update_property([Gtk.AccessibleProperty.LABEL], [text])
    return widget


def _grid_text():
    return "\n".join("\t".join(row) for row in GRID_ROWS)


def _copy_to_clipboard(widget, text):
    provider = Gdk.ContentProvider.new_for_bytes(
        "text/plain;charset=utf-8", GLib.Bytes.new(text.encode("utf-8"))
    )
    widget.get_clipboard().set_content(provider)


# --- the shapes ---------------------------------------------------------------

def _drawn_button(status):
    """D21's "a button that is not a BUTTON": a DrawingArea that paints itself
    and acts only on the press/release *pair*. A press alone does nothing, so
    a driver that synthesises half the pair sees no effect and no error."""
    area = Gtk.DrawingArea(accessible_role=Gtk.AccessibleRole.BUTTON)
    area.set_content_width(140)
    area.set_content_height(32)
    area.set_focusable(True)
    _label(area, "Recalculate")

    def draw(_area, cr, width, height):
        cr.set_source_rgb(0.85, 0.85, 0.88)
        cr.rectangle(0, 0, width, height)
        cr.fill()
        cr.set_source_rgb(0.1, 0.1, 0.1)
        cr.move_to(12, 21)
        cr.show_text("Recalculate")

    area.set_draw_func(draw)

    click = Gtk.GestureClick()
    seen = {"pressed": False}

    def pressed(*_):
        seen["pressed"] = True

    def released(*_):
        if seen["pressed"]:                      # the pair, not the release
            seen["pressed"] = False
            STATE["recalculated"] = STATE.get("recalculated", 0) + 1
            status.set_text(f"recalculated {STATE['recalculated']}")
            _event(event="recalculated", count=STATE["recalculated"])

    click.connect("pressed", pressed)
    click.connect("released", released)
    area.add_controller(click)
    return area


def _bound_entry(mirror):
    """D21's silent split. The committed value is mirrored on focus-out, so a
    value written without going through the toolkit's input path shows in the
    entry while the mirror still holds the old one -- visible only on commit,
    which is exactly how the Windows one hid the bug."""
    entry = Gtk.Entry()
    entry.set_text("original")
    _label(entry, "bound entry")

    # Did the toolkit's own input path see the write? D21's split on Windows
    # was a value that reached the control while the binding never heard of
    # it, so the display and the committed value disagreed. `changed` is what
    # a GTK binding listens to, so reporting it answers the question directly
    # rather than by inference.
    entry.connect("changed", lambda *_: _event(event="bound_changed",
                                               text=entry.get_text()))

    focus = Gtk.EventControllerFocus()

    def commit(*_):
        mirror.set_text(entry.get_text())
        _event(event="bound_committed", text=entry.get_text())

    focus.connect("leave", commit)
    entry.add_controller(focus)
    mirror.set_text(entry.get_text())
    return entry


def _grid(status):
    """An owner-drawn grid: a DrawingArea with no children, so it enumerates
    as one node however many rows it paints. Ctrl+C is the only route to its
    exact text (D50, D65) -- unless --grid-no-copy takes even that away, so a
    prober's honest "no route works" verdict can be tested."""
    area = Gtk.DrawingArea(accessible_role=Gtk.AccessibleRole.TABLE)
    area.set_content_width(340)
    area.set_content_height(90)
    area.set_focusable(True)
    _label(area, "results grid")

    def draw(_area, cr, width, height):
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(0, 0, width, height)
        cr.fill()
        cr.set_source_rgb(0.1, 0.1, 0.1)
        for i, row in enumerate(GRID_ROWS):
            cr.move_to(6, 20 + i * 22)
            cr.show_text("   ".join(row))

    area.set_draw_func(draw)

    keys = Gtk.EventControllerKey()

    def on_key(_c, keyval, _code, mods):
        ctrl = bool(mods & Gdk.ModifierType.CONTROL_MASK)
        if ctrl and keyval in (Gdk.KEY_c, Gdk.KEY_C):
            if STATE["options"].grid_copies:
                _copy_to_clipboard(area, _grid_text())
                status.set_text("grid copied")
                _event(event="grid_copied")
            return True
        return False

    keys.connect("key-pressed", on_key)
    area.add_controller(keys)
    return area


def _toolbar():
    """D56's element form. GTK4 removed Gtk.Toolbar, so this is a box of
    icon-only buttons: controls with no caption of their own, which have to be
    named by role and position or by their accessible label."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    _label(box, "toolbar")
    for icon, name in (("document-new", "New"), ("document-save", "Save"),
                       ("edit-find", "Find")):
        button = Gtk.Button()
        button.set_icon_name(icon)
        _label(button, name)
        # An observable effect, so "the action returned true" can be told
        # apart from "the action did something".
        button.connect("clicked", lambda _b, n=name: _event(event="toolbar", name=n))
        box.append(button)
    return box


def _pages(status):
    """D31's `within=`: two stacked pages whose buttons carry the *same*
    label, so a locator that does not say which page it means is ambiguous --
    and D33 says ambiguity is refused, not guessed at."""
    stack = Gtk.Stack()
    _label(stack, "pages")
    buttons = {}
    for page in ("Details", "Summary"):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        button = Gtk.Button(label="Apply")
        _label(button, "Apply")
        def applied(_b, p=page):
            status.set_text(f"applied on {p}")
            _event(event="applied", page=p)

        button.connect("clicked", applied)
        box.append(Gtk.Label(label=f"{page} page"))
        box.append(button)
        stack.add_titled(box, page.lower(), page)
        buttons[page.lower()] = button
    return stack, buttons


def _tabs():
    notebook = Gtk.Notebook()
    _label(notebook, "tabs")
    for name in ("First", "Second"):
        notebook.append_page(Gtk.Label(label=f"{name} tab body"),
                             Gtk.Label(label=name))
    return notebook


# --- the opt-in disruptions ---------------------------------------------------

def _raise_modal(main, status):
    """A modal on a timer. Modality is not how it looks: it is that the owner
    stops accepting input, which from outside is hard to tell from a hung
    application (D48, and L5 asks what AT-SPI says about it)."""
    dialog = Gtk.Window(title="Confirm")
    dialog.set_transient_for(main)
    dialog.set_modal(True)
    dialog.set_default_size(240, 110)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.append(Gtk.Label(label="The operation needs confirming."))
    ok = Gtk.Button(label="OK")
    _label(ok, "OK")
    ok.connect("clicked", lambda *_: (status.set_text("modal dismissed"),
                                      dialog.close()))
    box.append(ok)
    dialog.set_child(box)
    dialog.set_visible(True)                 # mapped, still never presented
    STATE["modal"] = dialog
    return False


def _hang(seconds):
    """Stop servicing the main loop, without exiting.

    D4's unresponsive control, in the shape Linux gives it. On Windows a
    window whose thread never pumps cannot service WM_GETTEXT and a
    cross-process send hits its timeout. Here the equivalent is worse in
    kind: AT-SPI is D-Bus, so an application that stops running its main
    loop stops answering the *bus*, and a caller with no per-call timeout
    waits on it rather than on one control.
    """
    _event(event="hanging", seconds=seconds)
    time.sleep(seconds)
    _event(event="resumed")
    return False


def _grab_foreground(main, status):
    """The one place present() is called. This is what a foreground grab *is*,
    and it is here so L6 can measure a real one rather than assume."""
    status.set_text("grabbed the foreground")
    main.present()
    return False


# --- build and run ------------------------------------------------------------

def build(options):
    STATE["options"] = options

    status = Gtk.Label(label="ready")
    _label(status, "status")
    mirror = Gtk.Label(label="")
    _label(mirror, "bound mirror")

    main = Gtk.Window(title="Ghostdriver GTK fixture")
    main.set_default_size(520, 460)

    plain = Gtk.Entry()
    plain.set_text("plain")
    _label(plain, "plain entry")

    secret = Gtk.Entry()
    secret.set_visibility(False)             # D37/D38: must read as protected
    secret.set_text("hunter2")
    _label(secret, "password entry")

    # Two ways to hide a value, because they may not look the same to AT-SPI:
    # an Entry told not to show its characters, and the dedicated widget.
    secret2 = Gtk.PasswordEntry()
    secret2.set_text("hunter3")
    _label(secret2, "password widget")

    bound = _bound_entry(mirror)
    drawn = _drawn_button(status)
    grid = _grid(status)
    stack, page_buttons = _pages(status)
    tabs = _tabs()
    toolbar = _toolbar()

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    for child in (toolbar, plain, secret, secret2, bound, mirror, drawn, grid,
                  stack, tabs, status):
        box.append(child)
    main.set_child(box)

    if options.offscreen:
        # Off the operator's view but still mapped, so reads and actuation
        # have something real to work on.
        main.set_default_size(520, 460)
    main.set_visible(True)

    if options.modal_after:
        GLib.timeout_add(options.modal_after, _raise_modal, main, status)
    if options.present_after:
        GLib.timeout_add(options.present_after, _grab_foreground, main, status)
    if options.hang_after:
        GLib.timeout_add(options.hang_after, _hang, options.hang_for)

    # The grid holds focus from the start, so the copy route can be measured
    # without a window manager to route focus for us.
    grid.grab_focus()

    STATE.update(main=main, status=status, grid=grid, bound=bound,
                 mirror=mirror, page_buttons=page_buttons,
                 widgets={"drawn_button": drawn, "grid": grid, "plain_edit": plain,
                          "password": secret, "password_widget": secret2, "bound_edit": bound,
                          "bound_mirror": mirror, "status": status,
                          "tabs": tabs, "toolbar": toolbar, "pages": stack})
    return main


def _bounds(widget, root):
    """A widget's rectangle in its toplevel's coordinates. Reported because a
    control here is an AT-SPI accessible, not a window: there is no per-control
    X id to hit, so a measurement that wants to click one needs the geometry
    from somewhere, and guessing at it is how a negative result gets mistaken
    for "the toolkit ignored the event"."""
    ok, rect = widget.compute_bounds(root)
    if not ok:
        return None
    return {"x": round(rect.origin.x), "y": round(rect.origin.y),
            "w": round(rect.size.width), "h": round(rect.size.height)}


def _xid(window):
    surface = window.get_surface()
    return surface.get_xid() if isinstance(surface, GdkX11.X11Surface) else None


def announce(main):
    """One JSON line, like the Windows fixture. Only toplevels carry an X id;
    everything else is named for AT-SPI, which is the difference the Linux
    backend has to model."""
    return {
        "pid": os.getpid(),
        "display": os.environ.get("DISPLAY"),
        "toolkit": "gtk4",
        "main": _xid(main),
        "accessible": {
            "status": "status",
            "plain_edit": "plain entry",
            "password": "password entry",
            "password_widget": "password widget",
            "bound_edit": "bound entry",
            "bound_mirror": "bound mirror",
            "drawn_button": "Recalculate",
            "grid": "results grid",
            "pages": "pages",
            "page_buttons": "Apply",
            "tabs": "tabs",
            "toolbar": "toolbar",
        },
        "bounds": {name: _bounds(w, main) for name, w in STATE["widgets"].items()},
        "grid_rows": len(GRID_ROWS),
        "grid_copies": bool(STATE["options"].grid_copies),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modal-after", type=int, default=0, metavar="MS",
                        help="raise a modal dialog this long after start; 0 disables")
    parser.add_argument("--present-after", type=int, default=0, metavar="MS",
                        help="grab the foreground this long after start; 0 disables. "
                             "The only thing here that calls present().")
    parser.add_argument("--grid-no-copy", dest="grid_copies", action="store_false",
                        help="make the grid ignore Ctrl+C, so an honest "
                             "'no route works' verdict can be tested")
    parser.add_argument("--hang-after", type=int, default=0, metavar="MS",
                        help="stop servicing the main loop this long after start; "
                             "0 disables. The application stops answering the bus, "
                             "not just one control.")
    parser.add_argument("--hang-for", type=float, default=20.0, metavar="S",
                        help="how long the hang lasts")
    parser.add_argument("--quit-after", type=int, default=0, metavar="MS",
                        help="exit this long after start; for unattended runs")
    parser.set_defaults(offscreen=True, grid_copies=True)
    options = parser.parse_args(argv)

    # Without these the AT-SPI application node comes back named "Unnamed",
    # which leaves a locator nothing to match the *application* on -- the
    # Linux counterpart of the process/main-window pairing D3 does on Windows.
    GLib.set_prgname("ghostdriver-fixture")
    GLib.set_application_name("Ghostdriver GTK fixture")

    if not Gtk.init_check():
        print(json.dumps({"error": "no display"}), flush=True)
        return 2

    window = build(options)
    loop = GLib.MainLoop()

    def first_line():
        print(json.dumps(announce(window)), flush=True)
        if options.quit_after:
            GLib.timeout_add(options.quit_after, lambda: (loop.quit(), False)[1])
        return False

    # One turn of the loop, so the surface exists and has an X id to report.
    GLib.timeout_add(120, first_line)
    loop.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
