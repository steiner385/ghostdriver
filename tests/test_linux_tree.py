"""Slice 1 of the Linux backend: the window tree (#40).

Split by what each part needs. `process_facts`, `descendants`, `parent_map`
and the ELF read need no display at all -- they read `/proc` and the
filesystem -- so they are tested directly and fast. The tree itself needs an
AT-SPI bus, and is covered by `tests/test_linux_atspi.py`'s stack.
"""

import os
import sys

import pytest

from tests.conftest import on_linux

pytestmark = on_linux


def _tree():
    """Imported inside the tests: `ghostdriver.backends.*` at module scope is
    what took the whole suite down on the wrong host once (D74)."""
    from ghostdriver.backends.linux import tree

    return tree


def test_process_facts_describes_this_process():
    facts = _tree().process_facts(os.getpid())
    assert facts.pid == os.getpid()
    assert facts.executable.endswith("python3") or "python" in facts.executable


def test_process_facts_says_unknown_rather_than_guessing_the_windows_fields():
    """`wow64`, `integrity_level` and `dpi_awareness` have no Linux meaning.
    They report the absence rather than a plausible-looking value, because
    `probe/runner.py` writes every one of them into a profile an operator
    reads and diffs, and a guess there is indistinguishable from a reading."""
    facts = _tree().process_facts(os.getpid())
    assert facts.wow64 is False
    assert facts.integrity_level is None
    assert facts.dpi_awareness == "unknown"


def test_bitness_comes_from_the_elf_header():
    """The counterpart of reading the PE header on Windows. This interpreter
    is a real ELF binary, so the answer is real rather than a default."""
    facts = _tree().process_facts(os.getpid())
    assert facts.bitness in ("x86", "x64"), facts.bitness
    assert facts.bitness == ("x64" if sys.maxsize > 2**32 else "x86")


def test_bitness_is_unknown_for_something_that_is_not_an_elf(tmp_path):
    """"unknown" is a real answer here and must not be reachable by accident:
    a default that looked like a measurement is exactly what the field is
    written to avoid."""
    fake = tmp_path / "not-a-binary"
    fake.write_bytes(b"#!/bin/sh\necho hi\n")
    assert _tree()._bitness(str(fake)) == "unknown"
    assert _tree()._bitness("/does/not/exist") == "unknown"


def test_loaded_objects_are_the_toolkit_evidence():
    """`infer_toolkit` reads this list looking for libgtk, libQt, libwx.
    /proc/<pid>/maps is the Linux module list."""
    facts = _tree().process_facts(os.getpid())
    assert facts.modules_readable is True
    assert facts.modules, "no shared objects read for a running interpreter"
    assert all(path.startswith("/") for path in facts.modules)


def test_unreadable_modules_are_distinguished_from_none_matching():
    """pid 1 is owned by root. Its maps are unreadable as this user, and that
    is a different fact from "the process loaded nothing" -- the same
    distinction `modules_readable` exists to keep on Windows."""
    facts = _tree().process_facts(1)
    if facts.modules_readable:
        pytest.skip("running with enough privilege to read pid 1; nothing to prove")
    assert facts.modules == []


def test_descendants_include_the_process_itself():
    assert os.getpid() in _tree().descendants(os.getpid())


def test_descendants_of_a_dead_pid_are_empty_not_an_error():
    """A watch follows a process tree and the tree can vanish under it (D71).
    That is a result, not an exception (D10)."""
    assert _tree().descendants(2**22) == []


def test_parent_map_knows_this_process_parent():
    mapping = _tree().parent_map()
    assert mapping[os.getpid()] == os.getppid()


def test_a_handle_from_a_previous_enumeration_is_refused():
    """WindowNode says a handle is valid only for the enumeration that
    produced it. Win32 recycles handles; this mints them, and a stale one
    must fail loudly rather than resolve to whatever now holds its number."""
    tree = _tree()
    tree._reset()
    with pytest.raises(KeyError, match="not from the current enumeration"):
        tree.direct_children(999_999)
