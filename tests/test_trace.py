"""The trace: every tool call, written where the operator can read it later.

Pure where it can be -- trimming, writing, reading, the environment rules
-- and through the Toolbox with the fixture for the one claim that
matters: a call made through the tools lands in the file with its tool,
arguments and outcome.
"""

import json
import os

import pytest

from ghostdriver.trace import ENV_VAR, Trace, describe, read, trimmed

# --- trimming -------------------------------------------------------------------

def test_pixels_are_left_out_and_long_values_cut_short():
    event = {"base64": "A" * 5000, "nested": {"base64": "B"}, "text": "x" * 3000,
             "many": list(range(80)), "obj": object()}

    out = trimmed(event)

    assert out["base64"] == "<png omitted>" and out["nested"]["base64"] == "<png omitted>"
    assert out["text"].startswith("x" * 2000) and "1000 more chars omitted" in out["text"]
    assert len(out["many"]) == 51 and out["many"][-1] == "<30 more omitted>"
    assert isinstance(out["obj"], str)


# --- writing and reading -------------------------------------------------------------

def test_events_are_appended_as_json_lines_and_read_back_in_order(tmp_path):
    path = tmp_path / "logs" / "t.jsonl"
    trace = Trace(path)

    trace.record({"tool": "describe", "session_id": "s1", "ok": True})
    trace.record({"tool": "click", "session_id": "s2", "ok": False, "error_kind": "not_found"})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and all("at" in json.loads(line) for line in lines)
    assert [e["tool"] for e in read(path)] == ["describe", "click"]
    assert [e["tool"] for e in read(path, session_id="s2")] == ["click"]
    assert [e["tool"] for e in read(path, tail=1)] == ["click"]


def test_a_disabled_trace_writes_nothing_and_never_raises(tmp_path):
    trace = Trace(None)

    trace.record({"tool": "describe"})

    assert not trace.enabled and list(tmp_path.iterdir()) == []


def test_describe_is_one_readable_line():
    line = describe({"at": 0, "session_id": "abcdef123456xx", "tool": "click", "ok": False,
                     "error_kind": "not_found", "elapsed_ms": 42,
                     "args": {"locator": 'class=Button text="Save"'},
                     "error_message": "no element matches"})

    assert "abcdef123456" in line and "click" in line and "FAIL not_found" in line
    assert "42ms" in line and 'locator=' in line and "no element matches" in line


# --- where it goes -------------------------------------------------------------------

def test_the_trace_lands_under_the_operator_directory(tmp_path, monkeypatch):
    from ghostdriver.operator import ENV_VAR as OPERATOR_ENV

    monkeypatch.setenv(OPERATOR_ENV, str(tmp_path / "ops"))
    monkeypatch.delenv(ENV_VAR, raising=False)

    trace = Trace.from_environment()

    assert trace.enabled
    assert trace.path.parent == (tmp_path / "ops").resolve() / "logs"
    assert trace.path.name.startswith("ghostdriver-") and trace.path.name.endswith(f"-{os.getpid()}.jsonl")


def test_no_operator_directory_means_no_trace(monkeypatch):
    from ghostdriver.operator import ENV_VAR as OPERATOR_ENV

    monkeypatch.delenv(OPERATOR_ENV, raising=False)
    monkeypatch.delenv(ENV_VAR, raising=False)

    assert not Trace.from_environment().enabled


@pytest.mark.parametrize("off", ["0", "off", "false", "no"])
def test_the_trace_can_be_switched_off(tmp_path, monkeypatch, off):
    from ghostdriver.operator import ENV_VAR as OPERATOR_ENV

    monkeypatch.setenv(OPERATOR_ENV, str(tmp_path / "ops"))
    monkeypatch.setenv(ENV_VAR, off)

    assert not Trace.from_environment().enabled


def test_an_explicit_path_wins(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "mine.jsonl"))

    assert Trace.from_environment().path == tmp_path / "mine.jsonl"


# --- through the tools ----------------------------------------------------------------

def test_every_tool_call_is_traced_with_its_arguments_and_outcome(tmp_path, monkeypatch):
    """No desktop needed: an unknown session is refused before anything is
    touched, and the refusal is what gets traced."""
    from ghostdriver.session import SessionManager
    from ghostdriver.tools import Toolbox

    path = tmp_path / "trace.jsonl"
    monkeypatch.setenv(ENV_VAR, str(path))
    box = Toolbox(SessionManager())

    box.describe("nope", depth=2)
    box.click("nope", 'class=Button text="Save"', button="right")
    box.release("nope")

    events = read(path)
    assert [e["tool"] for e in events] == ["describe", "click", "release"]
    assert events[0]["args"] == {"session_id": "nope", "depth": 2}
    assert events[0]["ok"] is False and events[0]["error_kind"] == "not_found"
    assert events[1]["args"]["button"] == "right"
    assert events[2]["ok"] is True and events[2]["result"]["released"] == "nope"
    assert all("elapsed_ms" in e for e in events)


# --- how describe fared at the sizes it met (#227) ------------------------------

def test_the_scale_report_lists_measured_describes_largest_first():
    from ghostdriver.trace import scale_report

    def describe_event(total, shown, chars, truncated, **args):
        return {"tool": "describe", "ok": True, "elapsed_ms": 150, "args": args,
                "result": {"windows_total": total, "nodes_shown": shown, "tree_chars": chars,
                           "truncated": truncated, "elided_by_collapsing": total - shown,
                           "below_depth": 0}}

    events = [
        describe_event(108, 60, 900, False),
        describe_event(1140, 48, 1300, True, max_nodes=80),
        {"tool": "describe", "ok": True, "result": {"blocked": []}},      # before the numbers
        {"tool": "find", "ok": True, "result": {"match_count": 3}},
        {"tool": "describe", "ok": False, "result": {}},
    ]

    lines = scale_report(events)

    assert lines[1].split()[0] == "1140" and lines[2].split()[0] == "108"
    assert "the largest tree held 1140 windows and came back as 1300 characters" in lines[3]
    assert "truncated, and said so" in lines[3]
    assert "1 earlier describe call(s) were traced before the numbers were kept" in lines[4]


def test_the_scale_report_says_when_nothing_was_measured():
    from ghostdriver.trace import scale_report

    lines = scale_report([{"tool": "describe", "ok": True, "result": {"blocked": []}}])

    assert lines[0] == "-- no describe call in this trace recorded its numbers"
    assert "1 earlier describe call(s)" in lines[1]
