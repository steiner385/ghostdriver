"""What counts as a hidden field's text leaking or being masked (issue 219).

The Linux password tests accept either answer, because the toolkit version
decides it (GTK 4.14.5 leaked, 4.22.4 and 3.24.52 mask). This pins the
classifier itself, on any platform.
"""

from tests.linux_probe_support import leaked_or_masked


def test_the_secret_itself_is_a_leak():
    assert leaked_or_masked("hunter2", "hunter2") == "leaked"


def test_one_mask_character_per_secret_character_is_masked():
    assert leaked_or_masked("•" * 7, "hunter2") == "masked"  # X11 backend
    assert leaked_or_masked("●" * 7, "hunter2") == "masked"  # Wayland backend


def test_anything_else_is_an_unmeasured_change():
    assert leaked_or_masked("", "hunter2") is None
    assert leaked_or_masked("•" * 6, "hunter2") is None
    assert leaked_or_masked("hunter3", "hunter2") is None
