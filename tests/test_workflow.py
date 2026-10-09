"""The operator directory, the workflow model, and the runner -- with fakes.

Nothing here touches a desktop. The operator directory's one rule (never
inside a repository) is checked against real directories under tmp_path;
the runner is driven with a fake toolbox that records calls and returns
what it is told; the interference watch is fed observations.
"""

import json

import pytest

from ghostdriver.operator import ENV_VAR, OperatorDir, OperatorDirError
from ghostdriver.workflow import (
    Branch,
    ForEach,
    Guard,
    Handler,
    Param,
    Provenance,
    RepeatUntil,
    RunReport,
    Step,
    Workflow,
    WorkflowError,
    check,
    dig,
    run_workflow,
)
from tests.conftest import on_windows

# --- the operator directory -----------------------------------------------------

def test_the_directory_comes_from_the_environment_or_an_explicit_path(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "from-env"))

    assert OperatorDir.resolve().root == (tmp_path / "from-env").resolve()
    assert OperatorDir.resolve(tmp_path / "explicit").root == (tmp_path / "explicit").resolve()


def test_no_directory_is_an_error_that_says_how_to_fix_it(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)

    with pytest.raises(OperatorDirError, match=ENV_VAR):
        OperatorDir.resolve()


def test_a_directory_inside_a_git_checkout_is_refused(tmp_path):
    """The rule, made mechanical: target knowledge lives in no repository,
    so a directory the tool would read from cannot be one `git add` away."""
    (tmp_path / ".git").mkdir()
    inside = tmp_path / "ops"
    inside.mkdir()

    with pytest.raises(OperatorDirError, match="inside the git checkout"):
        OperatorDir.resolve(inside)


def test_a_packaged_apps_virtualized_app_data_is_refused(tmp_path):
    """Measured: from inside the packaged desktop client, a directory made
    under %LOCALAPPDATA% resolves into the app's LocalCache, invisible to
    the operator's own shell. Refused with the reason."""
    from ghostdriver.operator import virtualized_app_data

    virtual = tmp_path / "Packages" / "SomeApp_abc" / "LocalCache" / "Local" / "ghostdriver"
    virtual.mkdir(parents=True)

    assert virtualized_app_data(virtual) == tmp_path / "Packages" / "SomeApp_abc" / "LocalCache"
    with pytest.raises(OperatorDirError, match="private copy of AppData"):
        OperatorDir.resolve(virtual)


def test_this_repository_itself_is_refused():
    from pathlib import Path

    here = Path(__file__).resolve().parent
    with pytest.raises(OperatorDirError):
        OperatorDir.resolve(here)


def test_a_bare_profile_name_is_looked_up_and_a_path_is_used_as_given(tmp_path):
    folder = OperatorDir.resolve(tmp_path)

    assert folder.profile_path("sandbox") == tmp_path.resolve() / "profiles" / "sandbox.json"
    assert str(folder.profile_path("C:/elsewhere/p.json")).endswith("p.json")


def test_workflows_are_listed_by_name_and_missing_ones_name_the_known(tmp_path):
    folder = OperatorDir.resolve(tmp_path)
    folder.ensure()
    (folder.workflows / "open-list.json").write_text("{}", encoding="utf-8")
    (folder.workflows / "walk-tabs.json").write_text("{}", encoding="utf-8")

    assert folder.list_workflows() == ["open-list", "walk-tabs"]
    assert folder.workflow_path("walk-tabs").name == "walk-tabs.json"
    with pytest.raises(OperatorDirError, match="open-list, walk-tabs"):
        folder.workflow_path("nope")


def test_reports_are_written_under_reports(tmp_path):
    folder = OperatorDir.resolve(tmp_path)

    written = folder.write_report("walk-tabs", "20260903-101500", {"verdict": "passed"})

    assert written.parent == folder.reports
    assert json.loads(written.read_text(encoding="utf-8"))["verdict"] == "passed"


# --- the workflow model ------------------------------------------------------------

def test_a_workflow_parses_its_steps_and_defaults():
    wf = Workflow.from_dict({
        "name": "walk-tabs", "tier": "interactive",
        "steps": [
            {"tool": "find", "args": {"locator": "type=TabItem"},
             "expect": {"match_count": 3}},
            {"tool": "click", "args": {"locator": 'type=TabItem name="Components"'},
             "expect_contains": {"verified": "effect"}, "note": "switch page"},
            {"tool": "click", "args": {"locator": "type=TabItem"}, "expect_ok": False},
        ],
    })

    assert wf.name == "walk-tabs" and wf.tier == "interactive" and wf.isolation == "none"
    assert [s.tool for s in wf.steps] == ["find", "click", "click"]
    assert wf.steps[0].expect == {"match_count": 3}
    assert wf.steps[1].note == "switch page"
    assert wf.steps[2].expect_ok is False


@pytest.mark.parametrize("bad", [
    [], {"steps": []}, {"steps": [{"args": {}}]}, {"steps": "click"},
])
def test_a_malformed_workflow_is_refused_with_a_reason(bad):
    with pytest.raises(WorkflowError):
        Workflow.from_dict(bad)


def test_a_workflow_file_takes_its_name_from_the_file(tmp_path):
    path = tmp_path / "read-status.json"
    path.write_text(json.dumps({"steps": [{"tool": "read", "args": {"locator": "class=Static"}}]}),
                    encoding="utf-8")

    assert Workflow.load(path).name == "read-status"


# --- assertions --------------------------------------------------------------------

def test_dig_follows_dotted_paths_through_dicts_and_lists():
    data = {"values": [{"text": "clicks=1"}], "ok": True}

    assert dig(data, "values.0.text") == (True, "clicks=1")
    assert dig(data, "values.9.text") == (False, None)
    assert dig(data, "nope") == (False, None)


def test_check_reports_every_failure_as_a_sentence():
    step = Step(tool="read", expect={"values.0.text": "clicks=1", "match_count": 1},
                expect_contains={"values.0.text": "clicks"})
    failures = check(step, {"ok": True, "match_count": 2,
                            "values": [{"text": "clicks=0"}]})

    assert failures == [
        "values.0.text is 'clicks=0', expected 'clicks=1'",
        "match_count is 2, expected 1",
    ]


def test_check_treats_a_refusal_as_the_expected_outcome_when_asked():
    refused = {"ok": False, "error": {"kind": "denied_by_policy", "message": "no"}}

    assert check(Step(tool="click", expect_ok=False), refused) == []
    assert check(Step(tool="click"), refused) == ["the call did not succeed: no"]
    assert check(Step(tool="click", expect_ok=False), {"ok": True}) == [
        "the call succeeded, and this step expected it to be refused"]


# --- the runner, with a fake toolbox -------------------------------------------------

class FakeSessions:
    def __init__(self):
        self.grants = []

    def record_grant(self, pid, *, allowed, source, note=""):
        self.grants.append((pid, allowed, source.value, note))


class FakeBox:
    """Answers each tool from a script; records every call in order."""

    def __init__(self, answers):
        self.sessions = FakeSessions()
        self.answers = answers
        self.calls = []

    def attach(self, pid, **kw):
        self.calls.append(("attach", pid, kw))
        return self.answers.get("attach", {"ok": True, "session_id": "s1"})

    def release(self, session_id):
        self.calls.append(("release", session_id))
        return self.answers.get("release", {"ok": True})

    def __getattr__(self, name):
        if name not in self.answers:
            raise AttributeError(name)

        def tool(session_id, **kw):
            self.calls.append((name, session_id, kw))
            answer = self.answers[name]
            return answer.pop(0) if isinstance(answer, list) else answer
        return tool


class FakeWatch:
    def __init__(self, events=()):
        self.started = self.stopped = False
        self._events = list(events)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def events(self):
        return self._events


def walk_tabs():
    return Workflow.from_dict({"name": "walk-tabs", "tier": "interactive", "steps": [
        {"tool": "find", "args": {"locator": "type=TabItem"}, "expect": {"match_count": 3}},
        {"tool": "click", "args": {"locator": 'type=TabItem name="Components"'},
         "expect": {"verified": "effect"}},
        {"tool": "read", "args": {"locator": "class=Static"},
         "expect_contains": {"values.0.text": "clicks="}},
    ]})


def test_a_passing_run_attaches_runs_every_step_releases_and_reports():
    box = FakeBox({
        "find": {"ok": True, "match_count": 3},
        "click": {"ok": True, "verified": "effect"},
        "read": {"ok": True, "values": [{"text": "clicks=1"}]},
    })
    watch = FakeWatch()

    report = run_workflow(box, walk_tabs(), pid=4242, watch=watch, now=lambda: 1.0)

    assert report.passed and report.verdict == "passed"
    assert [c[0] for c in box.calls] == ["attach", "find", "click", "read", "release"]
    assert box.calls[0][2] == {"tier": "interactive", "profile_path": None, "isolation": "none"}
    assert box.sessions.grants[0][:3] == (4242, True, "operator_tool")
    assert "walk-tabs" in box.sessions.grants[0][3]
    assert watch.started and watch.stopped
    assert [s.ok for s in report.steps] == [True, True, True]


def test_a_failed_step_stops_the_run_and_still_releases():
    box = FakeBox({
        "find": {"ok": True, "match_count": 2},
        "click": {"ok": True, "verified": "effect"},
    })

    report = run_workflow(box, walk_tabs(), pid=1, watch=FakeWatch())

    assert report.verdict == "failed"
    assert [c[0] for c in box.calls] == ["attach", "find", "release"]
    assert report.steps[0].failures == ["match_count is 2, expected 3"]


def test_the_target_taking_the_foreground_fails_a_run_whatever_the_steps_said():
    box = FakeBox({
        "find": {"ok": True, "match_count": 3},
        "click": {"ok": True, "verified": "effect"},
        "read": {"ok": True, "values": [{"text": "clicks=1"}]},
    })
    watch = FakeWatch(events=[{"kind": "cursor_moved"}, {"kind": "foreground_taken"}])

    report = run_workflow(box, walk_tabs(), pid=1, watch=watch)

    assert report.verdict == "failed"
    assert "took the foreground" in report.error
    assert len(report.interference) == 2


def test_cursor_movement_alone_is_reported_not_judged():
    box = FakeBox({
        "find": {"ok": True, "match_count": 3},
        "click": {"ok": True, "verified": "effect"},
        "read": {"ok": True, "values": [{"text": "clicks=1"}]},
    })

    report = run_workflow(box, walk_tabs(), pid=1,
                          watch=FakeWatch(events=[{"kind": "cursor_moved"}]))

    assert report.passed and report.interference == [{"kind": "cursor_moved"}]


def test_a_run_whose_watch_cannot_see_the_pointer_says_so():
    """On a Wayland desktop the watch reads the foreground and not the
    pointer (#225); the report must not let "no cursor_moved" read as "the
    pointer never moved"."""
    box = FakeBox({
        "find": {"ok": True, "match_count": 3},
        "click": {"ok": True, "verified": "effect"},
        "read": {"ok": True, "values": [{"text": "clicks=1"}]},
    })
    watch = FakeWatch()
    watch.unwatched = "the pointer: not watched here"

    report = run_workflow(box, walk_tabs(), pid=1, watch=watch)

    assert report.passed
    assert "pointer" in report.to_dict()["interference_unwatched"]


def test_a_run_whose_watch_sees_the_pointer_adds_no_note():
    box = FakeBox({
        "find": {"ok": True, "match_count": 3},
        "click": {"ok": True, "verified": "effect"},
        "read": {"ok": True, "values": [{"text": "clicks=1"}]},
    })
    assert "interference_unwatched" not in run_workflow(
        box, walk_tabs(), pid=1, watch=FakeWatch()).to_dict()


def test_a_failed_attach_is_the_report_not_an_exception():
    box = FakeBox({"attach": {"ok": False, "error": {"message": "not approved"}}})

    report = run_workflow(box, walk_tabs(), pid=1)

    assert report.verdict == "failed" and "not approved" in report.error
    assert [c[0] for c in box.calls] == ["attach"]


def test_watchdog_events_from_any_step_are_collected_into_the_report():
    box = FakeBox({
        "find": {"ok": True, "match_count": 3,
                 "watchdog_events": [{"kind": "unexpected_restore"}]},
        "click": {"ok": True, "verified": "effect"},
        "read": {"ok": True, "values": [{"text": "clicks=1"}]},
        "release": {"ok": True, "watchdog_events": [{"kind": "unexpected_foreground"}]},
    })

    report = run_workflow(box, walk_tabs(), pid=1)

    assert [e["kind"] for e in report.watchdog_events] == \
        ["unexpected_restore", "unexpected_foreground"]


def test_an_unknown_tool_fails_the_step_by_name():
    wf = Workflow.from_dict({"steps": [{"tool": "teleport"}]})
    box = FakeBox({})

    report = run_workflow(box, wf, pid=1)

    assert report.verdict == "failed"
    assert report.steps[0].failures == ["no such tool: 'teleport'"]


def test_the_report_leaves_pixels_out():
    report = RunReport(workflow="w", pid=1, started_at=0.0)
    report.attach = {"ok": True, "base64": "AAAA", "nested": {"base64": "BBBB"}}

    data = report.to_dict()

    assert data["attach"]["base64"] == "<png omitted>"
    assert data["attach"]["nested"]["base64"] == "<png omitted>"


# --- the interference watch, fed ---------------------------------------------------

# Reaches InterferenceWatch's real defaults, which bind Win32 through winapi.
@on_windows
def test_the_watch_records_the_target_taking_the_foreground_and_cursor_moves():
    from ghostdriver.backends.windows.interference import InterferenceWatch

    watch = InterferenceWatch(77, foreground_pid=lambda: 0, cursor=lambda: (0, 0),
                              now=lambda: 5.0)

    watch.observe(foreground_pid=99, cursor=(0, 0), last_foreground=0, last_cursor=(0, 0))
    watch.observe(foreground_pid=77, cursor=(0, 0), last_foreground=99, last_cursor=(0, 0))
    watch.observe(foreground_pid=77, cursor=(3, 4), last_foreground=77, last_cursor=(0, 0))

    kinds = [e["kind"] for e in watch.events()]
    assert kinds == ["foreground_taken", "cursor_moved"]
    assert watch.events()[1]["to"] == [3, 4]


# --- the macro format extension (#84) -------------------------------------

def test_a_macro_parses_params_provenance_and_step_flags():
    wf = Workflow.from_dict({
        "name": "embed", "tier": "interactive",
        "params": {"plan_id": {"required": True, "note": "the plan"}},
        "provenance": {"recorded_at": "2026-09-10T00:00:00Z",
                       "recorded_against": "ca4904", "revision": 3},
        "steps": [
            {"tool": "click", "args": {"locator": "type=TabItem name=${plan_id}"},
             "expect": {"verified": "effect"}, "verified": True},
            {"tool": "click", "args": {"locator": "class=THtLeftPanel", "at": {"x": 11, "y": 100}},
             "delivery_only": True, "note": "painted gutter"},
        ],
    })

    assert wf.params == (Param("plan_id", True, "the plan"),)
    assert wf.provenance == Provenance("2026-09-10T00:00:00Z", "ca4904", 3)
    assert wf.steps[0].verified is True and wf.steps[0].delivery_only is False
    assert wf.steps[1].delivery_only is True and wf.steps[1].verified is False


def test_a_legacy_workflow_still_loads_with_empty_params_and_provenance():
    wf = Workflow.from_dict({"steps": [{"tool": "find", "args": {"locator": "x"}}]})

    assert wf.params == () and wf.provenance.is_empty
    assert isinstance(wf.steps[0], Step) and wf.steps[0].verified is False


def test_a_when_branch_parses_with_both_arms():
    wf = Workflow.from_dict({"steps": [
        {"when": {"locator": "class=Funnel", "pressed": True},
         "then": [{"tool": "click", "args": {"locator": "class=Funnel"}}],
         "else": [{"tool": "click", "args": {"locator": "class=Funnel"}},
                  {"tool": "click", "args": {"locator": "class=Funnel"}}],
         "note": "toggle"}]})

    branch = wf.steps[0]
    assert isinstance(branch, Branch)
    assert branch.when == Guard(locator="class=Funnel", pressed=True)
    assert len(branch.then) == 1 and len(branch.otherwise) == 2
    assert branch.note == "toggle"


def test_a_branch_with_no_else_defaults_to_an_empty_arm():
    wf = Workflow.from_dict({"steps": [
        {"when": {"locator": "class=X"}, "then": [{"tool": "click", "args": {"locator": "x"}}]}]})

    assert isinstance(wf.steps[0], Branch) and wf.steps[0].otherwise == ()


def test_a_branch_may_nest_and_too_deep_is_refused():
    inner = {"tool": "click", "args": {"locator": "x"}}
    node = inner
    for _ in range(3):  # a few levels: fine
        node = {"when": {"locator": "class=X"}, "then": [node]}
    Workflow.from_dict({"steps": [node]})  # no raise

    node = inner
    for _ in range(12):  # past MAX_NEST_DEPTH
        node = {"when": {"locator": "class=X"}, "then": [node]}
    with pytest.raises(WorkflowError, match="nest deeper"):
        Workflow.from_dict({"steps": [node]})


@pytest.mark.parametrize("bad", [
    {"steps": [{"tool": "click", "typo": 1}]},                       # unknown step key
    {"steps": [{"when": {"locator": "x"}}]},                          # branch without then
    {"steps": [{"when": {"nope": 1}, "then": [{"tool": "click"}]}]},  # guard unknown key
    {"steps": [{"when": {"selected": True}, "then": [{"tool": "click"}]}]},  # guard without locator
    {"steps": [{"tool": "click", "when": {"locator": "x"}, "then": []}]},    # both tool and when
    {"steps": [{"foo": 1}]},                                          # neither tool nor when
    {"steps": [{"when": {"locator": "x"}, "then": [{"tool": "click"}], "oops": 1}]},  # unknown branch key
    {"steps": [{"tool": "click"}], "params": {"p": {"bad": 1}}},      # unknown param key
    {"steps": [{"tool": "click"}], "provenance": {"revision": "x"}},  # non-integer revision
    {"steps": [{"when": {"locator": "x", "pressed": "yes"}, "then": [{"tool": "click"}]}]},  # non-bool
])
def test_a_malformed_macro_body_is_refused_with_a_reason(bad):
    with pytest.raises(WorkflowError):
        Workflow.from_dict(bad)


def test_the_linear_runner_fails_clean_on_a_branch_until_the_macro_runner():
    """The format holds a branch (#84); executing it is the macro runner's
    job (#85). The linear runner must not crash on one -- it fails clean."""
    box = FakeBox({"click": {"ok": True}})
    wf = Workflow.from_dict({"name": "m", "tier": "interactive", "steps": [
        {"when": {"locator": "class=X"}, "then": [{"tool": "click", "args": {"locator": "x"}}]}]})

    report = run_workflow(box, wf, pid=1234, watch=FakeWatch())

    assert report.verdict == "failed"
    assert any("macro runner" in f for f in report.steps[0].failures)
    assert report.release.get("ok"), "it still released the session"


# --- loops: the format (#97) ----------------------------------------------

def test_a_repeat_until_loop_parses():
    wf = Workflow.from_dict({"steps": [
        {"repeat_until": {"locator": "class=Done"}, "max": 20,
         "do": [{"tool": "click", "args": {"locator": "next"}}], "note": "page"}]})

    loop = wf.steps[0]
    assert isinstance(loop, RepeatUntil)
    assert loop.until == Guard(locator="class=Done") and loop.max == 20
    assert [s.tool for s in loop.do] == ["click"] and loop.note == "page"


def test_a_for_each_loop_parses_a_list_and_a_param():
    inline = Workflow.from_dict({"steps": [
        {"for_each": "row", "in": ["A", "B"],
         "do": [{"tool": "click", "args": {"locator": "${row}"}}]}]})
    assert isinstance(inline.steps[0], ForEach)
    assert inline.steps[0].var == "row" and inline.steps[0].items == ["A", "B"]

    param = Workflow.from_dict({"steps": [
        {"for_each": "x", "in": "${rows}", "do": [{"tool": "click", "args": {"locator": "x"}}]}]})
    assert param.steps[0].items == "${rows}"


@pytest.mark.parametrize("bad", [
    {"steps": [{"repeat_until": {"locator": "x"}, "do": [{"tool": "click"}]}]},   # no max
    {"steps": [{"repeat_until": {"locator": "x"}, "max": 0, "do": [{"tool": "click"}]}]},  # max < 1
    {"steps": [{"repeat_until": {"locator": "x"}, "max": 99999, "do": [{"tool": "click"}]}]},  # over ceiling
    {"steps": [{"repeat_until": {"locator": "x"}, "max": 5}]},                    # no do
    {"steps": [{"for_each": "row", "do": [{"tool": "click"}]}]},                  # no in
    {"steps": [{"for_each": "row", "in": 3, "do": [{"tool": "click"}]}]},         # in not a list/str
    {"steps": [{"for_each": "not an id", "in": [], "do": [{"tool": "click"}]}]},  # bad var (and empty do)
    {"steps": [{"for_each": "row", "in": ["a"], "do": [{"tool": "click"}], "oops": 1}]},  # unknown key
    {"steps": [{"tool": "click", "repeat_until": {"locator": "x"}, "max": 2, "do": []}]},  # two kinds
])
def test_a_malformed_loop_is_refused(bad):
    with pytest.raises(WorkflowError):
        Workflow.from_dict(bad)


# --- reactive handlers: the format (#106) ---------------------------------

def test_a_handler_parses():
    wf = Workflow.from_dict({"steps": [{"tool": "click", "args": {"locator": "x"}}],
        "handlers": [{"on_disturbance": {"window": "class=TConnLostDlg"},
                      "handle": [{"tool": "click", "args": {"locator": "ok"}}],
                      "then": "retry", "max": 5}]})

    assert len(wf.handlers) == 1
    h = wf.handlers[0]
    assert isinstance(h, Handler)
    assert h.window == "class=TConnLostDlg" and h.then == "retry" and h.max == 5
    assert [n.tool for n in h.handle] == ["click"]


def test_a_handler_defaults_then_continue_and_max_three():
    wf = Workflow.from_dict({"steps": [{"tool": "click"}],
        "handlers": [{"on_disturbance": {"window": "class=D"},
                      "handle": [{"tool": "click", "args": {"locator": "ok"}}]}]})
    assert wf.handlers[0].then == "continue" and wf.handlers[0].max == 3


@pytest.mark.parametrize("bad", [
    {"steps": [{"tool": "click"}], "handlers": [{"handle": [{"tool": "click"}]}]},  # no on_disturbance
    {"steps": [{"tool": "click"}], "handlers": [{"on_disturbance": {"window": "*"},
        "handle": [{"tool": "click"}]}]},  # wildcard window
    {"steps": [{"tool": "click"}], "handlers": [{"on_disturbance": {"window": "class=D"}}]},  # no handle
    {"steps": [{"tool": "click"}], "handlers": [{"on_disturbance": {"window": "class=D"},
        "handle": [{"tool": "click"}], "then": "explode"}]},  # bad then
    {"steps": [{"tool": "click"}], "handlers": [{"on_disturbance": {"window": "class=D"},
        "handle": [{"tool": "click"}], "max": 0}]},  # bad max
    {"steps": [{"tool": "click"}], "handlers": [{"on_disturbance": {"window": "class=D"},
        "handle": [{"tool": "click"}], "max": 999}]},  # over ceiling
    {"steps": [{"tool": "click"}], "handlers": [{"on_disturbance": {"nope": 1},
        "handle": [{"tool": "click"}]}]},  # unknown trigger key
    {"steps": [{"tool": "click"}], "handlers": "not-a-list"},
])
def test_a_malformed_handler_is_refused(bad):
    with pytest.raises(WorkflowError):
        Workflow.from_dict(bad)
