"""What `restore` says it did (issue 217).

On GNOME 50's headless shell an X client's activation is refused, so a
restore asks and nothing comes back on screen. The result used to say "the
application re-showed its own forms" whenever it had asked at all.
"""

from ghostdriver.model.restore import RestoreResult


def _result(restored, before, after):
    return RestoreResult(restored=restored, visible_before=before,
                         visible_after=after, foreground_before=1,
                         foreground_after=1)


def test_nothing_hidden_says_so():
    assert _result((), (5,), (5,)).note == "nothing was minimized"


def test_a_restore_nothing_answered_does_not_claim_it_worked():
    note = _result((7,), (), ()).note
    assert "none came back on screen" in note
    assert "re-showed" not in note


def test_a_restore_that_worked_says_what_came_back():
    assert _result((7,), (), (7,)).note == "the application re-showed its own forms"
