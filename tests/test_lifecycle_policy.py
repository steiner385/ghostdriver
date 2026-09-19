"""Two `attach`/`grant_targets` refusals that never reach a backend.

Both are decided before any window is touched: `grant_targets()` with
nothing to record is rejected by shape alone, and a dead pid is caught by
`psutil.Process` -- which raises before `Toolbox.attach` ever gets to
enumerating the target's windows (the same backend touch that keeps the
rest of `test_tools.py` on Windows; see its `win32_target` fixture and
D#39). Platform-neutral by construction, so these run anywhere.
"""

from ghostdriver.model.result import ErrorKind
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox


def box():
    return Toolbox(sessions=SessionManager())


def test_granting_nothing_is_an_error_rather_than_a_silent_no_op():
    result = box().grant_targets()

    assert result["ok"] is False
    assert "allow" in result["error"]["message"]


def test_attaching_to_a_dead_pid_says_so():
    b = box()
    b.grant_targets(allow=[999_999])
    result = b.attach(999_999)

    assert result["ok"] is False
    assert result["error"]["kind"] == ErrorKind.NOT_FOUND.value
