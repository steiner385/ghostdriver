"""The Linux backend: specified, being measured, not yet built.

docs/LINUX.md says what it will be -- AT-SPI for the tree and actuation, a
nested X server for the structural isolation guarantee -- and, more
importantly, what has to be *measured* first, because every corner of the
Windows backend that mattered was a measurement contradicting a model.

That measuring has started, and has already contradicted the plan twice: a
bare Xvfb has no EWMH, and the nested display needs a D-Bus session bus of
its own before it isolates anything (D#8). `deadline` is the first piece
that survived it -- AT-SPI will not bound a call against a hung application,
so the caller has to (D#9).

Every *contract* name still answers with the same refusal, because none of
them has been built.
"""

from typing import Any

from .. import CONTRACT, UnsupportedPlatform
from . import (
    clipboard,
    elements,
    hidden_desktop,
    interference,
    isolate,
    modality,
    notice,
    reading,
    restore,
    tree,
    verbs,
)
from . import (
    input as _input,
)
from . import winapi as _winapi

#: What is wired, and where it lives. Everything else still refuses. The map
#: is explicit rather than "try the import and see", so a name that is not
#: here refuses with an explanation instead of an AttributeError from three
#: modules down.
#: `tree` is safe to import here even on Windows -- it keeps `gi` inside its
#: functions -- and importing it plainly rather than by name keeps it visible
#: to the reachability guard, which reads imports and cannot follow a string.
_WIRED: dict[str, Any] = {
    # slice 1, the window tree (#40)
    **dict.fromkeys(
        ("enumerate_process", "top_level_windows", "direct_children",
         "process_facts", "descendants", "parent_map", "application_name"),
        tree,
    ),
    # slice 2, reading -- under the deadline (D#9) and the disclosure
    # policy (D#34b)
    **dict.fromkeys(
        ("read_window_text", "is_protected", "disclosure", "confirms_value",
         "capture_window", "CaptureError", "ink_fraction"),
        reading,
    ),
    # elements that are not windows -- the AT-SPI surface as UIA-shaped
    # nodes (#104): identity is position plus value, so these carry extents
    # and defer a field's value to a confirmation (D#104).
    **dict.fromkeys(
        ("walk_elements_awake", "is_selected", "_current_value"),
        elements,
    ),
    # acting extras (#105). No posted pair exists (D#11), so button_pair
    # only refuses what cannot be sent and deepest_child_at is a no-op; the
    # key tables travel XTest inside a live session (D#111).
    **dict.fromkeys(
        ("NAMED_KEYS", "EDIT_ACTIONS", "button_pair", "deepest_child_at"),
        _input,
    ),
    # the clipboard and the two grid routes -- both tier 4 here, because a
    # copy or a focus needs real input on this toolkit (D#11, D#111).
    **dict.fromkeys(
        ("read_clipboard_text", "snapshot_clipboard", "restore_clipboard",
         "copy_route", "focus_route"),
        clipboard,
    ),
    # slice 5a, the minimized watch -- sampling for the neutral policy in
    # ghostdriver.isolation, which decides (D#13, D#14)
    **dict.fromkeys(("MinimizedWatch", "WatchError"), isolate),
    # the interference watch, armed around a live action (D#111); its logic
    # is the neutral one, this supplies the X samplers.
    "InterferenceWatch": interference,
    # slice 3, modality and state. Read from the window manager rather than
    # AT-SPI: nothing goes disabled here, so the accessibility tree carries
    # no modality at all (D#12).
    **dict.fromkeys(
        ("top_level_state", "blocking_ancestor", "snapshot", "surface_of"),
        modality,
    ),
    # ... and un-hiding, which on this window manager also focuses (D#14)
    **dict.fromkeys(("restore_process",), restore),
    # slice 4a, acting -- tier 1 only. Tier 3 does not exist here (D#11)
    # and tier 4 has no isolation to run inside until slice 5b, so several
    # of these ladders are deliberately empty (D53).
    "verbs": verbs,
    # slice 5b, the nested-display strategy (#40, D#40f): a hidden desktop
    # is a second display and bus rather than a second thread on the same
    # ones (see hidden_desktop.py for the measurement that forced the
    # difference), and a notice on the operator's own display for the one
    # tool that needs a person to see it.
    "HiddenDesktop": hidden_desktop,
    "OperatorNotice": notice,
    # slice 3's last name. `winapi` *is* a module -- the contract hands the
    # raw platform API over whole -- which `backends/windows` marks the same
    # way. Deliberately partial: `winapi.__getattr__` refuses an unbuilt
    # name with an explanation rather than an AttributeError.
    "winapi": _winapi,
}

#: Names whose value is the module itself rather than something inside it.
#: `backends/windows` spells this `None` in its own map; here the module is
#: already the value, so this only says not to look inside it.
_IS_MODULE = frozenset({"winapi", "verbs"})


class _LinuxBackend:
    platform = "linux"

    def __getattr__(self, name: str) -> Any:
        if name not in CONTRACT:
            raise AttributeError(f"the backend contract has no {name!r}")
        wired = _WIRED.get(name)
        if wired is not None:
            return wired if name in _IS_MODULE else getattr(wired, name)
        raise UnsupportedPlatform(
            f"{name} is not implemented on Linux yet. The window tree, "
            "reading, modality and state, the minimized watch, elements, "
            "acting (tier 1, and tier 4 under the live-actuation consent), "
            "the interference watch and the nested-display strategy "
            "(HiddenDesktop, OperatorNotice) are wired; this is not part of "
            "them. What is left is assessment -- region_evidence, "
            "resolve_hosted_app, assess_uia, assess_msaa -- against an "
            "embedded document, now measured (D#15) but not yet wired up "
            "here. docs/LINUX.md tracks what has been measured and what "
            "has not."
        )


BACKEND = _LinuxBackend()
