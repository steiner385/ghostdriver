"""Recognising a process that owns windows for somebody else.

`list_targets` maps processes to windows and presents that as the whole
truth. It is not: some processes own windows on behalf of other processes,
and a caller who attaches to the pid owning the visible window can end up
profiling a title bar.
"""

from ghostdriver.hosting import (
    MEASURED_A_FRAME_NOTE,
    classify_process,
    is_frame_host,
    is_hosted_app,
    note_for_measured_window,
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
    assert note_for_measured_window("ApplicationFrameWindow")
    assert not note_for_measured_window("Shell_TrayWnd")
    assert not note_for_measured_window("Windows.UI.Core.CoreWindow")


def test_the_warning_explains_rather_than_merely_labelling():
    """A caller that only learns "frame-host" knows nothing actionable."""
    assert "describes the frame, not the application" in MEASURED_A_FRAME_NOTE
    assert "CoreWindow" in MEASURED_A_FRAME_NOTE, "says what to look for"
    assert len(MEASURED_A_FRAME_NOTE) > 120
