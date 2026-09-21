"""`button_pair` and `deepest_child_at` (D#40e) -- untested before this file.

Both are pure refusal/passthrough logic with no AT-SPI call behind them:
`button_pair` exists only to raise by name on what tier 1 cannot send
(D#11), and `deepest_child_at` is the Windows hit-test contract's answer
for a platform where a control is an accessible, not a window to hit-test
(D#40d). Neither needs a bus, a display, or a fixture, so nothing here is
marked `slow`.

This module is pure Python at import time (no `gi`, no live bus); it is
Linux-only because `input.py` lives under `backends/linux/`, with the rest
of that backend, per D59's platform boundary. The backend import is inside
each function, never at module scope
(`test_no_test_module_binds_a_platform_at_import_time`).
"""

import pytest

from tests.conftest import on_linux

pytestmark = on_linux


def test_button_pair_allows_only_a_plain_left_click():
    from ghostdriver.backends.linux import input as linux_input

    assert linux_input.button_pair("left", ()) == ()


def test_button_pair_refuses_a_right_click_by_name():
    from ghostdriver.backends.linux import input as linux_input

    with pytest.raises(ValueError, match="right"):
        linux_input.button_pair("right", ())


def test_button_pair_refuses_a_modifier_by_name():
    from ghostdriver.backends.linux import input as linux_input

    with pytest.raises(ValueError, match="ctrl"):
        linux_input.button_pair("left", ("ctrl",))


def test_deepest_child_at_is_a_no_op():
    """There is no window to hit-test (D#40d); the point passed in comes
    back unchanged, which is the Windows contract's "nothing else is under
    the point" answer."""
    from ghostdriver.backends.linux import input as linux_input

    assert linux_input.deepest_child_at(42, 10, 20) == (42, 10, 20)


def test_named_keys_and_edit_actions_are_disjoint_and_lowercase():
    """`send_keys` looks a caller's word up in both tables (`tools/
    actuation.py`); a key spelled in both, or spelled with a capital, would
    be an ambiguity this contract does not have a rule for."""
    from ghostdriver.backends.linux import input as linux_input

    assert set(linux_input.NAMED_KEYS) & set(linux_input.EDIT_ACTIONS) == set()
    for table in (linux_input.NAMED_KEYS, linux_input.EDIT_ACTIONS):
        assert all(key == key.lower() for key in table)
