"""Recognising a process that owns windows for somebody else.

`list_targets` maps processes to windows and presents that as the whole
truth. It is not: some processes own windows on behalf of other processes,
and a caller who attaches to the pid owning the visible window can end up
profiling a title bar.
"""

from ghostdriver.hosting import (
    MEASURED_A_FRAME_NOTE,
    classify_process,
    hosted_frame_note,
    is_frame_host,
    is_hosted_app,
)


def test_a_frame_host_class_is_recognised():
    assert is_frame_host("ApplicationFrameWindow")
    assert not is_frame_host("Shell_TrayWnd")


def test_a_hosted_application_window_is_recognised():
    assert is_hosted_app("Windows.UI.Core.CoreWindow")
    assert not is_hosted_app("ApplicationFrameWindow")


def test_a_process_owning_a_frame_is_flagged_only_weakly():
    """A shell owns a hosted frame among dozens of windows of its own.

    Telling its user that "everything measured here describes a frame"
    would be false, so the process-level claim says only that not every
    window belongs to it.
    """
    kind, note = classify_process(
        ["ApplicationFrameWindow", "Shell_TrayWnd", "WorkerW"]
    )

    assert kind == "hosts-frames"
    assert "may also have a UI of its own" in note
    assert "describes the frame" not in note, "that is the strong claim"


def test_a_hosted_application_is_pointed_at():
    """The other end of the same problem: this is the pid worth attaching
    to, and it is not obvious from a process list."""
    kind, note = classify_process(
        ["Windows.UI.Core.CoreWindow", "WorkerW", "IME"]
    )

    assert kind == "hosted-app"
    assert "worth attaching to" in note


def test_an_ordinary_process_is_neither():
    kind, note = classify_process(["Shell_TrayWnd", "WorkerW", "Progman"])

    assert kind is None
    assert note == ""


def test_hosting_a_frame_wins_when_a_process_looks_like_both():
    kind, _ = classify_process(
        ["ApplicationFrameWindow", "Windows.UI.Core.CoreWindow"]
    )

    assert kind == "hosts-frames"


def test_the_strong_claim_applies_only_to_the_measured_window():
    """This is the one that warns, and it has to be precise: it says a
    result is about somebody else's frame."""
    assert is_frame_host("ApplicationFrameWindow")
    assert not is_frame_host("Shell_TrayWnd")
    assert not is_frame_host("Windows.UI.Core.CoreWindow")


def test_a_named_application_gives_the_caller_a_pid_not_a_search():
    """Resolution turns a signpost into an answer."""
    note = hosted_frame_note(125488, "SystemSettings.exe", 0.96)

    assert "SystemSettings.exe" in note
    assert "125488" in note
    assert "96%" in note
    assert "attach to that pid" in note


def test_an_unidentified_application_is_called_suspended_not_broken():
    """A hosted application that is not in the foreground provides nothing.

    Reporting that as "unresolvable" sends someone looking for a bug; the
    fix is to click the window. Measured both ways: suspended it yielded a
    single element, awake it yielded 203.
    """
    note = hosted_frame_note(None)

    assert "suspended" in note
    assert "foreground" in note


def test_the_warning_explains_rather_than_merely_labelling():
    """A caller that only learns "frame-host" knows nothing actionable.

    The advice changed once resolution existed: it used to say "go find a
    process owning a CoreWindow", which is a search. Now the resolved case
    hands over a pid, and the unresolved case says why it could not and what
    to do -- both better than a hunt.
    """
    assert "describes the frame, not the application" in MEASURED_A_FRAME_NOTE
    assert "measure again" in MEASURED_A_FRAME_NOTE, "says what to do"
    assert len(MEASURED_A_FRAME_NOTE) > 120
