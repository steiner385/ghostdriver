"""The element view (#104, D#104) through the contract, against the real fixture.

`walk_elements_awake`, `is_selected` and `_current_value` had no probe at all
before this one -- every other slice of the Linux backend (tree, modality,
acting) is measured against the fixture, this view was not. Two things this
probe exists to pin down, because guessing would be modelling:

* **`_current_value` withholds every editable entry, not only the password
  ones.** D#34b classifies by role and `EDITABLE` state, and AT-SPI cannot
  tell a plain `Gtk.Entry` from `Gtk.Entry(visibility=False)` -- so both come
  back "", same as the declared `Gtk.PasswordEntry`. A label is not typed
  into, so it discloses normally; that contrast is what proves the withhold
  is deliberate rather than merely "reads nothing".

* **`is_selected` re-reads live state, not the enumeration snapshot.** The
  fixture had nothing carrying `CHECKED`/`SELECTED` until #104 added the "opt
  in" checkbox -- a `Gtk.Notebook` page tab, measured separately, carries
  neither state at all on this toolkit, so it could not have answered this.
  The checkbox is flipped by the fixture's own timer rather than through
  AT-SPI: measured here first, a `Gtk.CheckButton` claims the `Action`
  interface but reports zero actions, the same shape D#10 found for the
  owner-drawn button -- an acting-ladder gap, not a reason this read-side
  probe cannot ask the question at all. `is_selected` is asked before and
  after the flip.

Prints one JSON line.
"""

import json
import os
import subprocess
import sys
import time


def _walk(pid):
    from ghostdriver.backends.linux import elements, tree

    out = []
    for frame in tree.enumerate_process(pid):
        out.extend(elements.walk_elements_awake(frame))
    return out


def _by_name(described, name):
    for element, _ancestors in described:
        if element.name == name:
            return element
    return None


def _dump(element):
    if element is None:
        return None
    return {
        "control_type": element.control_type,
        "name": element.name,
        "rect": list(element.rect),
        "enabled": element.enabled,
        "offscreen": element.offscreen,
        "patterns": list(element.patterns),
        "selected": element.selected,
        "value": element.value,
        "sibling_index": element.sibling_index,
        "is_password": element.is_password,
    }


def main():
    app = subprocess.Popen(
        [sys.executable, "-m", "tests.fixtureapp_gtk",
         "--check-opt-in-after", "8000", "--quit-after", "30000"],
        stdout=subprocess.PIPE, text=True,
        env=dict(os.environ, GDK_BACKEND="x11"),
    )
    announced = json.loads(app.stdout.readline())
    pid = announced["pid"]
    time.sleep(3)

    from ghostdriver.backends.linux import elements

    report = {"pid": pid}

    described = _walk(pid)
    report["count"] = len(described)

    names = {
        "toolbar_new": "New", "plain": "plain entry", "password": "password entry",
        "password_widget": "password widget", "opt_in": "opt in",
        "status": "status", "grid": "results grid", "drawn": "Recalculate",
    }
    by_key = {key: _by_name(described, name) for key, name in names.items()}
    report["elements"] = {key: _dump(el) for key, el in by_key.items()}

    # --- ancestors: the window itself is not one of the returned elements --
    frame_names = [a.name for _e, ancestors in described for a in ancestors
                   if a.control_type == "frame"]
    report["frame_in_ancestors"] = bool(frame_names)

    # --- _current_value: withheld by class, not by absence (D#34b) --------
    report["value"] = {
        key: elements._current_value(el) if el is not None else None
        for key, el in by_key.items() if key in ("plain", "password",
                                                  "password_widget", "status")
    }

    # --- is_selected: None off the pattern, live-read on it ---------------
    status_element = by_key["status"]
    report["is_selected_off_pattern"] = (
        elements.is_selected(status_element) if status_element is not None else "no element"
    )

    opt_in = by_key["opt_in"]
    if opt_in is not None:
        # The 8s mark (--check-opt-in-after) has not passed yet: this reads
        # the state from before the fixture's own timer flips it.
        report["opt_in_selected_before"] = elements.is_selected(opt_in)
        time.sleep(6)
        # Now it has. `is_selected` re-reads live rather than the
        # enumeration snapshot, so the same `AccessibleElement` answers
        # differently without re-walking the tree.
        report["opt_in_selected_after"] = elements.is_selected(opt_in)

    print(json.dumps(report), flush=True)
    app.terminate()
    app.wait(timeout=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
