"""The claim slice 5b's `HiddenDesktop` depends on: one process, one bus.

D#40f is the measurement -- against two real nested buses, neither a second
`Atspi.init()`, a fork, nor `Atspi.exit()` then reconnect let one process
reach a second AT-SPI bus. `desktop_claim.py` is the consequence: whoever
opens the shared accessibility connection first owns it for the process's
life, and everyone else is told so instead of silently reading the wrong
bus. This module is pure Python (no `gi`, no `Xlib`), so these tests run
without a display or a bus of their own; they are still Linux-only because
`desktop_claim.py` lives under `backends/linux/`, with the rest of that
backend, per D59's platform boundary.

The backend import is inside each function, never at module scope
(`test_no_test_module_binds_a_platform_at_import_time`).
"""

import pytest

from tests.conftest import on_linux

pytestmark = on_linux


@pytest.fixture(autouse=True)
def _fresh_claim(monkeypatch):
    """Each test gets its own unclaimed process, not the real one -- these
    tests run inside the pytest process, which may have already claimed
    itself for something unrelated by the time this module runs."""
    from ghostdriver.backends.linux import desktop_claim

    monkeypatch.setattr(desktop_claim, "_owner", None)


def test_the_first_claim_names_the_operator_by_default():
    from ghostdriver.backends.linux import desktop_claim

    desktop_claim.claim()
    assert desktop_claim.claimed_by() == desktop_claim.OPERATOR_DESKTOP


def test_a_second_claim_by_the_same_owner_is_a_no_op():
    from ghostdriver.backends.linux import desktop_claim

    desktop_claim.claim()
    desktop_claim.claim()  # does not raise
    assert desktop_claim.claimed_by() == desktop_claim.OPERATOR_DESKTOP


def test_a_different_claimant_is_refused_not_silently_rerouted():
    from ghostdriver.backends.linux import desktop_claim

    desktop_claim.claim()
    with desktop_claim.desktop("ghostdriver-abc123"), \
         pytest.raises(desktop_claim.AlreadyClaimed) as excinfo:
        desktop_claim.claim()
    assert "ghostdriver-abc123" in str(excinfo.value)
    assert desktop_claim.OPERATOR_DESKTOP in str(excinfo.value)


def test_a_hidden_desktop_claiming_first_then_refuses_the_operator():
    from ghostdriver.backends.linux import desktop_claim

    with desktop_claim.desktop("ghostdriver-abc123"):
        desktop_claim.claim()
    # Outside the `with`, `effective_owner()` is back to the operator's --
    # this is the ordinary-session call that must not silently read the
    # hidden desktop's tree.
    with pytest.raises(desktop_claim.AlreadyClaimed):
        desktop_claim.claim()


def test_the_same_hidden_desktop_can_claim_repeatedly():
    from ghostdriver.backends.linux import desktop_claim

    with desktop_claim.desktop("ghostdriver-abc123"):
        desktop_claim.claim()
        desktop_claim.claim()  # does not raise: same owner, same context
    assert desktop_claim.claimed_by() == "ghostdriver-abc123"


def test_desktop_context_nests_and_restores_the_outer_owner():
    from ghostdriver.backends.linux import desktop_claim

    assert desktop_claim.effective_owner() == desktop_claim.OPERATOR_DESKTOP
    with desktop_claim.desktop("outer"):
        assert desktop_claim.effective_owner() == "outer"
        with desktop_claim.desktop("inner"):
            assert desktop_claim.effective_owner() == "inner"
        assert desktop_claim.effective_owner() == "outer"
    assert desktop_claim.effective_owner() == desktop_claim.OPERATOR_DESKTOP
