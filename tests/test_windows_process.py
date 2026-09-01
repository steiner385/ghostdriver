from tests.conftest import on_windows

pytestmark = on_windows


def test_lists_modules_of_a_live_process(win32_target):
    from ghostdriver.backends.windows.process import list_modules
    mods = [m.lower() for m in list_modules(win32_target)]
    assert any(m.endswith("user32.dll") for m in mods)


def test_module_listing_returns_a_full_module_set(win32_target):
    """memory_maps must return a real module list, not a stub handful.

    This does NOT verify cross-bitness behaviour: the fixture spawns
    sys.executable, always the runner's own bitness. The cross-bitness
    property -- that inspecting a 32-bit target from a 64-bit caller returns
    all modules rather than a few WOW64 stubs -- is only verifiable against a
    real 32-bit target, in the Windows validation session.
    """
    from ghostdriver.backends.windows.process import list_modules
    assert len(list_modules(win32_target)) > 5


def test_reports_executable_and_bitness(win32_target):
    from ghostdriver.backends.windows.process import process_facts
    facts = process_facts(win32_target)
    assert facts.executable.lower().endswith(".exe")
    assert facts.bitness in ("x86", "x64")


def test_reports_dpi_awareness(win32_target):
    """The DPI query must actually answer, not fall back to the sentinel.

    Accepting "unknown" here would let a completely broken shcore path pass:
    every possible return value would be in the accepted set.
    """
    from ghostdriver.backends.windows.process import process_facts
    got = process_facts(win32_target).dpi_awareness
    assert got in ("unaware", "system", "per-monitor"), (
        f"DPI awareness query did not succeed, returned {got!r}"
    )


def test_reports_integrity_level(win32_target):
    """The integrity-level read must actually answer for a same-user target.

    The target runs as us, in our session, at our integrity level, so a None
    here means the token walk failed rather than that the answer is genuinely
    unavailable.
    """
    from ghostdriver.backends.windows.process import process_facts
    got = process_facts(win32_target).integrity_level
    assert got is not None, "integrity-level read returned None for a same-user target"
    assert got in ("untrusted", "low", "medium", "high", "system")


def test_unknown_pid_returns_empty_module_list():
    from ghostdriver.backends.windows.process import list_modules
    # None, not []: a pid that cannot be read is a different answer from a
    # process that genuinely loaded nothing, and toolkit inference acts on
    # the difference.
    assert list_modules(999_999) is None
