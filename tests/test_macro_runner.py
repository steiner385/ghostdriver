"""The macro runner: param binding and the `when` branch (#85), with fakes.

Pure with respect to the desktop -- it calls methods on a toolbox handed in
-- so it needs no fixture and runs anywhere (`env: any`). The end-to-end
proof against a real target is `macro_replay`'s smoke test (#87).
"""

from ghostdriver.workflow import (
    Workflow,
    bind,
    missing_required,
    run_macro_body,
)


class FakeBox:
    """Records every tool call as (name, args). `find`'s locator arrives
    positionally (as the real tool takes it) and is folded into the args so a
    test can read it uniformly."""

    def __init__(self, answers):
        self.answers = answers
        self.calls: list[tuple[str, dict]] = []

    def __getattr__(self, name):
        def tool(session_id, *pos, **kw):
            if pos:  # find(session_id, locator, ...)
                kw = {"locator": pos[0], **kw}
            self.calls.append((name, kw))
            answer = self.answers.get(name, {"ok": True})
            return answer.pop(0) if isinstance(answer, list) else answer
        return tool

    def clicks(self):
        return [a["locator"] for n, a in self.calls if n == "click"]


def macro(steps, **top):
    return Workflow.from_dict({"name": "m", "steps": steps, **top})


# --- param binding --------------------------------------------------------

def test_binding_substitutes_and_preserves_type():
    # a value that is exactly ${x} keeps its type; embedded it interpolates.
    bound, unbound = bind({"locator": "name=${pid}", "at": {"x": "${x}", "y": 10}},
                          {"pid": "P1", "x": 11})
    assert bound == {"locator": "name=P1", "at": {"x": 11, "y": 10}}
    assert unbound == []


def test_binding_reports_unresolved_names():
    _, unbound = bind({"locator": "${a}", "note": "${b}${a}"}, {"a": "1"})
    assert unbound == ["b"]


def test_missing_required_lists_unbound_required_params():
    wf = macro([{"tool": "click", "args": {"locator": "${p}"}}],
               params={"p": {"required": True}, "opt": {"required": False}})
    assert missing_required(wf.params, {}) == ["p"]
    assert missing_required(wf.params, {"p": "x"}) == []


def test_a_bound_macro_substitutes_before_dispatch():
    wf = macro([{"tool": "click", "args": {"locator": "name=${pid}"}}],
               params={"pid": {"required": True}})
    box = FakeBox({"click": {"ok": True}})

    out = run_macro_body(box, "s", wf.steps, {"pid": "PLAN-1"})

    assert out["ok"] and out["completed"] == 1
    assert box.clicks() == ["name=PLAN-1"]


def test_an_unbound_param_refuses_the_run_rather_than_guessing():
    wf = macro([{"tool": "click", "args": {"locator": "${pid}"}}])
    box = FakeBox({"click": {"ok": True}})

    out = run_macro_body(box, "s", wf.steps, {})

    assert not out["ok"] and "unbound param(s) ['pid']" in out["refused"]
    assert box.calls == [], "nothing was dispatched"


# --- the when branch ------------------------------------------------------

TOGGLE = [{"when": {"locator": "class=Funnel", "pressed": True},
           "then": [{"tool": "click", "args": {"locator": "once"}}],
           "else": [{"tool": "click", "args": {"locator": "twice-a"}},
                    {"tool": "click", "args": {"locator": "twice-b"}}]}]


def test_a_true_condition_runs_the_then_arm():
    box = FakeBox({"find": {"ok": True, "elements": [{"pressed": True}]},
                   "click": {"ok": True}})

    out = run_macro_body(box, "s", macro(TOGGLE).steps, {})

    assert out["ok"] and box.clicks() == ["once"]
    assert [s["path"] for s in out["steps"]] == ["0.then.0"]


def test_a_false_condition_runs_the_else_arm():
    box = FakeBox({"find": {"ok": True, "elements": [{"pressed": False}]},
                   "click": {"ok": True}})

    out = run_macro_body(box, "s", macro(TOGGLE).steps, {})

    assert out["ok"] and box.clicks() == ["twice-a", "twice-b"]
    assert [s["path"] for s in out["steps"]] == ["0.else.0", "0.else.1"]


def test_absent_holds_when_nothing_matches():
    body = [{"when": {"locator": "class=Dialog", "absent": True},
             "then": [{"tool": "click", "args": {"locator": "proceed"}}]}]
    box = FakeBox({"find": {"ok": True, "elements": []}, "click": {"ok": True}})

    out = run_macro_body(box, "s", macro(body).steps, {})

    assert out["ok"] and box.clicks() == ["proceed"]


def test_a_pressed_condition_the_target_cannot_report_refuses_rather_than_reads_false():
    """The funnel's pressed state is not readable until #77; a branch that
    conditions on it must say so, not silently take the else arm."""
    box = FakeBox({"find": {"ok": True, "elements": [{"class": "Funnel"}]}})

    out = run_macro_body(box, "s", macro(TOGGLE).steps, {})

    assert not out["ok"] and "#77" in out["refused"]
    assert box.clicks() == [], "it did not branch on a guess"


def test_a_condition_that_cannot_be_read_refuses_the_run():
    box = FakeBox({"find": {"ok": False, "error": {"message": "the target is gone"}}})

    out = run_macro_body(box, "s", macro(TOGGLE).steps, {})

    assert not out["ok"] and "could not evaluate the condition" in out["refused"]


def test_a_branch_locator_may_use_a_param():
    body = [{"when": {"locator": "name=${who}"},
             "then": [{"tool": "click", "args": {"locator": "hi"}}]}]
    box = FakeBox({"find": {"ok": True, "elements": [{"a": 1}]}, "click": {"ok": True}})

    out = run_macro_body(box, "s", macro(body).steps, {"who": "Bob"})

    assert out["ok"]
    assert box.calls[0][0] == "find" and box.calls[0][1]["locator"] == "name=Bob"


def test_an_unbound_branch_locator_param_refuses():
    body = [{"when": {"locator": "${who}"},
             "then": [{"tool": "click", "args": {"locator": "x"}}]}]
    out = run_macro_body(FakeBox({}), "s", macro(body).steps, {})

    assert not out["ok"] and "unbound param(s)" in out["refused"]


def test_a_nested_branch_resolves():
    body = [{"when": {"locator": "X"}, "then": [
        {"when": {"locator": "Y", "selected": True},
         "then": [{"tool": "click", "args": {"locator": "deep"}}]}]}]
    box = FakeBox({"find": [{"ok": True, "elements": [{"a": 1}]},
                            {"ok": True, "elements": [{"selected": True}]}],
                   "click": {"ok": True}})

    out = run_macro_body(box, "s", macro(body).steps, {})

    assert out["ok"] and box.clicks() == ["deep"]
    assert [s["path"] for s in out["steps"]] == ["0.then.0.then.0"]


# --- the safety model carries through -------------------------------------

def test_a_withheld_tool_refuses_the_whole_macro():
    out = run_macro_body(FakeBox({}), "s", macro([{"tool": "attach", "args": {}}]).steps, {})

    assert not out["ok"] and "cannot run in a macro" in out["refused"]


def test_a_step_may_not_carry_its_own_session():
    body = [{"tool": "click", "args": {"session_ref": "x", "locator": "y"}}]
    out = run_macro_body(FakeBox({}), "s", macro(body).steps, {})

    assert not out["ok"] and "omit the session" in out["refused"]


def test_a_failing_leaf_assertion_stops_the_run():
    body = [{"tool": "find", "args": {"locator": "X"}, "expect": {"match_count": 3}},
            {"tool": "click", "args": {"locator": "Y"}}]
    box = FakeBox({"find": {"ok": True, "match_count": 1}, "click": {"ok": True}})

    out = run_macro_body(box, "s", macro(body).steps, {})

    assert not out["ok"] and out["stopped_at"] == "0" and out["completed"] == 1
    assert "click" not in [n for n, _ in box.calls], "the second step never ran"


def test_stop_on_failure_false_runs_past_a_failing_leaf():
    body = [{"tool": "find", "args": {"locator": "X"}, "expect": {"match_count": 3}},
            {"tool": "click", "args": {"locator": "Y"}}]
    box = FakeBox({"find": {"ok": True, "match_count": 1}, "click": {"ok": True}})

    out = run_macro_body(box, "s", macro(body).steps, {}, stop_on_failure=False)

    assert not out["ok"] and out["completed"] == 2
