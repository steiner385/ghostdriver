"""grid_seek: read an owner-drawn grid a page at a time (D63)."""

from ..model.result import ErrorKind, GhostdriverError
from .acting import _ActingCore
from .core import _element, _error
from .guidance import CLIPBOARD_NOT_ALLOWED, text_guard


class SeekTools(_ActingCore):
    """Paging an owner-drawn grid to read it and find a value in it."""

    #: How many rows a single copy is expected to yield before it is treated
    #: as runaway. A grid page is tens of rows, not thousands.
    _SEEK_MAX_ROWS = 5000
    #: Copies in a row that may fail before the seek stops and says so. The
    #: clipboard is shared with the person and with every other program, so
    #: one copy that did not land is an ordinary event; two running is the
    #: route not answering (#182).
    _SEEK_MAX_FAILED_COPIES = 2

    def grid_seek(
        self,
        session_id: str,
        locator: str,
        *,
        value: str | None = None,
        advance: str = "pagedown",
        max_pages: int = 50,
        all_windows: bool = False,
    ) -> dict:
        """Read an owner-drawn grid a page at a time, by copying each view
        and paging with a caret key, until a value is found or the view
        stops changing.

        A target made of grids that yield their rows only to their own Copy
        command, and only the rows in view, has no primitive for "is this
        value in the grid, and where" -- and every caller would otherwise
        write the paging loop, badly (D63). This is that loop: copy the
        current rows (the clipboard route, `probe_grid`'s), match `value`
        against them if one was given, then post `advance` to the grid and
        copy again; stop when the value is found, when a copy repeats the
        one before it (the end, or a key the grid did not act on), or at
        `max_pages`.

        Full tier, the same rails as `probe_grid`: the region is named by
        the caller and matches exactly one; a denylisted caption, a held
        application, or a region that already answers `read` is refused --
        that last one waived for a class the profile's `text_is_label`
        names, since a real grid's text query answered with a static label
        rather than its rows (D#141).
        Paging depends on the grid acting on a posted key, which -- like a
        posted click (D64) -- a control may decline when its window is not
        the thread's active one; a view that never changes says so, and the
        keyboard landing is then a step for a person.
        """
        try:
            session = self.sessions.authorize(session_id, "grid_seek")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)
        node, failure = self._one(session, locator, all_windows)
        if failure is not None:
            return failure
        try:
            self.sessions.check_caption(session_id, node.text)
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message, locator=locator)

        from ..backends import current

        if session.run(lambda: current().blocking_ancestor(node.handle)) is not None:
            return _error(ErrorKind.NOT_ACTIONABLE,
                          "the application is held by a dialog; deal with it first")
        refusal, waiver = text_guard(session.profile, node, locator)
        if refusal is not None:
            return _error(ErrorKind.NOT_ACTIONABLE, refusal)
        if not session.clipboard:
            return _error(ErrorKind.DENIED_BY_POLICY, CLIPBOARD_NOT_ALLOWED, locator=locator)
        if advance.lower() not in current().NAMED_KEYS:
            return _error(ErrorKind.NOT_ACTIONABLE,
                          f"advance must be a named key (e.g. pagedown, down), not {advance!r}")

        copy_route = current().copy_route
        verbs = current().verbs

        def copy_rows() -> tuple[list[str] | None, str, str]:
            """The rows in view, or None when the copy did not work -- which
            is not the same as a page with no rows in it (#182)."""
            result = copy_route(node, want_text=True)
            if not result.worked:
                return None, result.caveat, str(result.detail or "the copy did not work")
            lines = [ln for ln in (result.detail or "").replace("\r\n", "\n").split("\n") if ln]
            return lines, result.caveat, ""

        rows: list[str] = []
        seen: set[str] = set()
        match = None
        pages_read = 0
        reached_end = False
        last_page: list[str] | None = None
        caveat = ""
        page_rows: list[int] = []
        copies_failed: list[str] = []
        failed_running = 0
        copy_stopped = ""

        while pages_read < max_pages:
            page, caveat, why = session.run(copy_rows)
            if page is None:
                # A copy that did not work used to become a page of no rows,
                # and an empty page followed by the real one read as "the
                # view changed": `advanced: true` on a grid that cannot page
                # (#182). It is not a page. The view has not moved -- no key
                # was sent -- so the same copy is asked for again, and every
                # failure is kept in the result rather than absorbed.
                copies_failed.append(why)
                failed_running += 1
                if failed_running >= self._SEEK_MAX_FAILED_COPIES:
                    copy_stopped = why
                    break
                continue
            failed_running = 0
            pages_read += 1
            page_rows.append(len(page))
            if page == last_page:
                reached_end = True
                break
            last_page = page
            for line in page:
                if line not in seen:
                    seen.add(line)
                    rows.append(line)
                    if value is not None and match is None and value in line:
                        match = {"row": len(rows) - 1, "page": pages_read, "line": line}
            if match is not None or len(rows) >= self._SEEK_MAX_ROWS:
                break
            session.run(lambda: verbs.send_keys(node.handle, [advance])[0].run())

        report = {
            "ok": True,
            "locator": locator,
            "element": _element(node),
            "rows": rows,
            "row_count": len(rows),
            "pages_read": pages_read,
            #: Rows in each page as it was read: what `advanced` and
            #: `reached_end` were decided from.
            "page_rows": page_rows,
            "reached_end": reached_end,
            "advance": advance,
            "caveat": caveat or "the clipboard is shared with the person; its "
                      "prior contents were restored after each copy",
        }
        if copies_failed:
            report["copies_failed"] = copies_failed
        if copy_stopped:
            report["copy_stopped"] = (
                f"the copy route stopped answering ({copy_stopped}), so the seek "
                "stopped without reaching the end; what was read before it is in "
                "rows. The clipboard may be held by another program, or the grid "
                "may not be answering its Copy command right now")
        if waiver is not None:
            report["text_is_label"] = waiver
        if value is not None:
            report["found"] = match is not None
            if match is not None:
                report["match"] = match
            elif reached_end:
                report["note"] = (
                    f"{value!r} is not in the grid: every page was read and it "
                    "appeared on none. To act on a row, capture the page it is "
                    "on and click at its offset, or hand the selection to a person"
                )
            elif not copy_stopped:
                report["note"] = (
                    f"stopped at max_pages={max_pages} without finding {value!r} "
                    "or reaching the end; raise max_pages, or the grid may not be "
                    "paging (a posted key it does not act on leaves the view "
                    "unchanged -- then this is a step for a person)"
                )
        # Whether advancing did anything visible. A second page identical to
        # the first (reached_end at pages_read==2) is indistinguishable from
        # a grid of one page, so the note names both readings honestly.
        advanced = pages_read > 1 and not (reached_end and pages_read == 2)
        report["advanced"] = advanced
        if not advanced and pages_read > 1:
            prior = str(report.get("note", ""))
            report["note"] = (
                (prior + " ").lstrip()
                + "The view did not change when advanced: the grid fits on one "
                "page, or it did not act on the posted key without focus (D64)."
            ).strip()
        return report
