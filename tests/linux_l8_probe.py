"""L8: an embedded document, on the nested display.

Runs inside the nested session bus as its own process, like the other Linux
probes. Reports one JSON line. Never imported.

Raw `Atspi` calls throughout, not `ghostdriver.backends.linux`, for the same
reason as `linux_tier1_probe.py`: this measures what the platform does, and
the backend module is what gets written once the measurement is in.
"""

import json
import os
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi  # noqa: E402

WAKE_BUDGET_S = 15.0
WAKE_POLL_S = 0.25

#: How long to wait for the page to finish loading before the first ask.
#: The wake question (D58) is about a *loaded* page; asked mid-load the
#: answer was "no document" on a busy box, which is not the same fact.
LOAD_BUDGET_S = 30.0


def _find_role(node, role_name, depth=0, max_depth=25):
    try:
        if node.get_role_name() == role_name:
            return node
    except Exception:
        return None
    try:
        count = node.get_child_count()
    except Exception:
        return None
    if depth >= max_depth:
        return None
    for index in range(count):
        try:
            child = node.get_child_at_index(index)
        except Exception:
            continue
        if child is None:
            continue
        found = _find_role(child, role_name, depth + 1, max_depth)
        if found is not None:
            return found
    return None


def _find_name(node, name_wanted, depth=0, max_depth=25):
    try:
        if node.get_name() == name_wanted:
            return node
    except Exception:
        pass
    try:
        count = node.get_child_count()
    except Exception:
        return None
    if depth >= max_depth:
        return None
    for index in range(count):
        try:
            child = node.get_child_at_index(index)
        except Exception:
            continue
        if child is None:
            continue
        found = _find_name(child, name_wanted, depth + 1, max_depth)
        if found is not None:
            return found
    return None


def _text_containing(node, needle, depth=0, max_depth=25):
    try:
        if "Text" in node.get_interfaces():
            text = Atspi.Text.get_text(node, 0, Atspi.Text.get_character_count(node))
            if needle in text:
                return text
    except Exception:
        pass
    try:
        count = node.get_child_count()
    except Exception:
        return None
    if depth >= max_depth:
        return None
    for index in range(count):
        try:
            child = node.get_child_at_index(index)
        except Exception:
            continue
        if child is None:
            continue
        found = _text_containing(child, needle, depth + 1, max_depth)
        if found is not None:
            return found
    return None


def _actions(node):
    try:
        return [Atspi.Action.get_action_name(node, i)
                for i in range(Atspi.Action.get_n_actions(node))]
    except Exception as exc:
        return [f"<{type(exc).__name__}>"]


def main():
    app = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp_web_gtk", "--quit-after", "60000"],
        stdout=subprocess.PIPE, text=True,
        env=dict(os.environ, GDK_BACKEND="x11"),
    )
    # The first line can be a `load_changed` event rather than the announce,
    # since WebKit fires it before the 200ms announce timer does.
    announced = None
    load_events = []
    while announced is None:
        line = app.stdout.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if "pid" in payload:
            announced = payload
        else:
            load_events.append(payload)

    report = {"announced": announced, "load_events_before_announce": load_events}
    if announced is None:
        print(json.dumps(report), flush=True)
        return 1

    # Keep reading load events after the announce: the first ask waits for
    # the page to say it finished (see LOAD_BUDGET_S).
    def read_events():
        for line in app.stdout:
            line = line.strip()
            if line:
                try:
                    load_events.append(json.loads(line))
                except ValueError:
                    pass
    threading.Thread(target=read_events, daemon=True).start()

    Atspi.init()
    desktop = Atspi.get_desktop(0)
    mine = None
    deadline = time.monotonic() + 10
    while mine is None and time.monotonic() < deadline:
        for index in range(desktop.get_child_count()):
            candidate = desktop.get_child_at_index(index)
            try:
                if candidate is not None and candidate.get_process_id() == announced["pid"]:
                    mine = candidate
                    break
            except Exception:
                continue
        if mine is None:
            time.sleep(0.2)

    report["found_on_bus"] = mine is not None
    if mine is None:
        print(json.dumps(report), flush=True)
        app.terminate()
        return 1

    # The wake question: once the page has loaded, is the document there the
    # first time anything asks, or does it take retrying? Asked only after
    # the page says it finished -- asking mid-load measured the load, not
    # the wake, and failed intermittently on a busy box. How long the load
    # took is recorded, so a slow run explains itself.
    load_started = time.monotonic()
    while time.monotonic() - load_started < LOAD_BUDGET_S:
        if any(e.get("state", "").endswith("FINISHED") for e in load_events):
            break
        time.sleep(0.1)
    report["load_finished_before_ask"] = any(
        e.get("state", "").endswith("FINISHED") for e in load_events)
    report["load_wait_s"] = round(time.monotonic() - load_started, 2)
    doc = _find_role(mine, "document web")
    report["doc_found_on_first_ask"] = doc is not None
    report["doc_children_on_first_ask"] = doc.get_child_count() if doc is not None else None

    woke_at = None
    if doc is None or doc.get_child_count() == 0:
        wake_deadline = time.monotonic() + WAKE_BUDGET_S
        start = time.monotonic()
        while time.monotonic() < wake_deadline:
            time.sleep(WAKE_POLL_S)
            doc = _find_role(mine, "document web")
            if doc is not None and doc.get_child_count() > 0:
                woke_at = time.monotonic() - start
                break
    else:
        woke_at = 0.0
    report["woke_after_s"] = woke_at
    report["doc_present"] = doc is not None and doc.get_child_count() > 0

    if not report["doc_present"]:
        print(json.dumps(report), flush=True)
        app.terminate()
        try:
            app.wait(timeout=10)
        except Exception:
            app.kill()
        return 0

    # Click: tier 1, through Action.DoAction, verified by the page's own effect.
    button = _find_name(mine, "Expand All")
    report["button_found"] = button is not None
    if button is not None:
        report["button_actions"] = _actions(button)
        try:
            report["button_do_action"] = bool(Atspi.Action.do_action(button, 0))
        except Exception as exc:
            report["button_do_action"] = f"<{type(exc).__name__}>"
        time.sleep(0.3)
        report["status_after_click"] = _text_containing(mine, "clicks=")

    # Write: does the tier-1 EditableText route exist on a web input, the
    # way it does on a native GTK entry (D#10)?
    entry = _find_role(mine, "entry")
    report["entry_found"] = entry is not None
    if entry is not None:
        report["entry_interfaces"] = sorted(entry.get_interfaces())
        report["entry_before"] = Atspi.Text.get_text(
            entry, 0, Atspi.Text.get_character_count(entry))
        try:
            report["entry_set_text_contents"] = bool(
                Atspi.EditableText.set_text_contents(entry, "written-by-atspi"))
        except Exception as exc:
            report["entry_set_text_contents"] = f"<{type(exc).__name__}>"
        time.sleep(0.2)
        report["entry_after"] = Atspi.Text.get_text(
            entry, 0, Atspi.Text.get_character_count(entry))

    # Protection: does a web password field carry the same role a native one
    # does, so the existing disclosure policy withholds it with no new code?
    password = _find_role(mine, "password text")
    report["password_role_found"] = password is not None

    # Tabs: SelectionItem is reported from role/state on Linux (D#104), not
    # a pattern -- does a page tab carry SELECTED the way a native one does?
    tab = _find_name(mine, "Components")
    if tab is not None:
        try:
            states = tab.get_state_set()
            report["tab_selected_before"] = bool(states.contains(Atspi.StateType.SELECTED))
            Atspi.Action.do_action(tab, 0)
            time.sleep(0.2)
            states_after = tab.get_state_set()
            report["tab_selected_after"] = bool(
                states_after.contains(Atspi.StateType.SELECTED))
        except Exception as exc:
            report["tab_error"] = f"<{type(exc).__name__}>"

    print(json.dumps(report), flush=True)
    app.terminate()
    try:
        app.wait(timeout=10)
    except Exception:
        app.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
