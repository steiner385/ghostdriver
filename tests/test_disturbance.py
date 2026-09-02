"""What the evidence layer reports, and what it refuses to conclude."""

from ghostdriver.disturbance import Change, Snapshot, compare


def snap(windows=None, blocked=(), foreground=0, alive=True):
    return Snapshot(windows=windows or {}, blocked_by=tuple(blocked),
                    foreground=foreground, alive=alive)


def kinds(disturbances):
    return [d.change for d in disturbances]


def test_a_quiet_action_reports_nothing():
    """Silence has to mean something, so it must not be noisy by default."""
    state = snap({1: "Main"}, foreground=1)

    assert compare(state, state) == []


def test_a_new_dialog_is_reported_with_its_caption():
    """The caption is the whole value of the report: "a window appeared"
    sends a caller looking, "Confirm Delete Record" does not."""
    found = compare(snap({1: "Main"}), snap({1: "Main", 2: "Confirm Delete"}))

    assert kinds(found) == [Change.WINDOW_APPEARED]
    assert found[0].detail == "Confirm Delete"


def test_becoming_blocked_outranks_the_dialog_that_caused_it():
    """A caller reading only the first entry should get the one that
    matters: the application is held, which is why nothing else will work."""
    found = compare(
        snap({1: "Main"}),
        snap({1: "Main", 2: "Error"}, blocked=("Error",)),
    )

    assert kinds(found)[0] is Change.BLOCKED
    assert "Error" in found[0].detail


def test_a_target_that_went_away_reports_that_and_stops():
    """Everything else is noise once the target is gone -- and a session
    timeout is one of the things this exists to surface."""
    found = compare(snap({1: "Main"}, foreground=1), snap(alive=False))

    assert kinds(found) == [Change.TARGET_GONE]


def test_the_target_taking_the_foreground_is_reported():
    """Never caused by anything the tool sends, so it is always the
    application's own doing -- and the person at the machine just had their
    desktop changed."""
    found = compare(
        snap({1: "Main"}, foreground=99),
        snap({1: "Main"}, foreground=1),
    )

    assert kinds(found) == [Change.TOOK_FOREGROUND]
    assert found[0].detail == "Main"


def test_the_foreground_moving_elsewhere_is_not_the_targets_doing():
    """Someone alt-tabbing to another application is not a disturbance this
    tool has anything to say about."""
    found = compare(
        snap({1: "Main"}, foreground=1),
        snap({1: "Main"}, foreground=4242),
    )

    assert Change.TOOK_FOREGROUND not in kinds(found)


def test_a_dismissed_dialog_reads_as_unblocked_not_as_a_loss():
    found = compare(
        snap({1: "Main", 2: "Error"}, blocked=("Error",)),
        snap({1: "Main"}),
    )

    assert kinds(found)[0] is Change.UNBLOCKED
    assert Change.WINDOW_DISAPPEARED in kinds(found)


def test_swapping_one_modal_for_another_reports_the_new_block():
    """Otherwise a caller sees "unblocked" and walks into the next one."""
    found = compare(
        snap({1: "Main", 2: "First"}, blocked=("First",)),
        snap({1: "Main", 3: "Second"}, blocked=("Second",)),
    )

    assert kinds(found)[0] is Change.BLOCKED
    assert Change.UNBLOCKED not in kinds(found)


def test_several_new_windows_are_all_named():
    found = compare(snap({1: "Main"}), snap({1: "Main", 2: "A", 3: "B"}))

    assert [d.detail for d in found] == ["A", "B"]


def test_an_untitled_window_still_gets_reported():
    """A window with no caption is still a window that appeared, and
    dropping it would be dropping the observation."""
    found = compare(snap({1: "Main"}), snap({1: "Main", 2: ""}))

    assert kinds(found) == [Change.WINDOW_APPEARED]
    assert found[0].detail == "(untitled)"
