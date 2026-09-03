"""A workflow run end to end against the fixture, through the real tools.

The workflow file lives in a temporary operator directory -- the shape the
operator's own directory has -- and names no target: the pid comes from
the runner's argument, as it will for the real application. The fixture
is the only application any workflow in this repository ever names.
"""

import json
import subprocess
import sys
import time

import psutil
import pytest

from ghostdriver.operator import OperatorDir
from ghostdriver.session import SessionManager
from ghostdriver.tools import Toolbox
from ghostdriver.workflow import Workflow, run_workflow
from tests.conftest import on_windows

pytestmark = [on_windows, pytest.mark.slow]
WALK_TABS = {
    "name": "walk-tabs",
    "description": "Find the tabs, switch to the second, read the status line.",
    "tier": "interactive",
    "steps": [
        {"tool": "find", "args": {"locator": "type=TabItem"},
         "expect": {"match_count": 3}},
        {"tool": "click",
         "args": {"locator": 'type=TabItem name="Components"',
                  "expect": {"locator": 'class=GhostFixturePage text="Components"'}},
         "expect": {"verified": "effect"}, "note": "the page switches"},
        {"tool": "read", "args": {"locator": 'class=Static text="/clicks=/"'},
         "expect_contains": {"values.0.text": "clicks="}},
        {"tool": "click", "args": {"locator": "type=TabItem"}, "expect_ok": False,
         "note": "ambiguity is refused"},
    ],
}


@pytest.fixture
def app():
    proc = subprocess.Popen([sys.executable, "-m", "tests.fixtureapp"],
                            stdout=subprocess.PIPE, text=True)
    handles = json.loads(proc.stdout.readline())
    time.sleep(0.4)
    yield handles
    if handles["pid"] != proc.pid:
        try:
            psutil.Process(handles["pid"]).terminate()
        except psutil.Error:
            pass
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def operator_dir(tmp_path):
    folder = OperatorDir.resolve(tmp_path / "operator")
    folder.ensure()
    (folder.workflows / "walk-tabs.json").write_text(json.dumps(WALK_TABS), encoding="utf-8")
    return folder


def test_a_workflow_runs_against_the_fixture_under_the_interference_watch(app, operator_dir):
    from ghostdriver.backends.windows.interference import InterferenceWatch

    workflow = Workflow.load(operator_dir.workflow_path("walk-tabs"))

    report = run_workflow(Toolbox(SessionManager()), workflow, pid=app["pid"],
                          watch=InterferenceWatch(app["pid"]))

    assert report.passed, report.to_dict()
    assert [s.ok for s in report.steps] == [True, True, True, True]
    assert report.steps[1].result["tier_used"] == 3
    assert report.release["ok"]
    assert not [e for e in report.interference if e["kind"] == "foreground_taken"], \
        "the target never took the foreground"


def test_a_failing_expectation_stops_the_run_and_the_report_says_where(app, operator_dir):
    wrong = dict(WALK_TABS, name="wrong", steps=[
        {"tool": "find", "args": {"locator": "type=TabItem"}, "expect": {"match_count": 4}},
        {"tool": "read", "args": {"locator": "class=Static"}},
    ])
    (operator_dir.workflows / "wrong.json").write_text(json.dumps(wrong), encoding="utf-8")

    report = run_workflow(Toolbox(SessionManager()),
                          Workflow.load(operator_dir.workflow_path("wrong")), pid=app["pid"])

    assert report.verdict == "failed"
    assert len(report.steps) == 1
    assert report.steps[0].failures == ["match_count is 3, expected 4"]


def test_the_cli_runs_a_workflow_and_writes_the_report(app, operator_dir):
    """The operator's command, end to end: exit 0 on pass, the verdict and
    every step on stdout, the report under reports/."""
    completed = subprocess.run(
        [sys.executable, "-m", "ghostdriver.cli", "run-workflow", "walk-tabs",
         "--pid", str(app["pid"]), "--operator-dir", str(operator_dir.root)],
        capture_output=True, text=True, timeout=120, check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "walk-tabs: passed (4/4 steps)" in completed.stdout
    reports = list(operator_dir.reports.glob("walk-tabs-*.json"))
    assert len(reports) == 1
    written = json.loads(reports[0].read_text(encoding="utf-8"))
    assert written["verdict"] == "passed"
    assert [s["tool"] for s in written["steps"]] == ["find", "click", "read", "click"]


def test_the_cli_lists_workflows(operator_dir):
    completed = subprocess.run(
        [sys.executable, "-m", "ghostdriver.cli", "list-workflows",
         "--operator-dir", str(operator_dir.root)],
        capture_output=True, text=True, timeout=60, check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout.split() == ["walk-tabs"]


def test_the_cli_refuses_an_operator_directory_inside_this_checkout():
    from pathlib import Path

    completed = subprocess.run(
        [sys.executable, "-m", "ghostdriver.cli", "list-workflows",
         "--operator-dir", str(Path(__file__).resolve().parent)],
        capture_output=True, text=True, timeout=60, check=False,
    )

    assert completed.returncode == 2
    assert "inside the git checkout" in completed.stderr


def test_attach_resolves_a_bare_profile_name_through_the_operator_directory(
        app, operator_dir, monkeypatch):
    """A client of the MCP server says `profile_path="sandbox"`; the server,
    started with the operator directory in its environment, finds
    profiles/sandbox.json there. No path that names a machine crosses the
    wire."""
    import json

    from ghostdriver.operator import ENV_VAR

    (operator_dir.profiles).mkdir(exist_ok=True)
    (operator_dir.profiles / "sandbox.json").write_text(
        json.dumps({"denylist": ["*delete*", "*submit*"]}), encoding="utf-8")
    monkeypatch.setenv(ENV_VAR, str(operator_dir.root))
    from ghostdriver.policy import ConsentSource
    box = Toolbox(SessionManager())
    box.sessions.record_grant(app["pid"], allowed=True, source=ConsentSource.ELICITED)

    attached = box.attach(app["pid"], profile_path="sandbox")

    assert attached["ok"], attached
    assert attached["denylist_patterns"] == 2
