"""The sentences said at the moment of need (`ghostdriver.tools.guidance`).

Plain string constants, so the promise they check is just that the words
are still there -- no backend, no window, no platform.
"""

from ghostdriver.tools.guidance import FOCUS_NOTE


def test_the_focus_note_names_a_tool_that_activates_windows():
    """A focus note that sent the caller to a no-op instead of naming the
    tool that could act (D69)."""
    assert "tool that does activate windows" in FOCUS_NOTE
    assert "until_change" in FOCUS_NOTE
