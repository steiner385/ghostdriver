import os

import pytest

from tests.conftest import on_windows

pytestmark = on_windows


def test_lists_modules_of_a_live_process(tk_target):
    from ghostdriver.backends.windows.process import list_modules
    mods = [m.lower() for m in list_modules(tk_target)]
    assert any(m.endswith("user32.dll") for m in mods)


def test_module_listing_works_across_bitness(tk_target):
    """psutil memory_maps reads the target's mappings directly.

    The .NET Process.Modules API returns only WOW64 stubs when a 64-bit
    caller inspects a 32-bit process, which silently under-reports. This
    path must not have that failure mode.
    """
    from ghostdriver.backends.windows.process import list_modules
    assert len(list_modules(tk_target)) > 5


def test_reports_executable_and_bitness(tk_target):
    from ghostdriver.backends.windows.process import process_facts
    facts = process_facts(tk_target)
    assert facts.executable.lower().endswith(".exe")
    assert facts.bitness in ("x86", "x64")


def test_reports_dpi_awareness(tk_target):
    from ghostdriver.backends.windows.process import process_facts
    assert process_facts(tk_target).dpi_awareness in (
        "unaware", "system", "per-monitor", "unknown",
    )


def test_reports_integrity_level(tk_target):
    from ghostdriver.backends.windows.process import process_facts
    assert process_facts(tk_target).integrity_level in (
        "untrusted", "low", "medium", "high", "system", None,
    )


def test_unknown_pid_returns_empty_module_list():
    from ghostdriver.backends.windows.process import list_modules
    assert list_modules(999_999) == []
