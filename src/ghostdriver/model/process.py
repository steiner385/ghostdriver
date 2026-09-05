"""What a backend can say about the process behind a target.

Lived in `backends/windows/process.py`, which binds Win32 at import, so no
other backend could name the type it was contracted to return. Nothing
outside that module imported it -- the platform-neutral layer duck-typed it
-- which works right up until a second backend has to guess the shape.

Moved here so both backends fill one definition rather than each keeping a
copy that drifts.

Several fields are Windows-flavoured, because Windows is where they were
first needed. They are kept rather than generalised: `probe/runner.py` writes
every one of them into the profile, and the profile is a document an operator
reads and diffs. A backend with no equivalent says so in the value -- `False`,
`None`, `"unknown"` -- rather than inventing a reading.
"""

from dataclasses import dataclass, field


@dataclass
class ProcessFacts:
    pid: int
    executable: str
    #: "x86" | "x64" | "unknown". On Windows from the PE header; elsewhere
    #: from whatever the platform's equivalent is, or "unknown".
    bitness: str
    #: A 32-bit process on 64-bit Windows. `False` anywhere the concept does
    #: not exist, which is not the same as "checked and it is not".
    wow64: bool
    #: Windows integrity levels. `None` where there is no such concept.
    integrity_level: str | None
    #: Windows per-process DPI awareness. `"unknown"` elsewhere: X11 scaling
    #: is a different model and mapping it here would be a guess dressed as a
    #: measurement.
    dpi_awareness: str
    modules: list[str] = field(default_factory=list)
    #: False when the module list could not be read. `modules` is then empty
    #: because nothing was legible, not because nothing matched.
    modules_readable: bool = True
