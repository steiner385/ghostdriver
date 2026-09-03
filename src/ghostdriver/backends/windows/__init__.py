"""The Windows backend, bound to the contract by name.

Loaded lazily: a name is imported from its module the first time it is
asked for, so importing the backend costs nothing and a module that needs
COM is touched only by a caller that needs it.
"""

import importlib
from typing import TYPE_CHECKING, Any

from .. import CONTRACT

if TYPE_CHECKING:
    # The modules this package binds, declared as imports so the structure
    # guard (tests/test_structure.py) can see them reach the entry points;
    # at runtime they load lazily through the table below.
    from . import (  # noqa: F401
        capture,
        elements,
        enumerate,
        grid,
        hidden_desktop,
        hosted,
        input,
        interference,
        isolate,
        modality,
        msaa,
        notice,
        process,
        region,
        restore,
        text,
        uia,
        verbs,
        winapi,
    )

#: contract name -> the submodule that implements it. `None` means the
#: name *is* a submodule (a namespace of verbs, or the raw API).
_WHERE: dict[str, str | None] = {
    "enumerate_process": "enumerate", "top_level_windows": "enumerate",
    "process_facts": "process", "descendants": "process", "parent_map": "process",
    "read_window_text": "text", "is_protected": "text",
    "capture_window": "capture", "CaptureError": "capture",
    "top_level_state": "modality", "blocking_ancestor": "modality",
    "snapshot": "modality", "surface_of": "modality",
    "restore_process": "restore",
    "walk_elements_awake": "elements", "is_selected": "elements",
    "_current_value": "elements",
    "region_evidence": "region", "resolve_hosted_app": "hosted",
    "assess_uia": "uia", "assess_msaa": "msaa",
    "verbs": None, "NAMED_KEYS": "input", "EDIT_ACTIONS": "input", "button_pair": "input",
    "read_clipboard_text": "grid",
    "ink_fraction": "capture",
    "deepest_child_at": "input",
    "copy_route": "grid", "focus_route": "grid",
    "MinimizedWatch": "isolate", "WatchError": "isolate",
    "HiddenDesktop": "hidden_desktop", "InterferenceWatch": "interference",
    "OperatorNotice": "notice",
    "winapi": None,
}
assert set(_WHERE) == set(CONTRACT), set(_WHERE) ^ set(CONTRACT)


class _WindowsBackend:
    platform = "win32"

    def __getattr__(self, name: str) -> Any:
        if name not in _WHERE:
            raise AttributeError(f"the backend contract has no {name!r}")
        module_name = _WHERE[name]
        if module_name is None:
            value: Any = importlib.import_module(f"{__name__}.{name}")
        else:
            value = getattr(importlib.import_module(f"{__name__}.{module_name}"), name)
        setattr(self, name, value)  # bound once; later lookups skip this
        return value


BACKEND = _WindowsBackend()
