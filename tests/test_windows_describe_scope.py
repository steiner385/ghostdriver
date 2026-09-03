"""What `describe` can see, and what it says it cannot.

`describe` is the command an agent reaches for first to orient itself on an
unfamiliar screen. If it silently shows one window while a modal dialog is
holding the application, everything planned from its output is planned
against a UI that cannot answer.
"""


from tests.conftest import on_windows

pytestmark = on_windows


def _describe(pid, capsys, **kw):
    from ghostdriver.cli import cmd_describe

    opts = dict(depth=6, max_nodes=200, show_all=False,
                collapse_threshold=3, all_windows=False)
    opts.update(kw)
    assert cmd_describe(pid, **opts) == 0
    return capsys.readouterr().out


def test_the_default_says_which_windows_it_did_not_look_at(modal_target, capsys):
    """A dialog is a separate top-level window, so the screen an operator
    is looking at may not be the one described."""
    pid, _, _ = modal_target
    out = _describe(pid, capsys)
    assert "--all-windows" in out


def _tree_body(out: str) -> str:
    """The described trees, without the blocking banner.

    The banner names the dialog whether or not that window was described,
    so an assertion about reach has to look past it.
    """
    kept = [ln for ln in out.splitlines() if not ln.startswith("BLOCKED")]
    return chr(10).join(kept)


MODAL_CLASSES = ("GhostdriverModalMainClass", "GhostdriverModalDialogClass")


def test_all_windows_reaches_every_window(modal_target, capsys):
    pid, _, _ = modal_target

    main_only = _tree_body(_describe(pid, capsys))
    every = _tree_body(_describe(pid, capsys, all_windows=True))

    assert sum(c in main_only for c in MODAL_CLASSES) == 1, "one window"
    assert sum(c in every for c in MODAL_CLASSES) == 2, "both windows"


def test_a_modal_dialog_may_legitimately_be_the_main_window(modal_target):
    """Not a bug, and worth stating so it is not "fixed" later.

    While a modal is up the dialog is the only window that can be acted
    on, so selecting it is the right answer. Both windows here carry a
    single visible node, so the selector falls back to size and either may
    win -- what matters is that whichever is chosen is a real window the
    caller can use, and that --all-windows reaches the other.
    """
    from ghostdriver.backends.windows.enumerate import enumerate_process
    from ghostdriver.model.window import select_main_tree

    pid, main, dialog = modal_target
    chosen = select_main_tree(enumerate_process(pid))

    assert chosen.handle in (main, dialog)


def test_the_blocking_dialog_is_labelled_as_such(modal_target, capsys):
    """Listing a dialog among the windows is not enough; a caller needs to
    know that this one is the reason nothing else responds."""
    pid, _, _ = modal_target
    out = _describe(pid, capsys, all_windows=True)

    assert "BLOCKED" in out
    assert out.index("BLOCKED") < out.index("==="), "before any window"
    assert "holding" in out


def test_the_node_budget_is_shared_across_windows(modal_target, capsys):
    """Otherwise output grows with however many windows a process owns --
    185 on a measured target -- which defeats the point of the command."""
    pid, _, _ = modal_target
    out = _describe(pid, capsys, all_windows=True, show_all=True, max_nodes=2)

    shown = [ln for ln in out.splitlines() if "nodes shown" in ln]
    assert shown, out
    count = int(shown[0].split("nodes shown")[0].split(",")[-1].strip())
    assert count <= 2, "the budget is for the whole command, not per window"
    assert "not described" in out, "and what it could not reach is counted"


def test_hidden_windows_are_skipped_and_counted(minimized_target, capsys):
    """summarize() always emits a root node, so without a visibility
    filter every hidden pooled form earns a heading and a line."""
    pid, _, _, _ = minimized_target
    out = _describe(pid, capsys, all_windows=True)

    assert "skipped as not visible" in out or "nothing to describe" in out


def test_a_target_with_nothing_visible_says_so(minimized_target, capsys):
    """Better than an empty tree, which reads as "this window is empty"."""
    from ghostdriver.cli import cmd_describe

    pid, _, _, _ = minimized_target
    # Nothing has been restored, so no window has visible content.
    cmd_describe(pid, depth=4, max_nodes=200, show_all=False,
                 collapse_threshold=3, all_windows=True)
    out = capsys.readouterr().out
    assert "nothing to describe" in out or "skipped as not visible" in out
