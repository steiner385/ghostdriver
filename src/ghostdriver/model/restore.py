"""What `restore_process` did, and what it cost.

Lived in `backends/windows/restore.py`, which binds Win32 at import, so no
other backend could name the type it was contracted to return. The move is
the one D#40a made for `ProcessFacts`, for the same reason and with the same
shape: one definition both backends fill, rather than a copy per backend
that drifts.

The two `foreground_*` fields are the point of the type rather than
bookkeeping. This is the only part of the tool that changes what the person
sees, so the claim about what it cost them is *measured on every call*
instead of asserted once in a test and assumed forever after.

That mattered less on Windows, where `show_no_activate` un-minimizes without
focusing. On Linux there is no such route -- D#14 measured that un-hiding a
window and focusing it are one operation under GNOME Shell, and a bare map
does nothing at all -- so `took_foreground` is expected to be True there
whenever anything was restored. The field records the difference between the
platforms instead of hiding it.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RestoreResult:
    #: The windows this call acted on -- minimized on Windows, hidden on
    #: Linux. Empty means nothing needed restoring, which is why calling
    #: `restore_process` before a read is safe and idempotent.
    restored: tuple[int, ...]
    visible_before: tuple[int, ...]
    visible_after: tuple[int, ...]
    foreground_before: int
    foreground_after: int

    @property
    def took_foreground(self) -> bool:
        return self.foreground_before != self.foreground_after

    @property
    def newly_visible(self) -> tuple[int, ...]:
        before = set(self.visible_before)
        return tuple(h for h in self.visible_after if h not in before)

    @property
    def note(self) -> str:
        """What happened, in a sentence -- never claiming more than the
        screen showed. Asking is not restoring: on GNOME 50's headless shell
        an X client's activation is refused and nothing comes back (#217)."""
        if not self.restored:
            return "nothing was minimized"
        if not self.newly_visible:
            return (f"asked to restore {len(self.restored)} window(s); none came "
                    "back on screen -- the window manager declined")
        return "the application re-showed its own forms"
