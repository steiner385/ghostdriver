"""index= drift: the same locator, in the same session, picking a different
control than it did before (#198).

`index` counts siblings in the tree's own order -- z-order, on Windows --
and a toolkit reorders siblings as controls take focus. A form filled by
index put a value in the wrong field twice. The bookkeeping lives here,
off the core, which sits at the tool-module limit (D60).
"""


def note_index_drift(seen: dict, pending: dict, session_id: str, expression: str,
                     picked, found: list) -> None:
    """Remember what an index= locator picked, and queue a note when it moves.

    When the same locator, in the same session, picks a different control
    while the one it picked before is still among the matches, the next
    result says so; a control that went away is not drift.
    """
    key = (session_id, expression)
    before = seen.get(key)
    seen[key] = picked.handle
    if before is None or before == picked.handle:
        return
    if any(node.handle == before for node in found):
        pending[key] = (
            f"index drift: {expression!r} picked a different control than it did "
            f"earlier in this session (0x{before:08X} then, 0x{picked.handle:08X} "
            "now) while the earlier one is still there. The tree's sibling order "
            "moved -- a toolkit reorders siblings as controls take focus. Anchor "
            "this field by text= or by region= from an earlier find instead of "
            "index=.")


def whitespace_note(locator: str) -> str:
    """text= matches exactly, whitespace included, and stays so: trimming
    would silently change which control a locator names. A pattern with
    leading or trailing whitespace that did not match is told (#206)."""
    import re

    from ..model.locator import Locator

    try:
        text = Locator.parse(locator).text
    except Exception:
        return ""
    if not text or text == text.strip():
        return ""
    return (f"; text= is an exact match including the leading/trailing whitespace "
            f"in {text!r} -- a /regex/ can match without it, e.g. "
            f"text=/{re.escape(text.strip())}/")
