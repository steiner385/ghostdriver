"""Finding a route to the exact text inside an owner-drawn region.

A grid that paints itself has real data and no windows: `read` returns
nothing, and a capture returns pixels a caller can look at but not trust as
a value (D46). What a caller needs to *verify* a grid is exact text, and the
spec is firm that the routes to it are probed before anything is built on
OCR.

There are three, and they are tried cheapest-first because the cost here is
not speed, it is interference:

1. **A focus-revealed accessible surface.** Some controls populate their
   accessibility tree only once focused. Focusing is close to free and
   touches nothing shared, so it is tried first -- even though a real
   Profile L1 grid showed nothing this way, it is true for other controls
   and costs almost nothing to rule out.

2. **The control's own copy.** Many grids answer `WM_COPY` or Ctrl+C by
   putting tab- and newline-delimited text on the clipboard. This is the
   route most likely to work and the one with a real side effect: the
   Windows clipboard is one shared resource for the whole session, not a
   per-process thing, so a copy overwrites whatever was there and is seen by
   clipboard-history and clipboard managers. Snapshot-and-restore puts the
   prior contents back, but not atomically -- a copy made by anything else
   in the gap loses to the restore. Stated, not hidden.

3. **An export command.** Application-specific and a file write; out of
   scope for a probe and named only so a curator knows it exists.

This module is the decision layer: given what each route yielded, which is
the strategy, and what did it cost. The focusing, the clipboard calls and
the accessibility re-scan are the backend's; they are injected, so the
ordering and the verdicts are testable without a desktop or a clipboard.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class Strategy(str, Enum):
    """How exact text comes out of a region. Recorded in the profile."""

    #: An accessibility surface appears once the region has focus.
    ACCESSIBLE_ON_FOCUS = "accessible_on_focus"
    #: The control copies structured text to the clipboard.
    CLIPBOARD_COPY = "clipboard_copy"
    #: Nothing here yields exact text. Pixels are all there is, and reading
    #: them is OCR, which the spec defers until this returns unknown.
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RouteResult:
    """What one route yielded when tried against the region."""

    strategy: Strategy
    #: True when the route actually produced structured text.
    worked: bool
    #: How many rows/lines the text appeared to hold, when it worked. Shape,
    #: not content -- the sample the profile keeps carries no cell data.
    lines: int = 0
    #: A side effect worth telling an operator about, empty when there was
    #: none. The clipboard route fills this.
    caveat: str = ""
    detail: str = ""


@dataclass(frozen=True, slots=True)
class GridProbe:
    """The routes to try, each a callable the backend supplies.

    A route returns a RouteResult. Absent routes are simply not tried --
    a caller that will not touch the clipboard passes only the focus route,
    and the probe reports UNKNOWN rather than reaching for a route it was
    not given.
    """

    accessible_on_focus: Callable[[], RouteResult] | None = None
    clipboard_copy: Callable[[], RouteResult] | None = None


@dataclass(frozen=True, slots=True)
class GridFinding:
    """What the probe concluded, for the profile and for the operator."""

    strategy: Strategy
    lines: int = 0
    caveat: str = ""
    #: Every route tried and whether it worked, so a reader sees what the
    #: verdict rested on rather than only the winner.
    attempts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        out = {"grid_strategy": self.strategy.value, "attempts": self.attempts}
        if self.lines:
            out["sample_lines"] = self.lines
        if self.caveat:
            out["caveat"] = self.caveat
        return out


def find_grid_strategy(probe: GridProbe) -> GridFinding:
    """Try the routes cheapest-first and report the first that works.

    Order is by interference, not by likelihood: the free accessibility
    route is ruled out before the clipboard is touched, so a region readable
    without a side effect is never read with one. The first route that
    yields structured text wins; if none does, the strategy is UNKNOWN and
    the caller is left to decide whether pixels are worth OCR.
    """
    attempts: list[dict] = []
    ordered = [
        ("accessible_on_focus", probe.accessible_on_focus),
        ("clipboard_copy", probe.clipboard_copy),
    ]
    for name, route in ordered:
        if route is None:
            attempts.append({"route": name, "tried": False})
            continue
        result = route()
        attempts.append({
            "route": name, "tried": True, "worked": result.worked,
            "lines": result.lines, "caveat": result.caveat,
        })
        if result.worked:
            return GridFinding(
                strategy=result.strategy, lines=result.lines,
                caveat=result.caveat, attempts=attempts,
            )
    return GridFinding(strategy=Strategy.UNKNOWN, attempts=attempts)


def looks_like_a_grid(text: str) -> tuple[bool, int]:
    """Whether copied text looks like grid rows, and how many.

    A grid's copy is delimited -- tabs across, newlines down. One long line
    with no tabs is a caption or a status string, not a grid, and reporting
    that as a working route would send a caller to a strategy that returns
    junk. Requires more than one line and at least one tab somewhere.
    """
    if not text:
        return False, 0
    lines = [line for line in text.replace("\r\n", "\n").split("\n") if line]
    if len(lines) < 2:
        return False, len(lines)
    if not any("\t" in line for line in lines):
        return False, len(lines)
    return True, len(lines)
