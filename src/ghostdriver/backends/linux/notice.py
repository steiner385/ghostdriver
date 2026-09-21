"""A notice on the operator's screen, for the one tool that needs a person.

The counterpart of `backends/windows/notice.py`, and the same reason it
exists: `await_human` blocks a tool call, and a person is not necessarily
looking at the chat client while it does. `docs/LINUX.md` proposes an
override-redirect window with `_NET_WM_STATE_ABOVE`, and that is what this
builds -- override-redirect because it is the X11 mechanism for a window no
window manager ever touches, which is a stronger version of "never takes
focus" than asking a WM nicely: there is no WM decision involved at all.

This always runs on the operator's own display, over `display.py`'s shared
connection -- never inside a `HiddenDesktop`'s claim, since the whole point
is that a person sees it. It is the one place in this backend that draws
rather than reads, so it is also the one place that opens a font and a
graphics context, both freed in `close`.

Wayland is out of scope here the same way `docs/LINUX.md` scopes the rest
of this backend to X11 first: the doc's fallback (a layer-shell surface, or
an `org.freedesktop.Notifications` call) is unmeasured.
"""

from __future__ import annotations

import contextlib
import threading
from typing import Any

from . import display

TITLE = "ghostdriver is waiting for you"
WIDTH = 340
PAD = 12
LATER_H = 22
LATER_W = 64
LINE_H = 15
CHAR_W = 6  # the "fixed" font's average advance; good enough to wrap by.


def _wrap(text: str, cols: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if len(candidate) > cols and line:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return lines


class OperatorNotice:
    """Show `ask` in the corner of the operator's screen until closed."""

    def __init__(self, ask: str, *, heading: str = TITLE):
        self.ask = ask
        self.heading = heading
        self.hwnd: int = 0
        self._deferred = False
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._later_box: tuple[int, int, int, int] = (0, 0, 0, 0)

    @property
    def text(self) -> str:
        return (f"{self.heading}\n\n{self.ask}\n\n"
                "It continues on its own once the application shows this done. "
                "Not now? Later defers the ask.")

    @property
    def deferred(self) -> bool:
        return self._deferred

    def show(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="operator-notice")
        self._thread.start()
        self._ready.wait(timeout=3)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        from Xlib import X

        conn = display.connection()
        screen = conn.screen()
        cols = (WIDTH - 2 * PAD) // CHAR_W
        lines = _wrap(self.text, cols)
        height = len(lines) * LINE_H + 2 * PAD + LATER_H + 8

        x = screen.width_in_pixels - WIDTH - 16
        y = screen.height_in_pixels - height - 16

        win = screen.root.create_window(
            x, y, WIDTH, height, 1, screen.root_depth,
            X.InputOutput, X.CopyFromParent,
            background_pixel=screen.white_pixel,
            border_pixel=screen.black_pixel,
            override_redirect=1,
            event_mask=X.ExposureMask | X.ButtonPressMask,
        )
        font = conn.open_font("fixed")
        gc = win.create_gc(foreground=screen.black_pixel,
                           background=screen.white_pixel, font=font)

        self._later_box = (WIDTH - PAD - LATER_W, height - PAD - LATER_H,
                           WIDTH - PAD, height - PAD)

        def draw() -> None:
            win.clear_area(width=WIDTH, height=height)
            for i, line in enumerate(lines):
                win.draw_text(gc, PAD, PAD + LINE_H * (i + 1) - 4, line)
            lx0, ly0, lx1, ly1 = self._later_box
            win.rectangle(gc, lx0, ly0, lx1 - lx0, ly1 - ly0)
            label = "Deferred" if self._deferred else "Later"
            win.draw_text(gc, lx0 + 6, ly1 - 6, label)

        win.map()
        win.configure(stack_mode=X.Above)
        win.change_property(
            conn.get_atom("_NET_WM_STATE"), conn.get_atom("ATOM"), 32,
            [conn.get_atom("_NET_WM_STATE_ABOVE")],
        )
        conn.flush()
        self.hwnd = win.id
        self._ready.set()

        conn.sync()
        while not self._stop.is_set():
            if conn.pending_events() == 0:
                # Polled rather than a blocking `next_event`, so `_stop`
                # (set from another thread) is noticed promptly instead of
                # waiting on an event that may never come.
                self._stop.wait(0.1)
                continue
            event = conn.next_event()
            if event.type == X.Expose:
                draw()
            elif event.type == X.ButtonPress:
                lx0, ly0, lx1, ly1 = self._later_box
                if lx0 <= event.event_x < lx1 and ly0 <= event.event_y < ly1:
                    self._deferred = True
                    draw()
            conn.flush()

        with contextlib.suppress(Exception):
            win.unmap()
            win.destroy()
            font.close()
            conn.flush()
        self.hwnd = 0

    def __enter__(self) -> OperatorNotice:
        self.show()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
