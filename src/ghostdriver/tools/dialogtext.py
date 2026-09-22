"""What a dialog says: every text control in it, top to bottom.

A modal's edit, memo and label controls answer a text query with their
whole buffer, not just the visible part, so this returns the exception
below the fold that a capture cannot show (D73). Its own module because
`status.py` sits at the tool-module limit (D60), and because the shape
changed (#196): each control is reported on its own, capped by default,
so a one-line message and a memo holding a stack trace are told apart and
the memo does not cost the message beside it.
"""

#: How much of one control's text a `modals` result carries by default. A
#: message fits; a Java stack trace, read eight times at 3-4k tokens each,
#: was the field report that set this (#196). `full_text=true` lifts it.
DIALOG_CONTROL_CHARS = 600


def dialog_controls(hwnd: int, *, per_control: int | None = DIALOG_CONTROL_CHARS) -> list[dict]:
    """Every readable text control inside a dialog, in reading order.

    Ordered by position so it reads as the dialog does; de-duplicated
    because a control and its frame can report the same string. Each entry
    is {class, chars, text}, with `cut` when `per_control` trimmed it --
    the count of characters left out, so the caller can tell a message from
    a trace without paying for the trace.
    """
    from ..backends import current

    enumerate_children = current().direct_children
    read_window_text = current().read_window_text
    winapi = current().winapi

    rows: list[tuple[int, int, str, str]] = []
    seen: set[str] = set()

    def walk(handle: int) -> None:
        for child in enumerate_children(handle):
            text = (read_window_text(child) or "").strip()
            if text and text not in seen:
                seen.add(text)
                rect = winapi.window_rect(child)
                rows.append((rect[1], rect[0], winapi.class_name(child), text))
            walk(child)

    walk(hwnd)
    rows.sort()
    out: list[dict] = []
    for _top, _left, class_name, text in rows:
        entry: dict = {"class": class_name, "chars": len(text), "text": text}
        if per_control is not None and len(text) > per_control:
            entry["text"] = text[:per_control]
            entry["cut"] = len(text) - per_control
        out.append(entry)
    return out


def join_dialog_text(controls: list[dict]) -> str:
    """The dialog as one text, the way it read before controls were split
    out -- from the capped pieces, so the whole is bounded too."""
    return "\n".join(c["text"] + (" ..." if c.get("cut") else "") for c in controls)


def _dialog_text(hwnd: int, *, limit: int = 8000) -> str:
    """Every readable line of text inside a dialog, top to bottom.

    A modal's edit, memo and label controls answer a text query with their
    whole buffer, not just the visible part, so this returns the exception
    below the fold that a capture cannot show (D73). Ordered by position so
    it reads as the dialog does; de-duplicated because a control and its
    frame can report the same string."""
    from ..backends import current

    enumerate_children = current().direct_children
    read_window_text = current().read_window_text

    lines: list[tuple[int, int, str]] = []
    seen: set[str] = set()

    def walk(handle: int) -> None:
        for child in enumerate_children(handle):
            text = (read_window_text(child) or "").strip()
            if text and text not in seen:
                seen.add(text)
                rect = current().winapi.window_rect(child)
                lines.append((rect[1], rect[0], text))
            walk(child)

    walk(hwnd)
    lines.sort()
    out = "\n".join(text for _, _, text in lines)
    return out[:limit] + (" ..." if len(out) > limit else "")
