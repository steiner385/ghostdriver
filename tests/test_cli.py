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
        # argparse.Namespace is always truthy, so asserting on the return
        # value itself proves nothing. Assert the subcommand was recognised.
        args = parser.parse_args(
            [command] + extra_args.get(command, ["--pid", "1"])
        )
        assert args.command == command


def test_describe_accepts_depth_and_all_flags():
    args = build_parser().parse_args(
        ["describe", "--pid", "1", "--depth", "7", "--all"]
    )
    assert args.depth == 7
    assert args.all is True


def test_describe_collapse_threshold_defaults_to_three_and_is_settable():
    """The escape hatch for collapsing must exist and carry a usable default.

    Without it an operator whose target hides its controls behind repeated
    containers has no way to see them from the command line.
    """
    parser = build_parser()
    assert parser.parse_args(["describe", "--pid", "1"]).collapse_threshold == 3
    args = parser.parse_args(
        ["describe", "--pid", "1", "--collapse-threshold", "1000"]
    )
    assert args.collapse_threshold == 1000


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


# --- an unsupported platform is an error, not a traceback ----------------------

def test_an_unsupported_platform_reports_an_error_not_a_traceback(capsys, monkeypatch):
    """Kicking the tires on Linux produced a traceback from every command.

    `UnsupportedPlatform` subclasses `RuntimeError`, not `GhostdriverError`,
    so none of the CLI's handlers caught it and it escaped from
    `list-targets`, `describe`, `find`, `read` and the rest alike. The
    backend's refusal is careful and says where to read about the gap -- and
    a person running the tool saw a stack trace instead.

    `test_unknown_pid_reports_error_not_traceback` above states the same
    principle, and is `@on_windows`, so nothing checked it on the platform
    where the refusal actually fires. This one is platform-neutral: it makes
    the backend refuse wherever it runs.
    """
    from ghostdriver import backends
    from ghostdriver.backends import UnsupportedPlatform

    def refuse():
        raise UnsupportedPlatform("top_level_windows is not implemented on Linux yet.")

    # Patched at the source: the CLI imports `current` inside each command,
    # which is what keeps the module importable on a platform it cannot drive.
    monkeypatch.setattr(backends, "current", refuse)

    code = main(["list-targets"])

    assert code != 0
    err = capsys.readouterr().err
    assert "Traceback" not in err, err
    assert "not implemented on Linux" in err, err
    assert err.lower().startswith("error:"), err
