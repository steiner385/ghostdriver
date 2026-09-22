"""The shared execution core (D#83), proven with a fake toolbox.

The core is pure with respect to the desktop -- it calls methods on a
toolbox handed in -- so it needs no fixture and runs on any platform. The
end-to-end proof that `batch` still behaves is `tests/test_batch.py` against
the real fixture; here the core's own logic is exercised directly.
"""

from ghostdriver.tools.stepper import RUNNABLE_TOOLS, run_steps, step_summary


class FakeBox:
    """A toolbox whose tools are just enough to drive the core.

    Real signatures (no ``**kwargs``), so an unexpected argument raises
    ``TypeError`` exactly as a real tool would -- that is the path the core
    turns into a step failure rather than a crash.
    """

    def __init__(self):
        self.calls: list[tuple] = []

    def describe(self, session_id):
        self.calls.append(("describe", session_id))
        return {"ok": True, "verified": "effect"}

    def capture(self, session_id, locator=None, scale=1.0):
        self.calls.append(("capture", session_id, locator))
        return {"ok": True, "width": 8, "height": 4, "base64": f"PNG-{locator}"}

    def find(self, session_id, locator, all_windows=False):
        self.calls.append(("find", session_id, locator))
        if locator == "MISS":
            return {"ok": False, "match_count": 0,
                    "error": {"kind": "not_found", "message": "no match"}}
        return {"ok": True, "match_count": 1}


def test_a_run_dispatches_every_step_and_reports_each_verdict():
    box = FakeBox()

    out = run_steps(box, "sid", [
        {"tool": "describe", "args": {}},
        {"tool": "find", "args": {"locator": "class=X"}},
    ])

    assert out["ok"] and out["completed"] == 2 and out["stopped_at"] is None
    assert [s["tool"] for s in out["steps"]] == ["describe", "find"]
    assert box.calls == [("describe", "sid"), ("find", "sid", "class=X")]


def test_a_failing_step_stops_the_run_by_default():
    box = FakeBox()

    out = run_steps(box, "sid", [
        {"tool": "find", "args": {"locator": "MISS"}},
        {"tool": "describe", "args": {}},
    ])

    assert not out["ok"] and out["stopped_at"] == 0 and out["completed"] == 1
    assert len(out["steps"]) == 1, "the second step never ran"
    assert box.calls == [("find", "sid", "MISS")], "describe was not dispatched"


def test_stop_on_failure_false_runs_every_step():
    box = FakeBox()

    out = run_steps(box, "sid", [
        {"tool": "find", "args": {"locator": "MISS"}},
        {"tool": "describe", "args": {}},
    ], stop_on_failure=False)

    assert not out["ok"] and out["completed"] == 2 and out["stopped_at"] is None


def test_a_tool_outside_the_allowlist_is_refused_before_anything_runs():
    box = FakeBox()

    out = run_steps(box, "sid", [
        {"tool": "describe", "args": {}},
        {"tool": "attach", "args": {}},
    ])

    assert not out["ok"] and "cannot run in a batch" in out["error"]["message"]
    assert "attach" in out["error"]["message"]
    assert "steps" not in out


def test_the_context_word_names_the_caller():
    box = FakeBox()

    out = run_steps(box, "sid", [{"tool": "attach", "args": {}}], context="macro")

    assert "cannot run in a macro" in out["error"]["message"]


def test_a_step_may_not_carry_its_own_session():
    box = FakeBox()

    for key in ("session_id", "session_ref"):
        out = run_steps(box, "sid", [{"tool": "describe", "args": {key: "elsewhere"}}])
        assert not out["ok"] and "omit the session" in out["error"]["message"]
    assert box.calls == [], "nothing was dispatched"


def test_bad_arguments_to_a_step_are_that_step_s_failure():
    box = FakeBox()

    out = run_steps(box, "sid", [{"tool": "describe", "args": {"no_such_arg": 1}}])

    assert not out["ok"] and out["stopped_at"] == 0
    assert "bad arguments" in out["steps"][0]["error"]["message"]


def test_malformed_steps_are_refused_by_shape():
    box = FakeBox()

    assert not run_steps(box, "sid", [{"args": {}}])["ok"]        # no tool
    assert not run_steps(box, "sid", "describe")["ok"]              # not a list
    assert not run_steps(box, "sid", [])["ok"]                      # empty
    bad = run_steps(box, "sid", [{"tool": "describe", "args": "x"}])
    assert not bad["ok"] and "args must be an object" in bad["error"]["message"]


def test_the_allowlist_is_the_documented_set():
    """A guard: the set of runnable tools is deliberate, so a change to it is
    a change someone has to make on purpose."""
    assert "click" in RUNNABLE_TOOLS and "find" in RUNNABLE_TOOLS
    assert "pace" in RUNNABLE_TOOLS, "a settle between steps rides in a batch (#119)"
    for withheld in ("attach", "release", "grant_targets", "launch_isolated",
                     "foreground", "await_human", "batch"):
        assert withheld not in RUNNABLE_TOOLS, withheld


# --- a step line names what changed around it (#117) ------------------------

def test_a_step_line_keeps_the_disturbances_by_name():
    """A typed value dismissed its dialog; the step used to say only
    "2 other change(s)" because the list was not a kept field."""
    result = {
        "ok": False,
        "error": {"kind": "postcondition_failed",
                  "message": "not verified; 2 other change(s) happened -- see disturbances"},
        "disturbances": [
            {"change": "window_disappeared", "detail": "Start Order Alteration"},
            {"change": "unblocked", "detail": "no longer held by: Start Order Alteration"},
        ],
        "live_aborted": "the operator's pointer moved while committing",
    }

    line = step_summary(3, "type_text", result)

    assert [d["change"] for d in line["disturbances"]] == ["window_disappeared", "unblocked"]
    assert line["disturbances"][0]["detail"] == "Start Order Alteration"
    assert "live_aborted" in line
    assert "base64" not in line


def test_a_step_line_without_disturbances_carries_no_empty_key():
    line = step_summary(0, "find", {"ok": True, "match_count": 1})
    assert "disturbances" not in line


# --- capture images ride on the batch result (#197) ----------------------------

def test_a_capture_step_s_image_rides_beside_the_result_not_in_the_step_line():
    from ghostdriver.tools.stepper import MAX_BATCH_IMAGES

    steps = [{"tool": "capture", "args": {"locator": f"shot{i}"}} for i in range(MAX_BATCH_IMAGES + 1)]
    out = run_steps(FakeBox(), "sid", steps)

    assert out["ok"]
    assert [i["step"] for i in out["images"]] == list(range(MAX_BATCH_IMAGES))
    assert out["images"][0]["base64"] == "PNG-shot0" and out["images"][0]["width"] == 8
    assert all("base64" not in line for line in out["steps"])
    assert out["steps"][0]["image"] == "attached"
    assert out["steps"][MAX_BATCH_IMAGES]["image"].startswith("dropped")


def test_a_batch_without_captures_carries_no_images_key():
    out = run_steps(FakeBox(), "sid", [{"tool": "describe", "args": {}}])
    assert "images" not in out
