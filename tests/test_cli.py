import pytest

from ghostdriver.cli import build_parser, main
from tests.conftest import on_windows


def test_parser_exposes_every_subcommand():
    # find and read both require --locator (see test_find_requires_a_locator
    # below), so they need it here too -- unlike describe and probe, which
    # only need --pid.
    extra_args = {
        "list-targets": [],
        "find": ["--pid", "1", "--locator", "class=X"],
        "read": ["--pid", "1", "--locator", "class=X"],
    }
    parser = build_parser()
    for command in ("list-targets", "describe", "find", "read", "probe"):
        assert parser.parse_args(
            [command] + extra_args.get(command, ["--pid", "1"])
        )


def test_describe_accepts_depth_and_all_flags():
    args = build_parser().parse_args(
        ["describe", "--pid", "1", "--depth", "7", "--all"]
    )
    assert args.depth == 7
    assert args.all is True


def test_find_requires_a_locator():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["find", "--pid", "1"])


def test_find_parses_locator_expression():
    args = build_parser().parse_args(
        ["find", "--pid", "1", "--locator", 'class=A text="b"']
    )
    assert args.locator == 'class=A text="b"'


def test_no_subcommand_returns_nonzero():
    assert main([]) != 0


@on_windows
def test_unknown_pid_reports_error_not_traceback(capsys):
    # main() reaches _main_tree, which imports the Windows backend
    # (backends.windows.enumerate -> winapi, which calls ctypes.WinDLL at
    # module scope). That import raises OSError on any non-Windows host, so
    # this test only exercises the intended behaviour -- an unknown pid
    # reported as a clean error rather than a traceback -- on Windows.
    code = main(["describe", "--pid", "999999"])
    assert code != 0
    assert "no windows" in capsys.readouterr().err.lower()
