"""The Linux web fixture: a GTK3 window embedding a WebKit2GTK view.

The counterpart of `tests/fixturepage.html`'s Windows use in
`tests/test_windows_web.py` (D58) -- the same page, on a GTK host, for L8
(#15). Kept separate from `tests/fixtureapp_gtk.py` rather than folded in:
that fixture's shapes are all native-toolkit ones, and mixing an embedded
engine into the same process would leave L8's measurement unable to tell
whether a finding came from the web view or from something else in that
window.

**GTK 3, not 4, and that is a measurement of its own (D#15).** GTK4's
WebKit binding (`WebKit` 6.0) never published an AT-SPI tree for its
document in any run measured here -- not once, across a dozen attempts and
sixty-second waits. GTK3's (`WebKit2` 4.1) does, and with no wake delay at
all: the document was already complete the first time anything asked.
D75 recorded GTK 3 as unavailable from PyGObject on the host it measured;
it is available here (`gi.require_version("Gtk", "3.0")` succeeds), which
is why this file can use it and the native fixture still does not.

Announces its pid and its X window id on stdout as one JSON line, like the
other fixtures, so a harness can attach deterministically. Never presents
its window, for the same reason as `fixtureapp_gtk.py`: the foreground
grab is the one place that verb belongs, and it is not here.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import GLib, Gtk, WebKit2  # noqa: E402

FIXTURE_PAGE = Path(__file__).parent / "fixturepage.html"


def build():
    window = Gtk.Window(title="Ghostdriver web fixture")
    window.set_default_size(640, 480)
    view = WebKit2.WebView()

    # Reported on stdout because L8's measurement needs to tell "the page
    # finished loading" apart from "the accessibility tree woke": the two
    # turned out not to be the same event (see the module docstring), and a
    # harness that cannot see WebKit's own load state has no way to
    # attribute a delay to one or the other.
    def load_changed(_view, event):
        print(json.dumps({"event": "load_changed", "state": event.value_name}),
              flush=True)

    view.connect("load-changed", load_changed)
    view.load_uri(f"file://{FIXTURE_PAGE.resolve()}")
    window.add(view)
    window.show_all()
    return window


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quit-after", type=int, default=0, metavar="MS",
                        help="exit this long after start; for unattended runs; "
                             "0 disables")
    options = parser.parse_args(argv)

    # Same reason as the GTK fixture: without these the AT-SPI application
    # node comes back "Unnamed", which leaves a locator nothing to match.
    GLib.set_prgname("ghostdriver-web-fixture")
    GLib.set_application_name("Ghostdriver web fixture")

    window = build()

    def first_line():
        print(json.dumps({
            "pid": os.getpid(),
            "display": os.environ.get("DISPLAY"),
            "toolkit": "gtk3+webkit2",
            "main": window.get_window().get_xid(),
        }), flush=True)
        if options.quit_after:
            GLib.timeout_add(options.quit_after, lambda: (Gtk.main_quit(), False)[1])
        return False

    # One turn of the loop, so the surface exists and has an X id to report.
    GLib.timeout_add(200, first_line)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
