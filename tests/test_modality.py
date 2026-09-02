"""Blocking state: pure logic, no desktop required."""

from ghostdriver.modality import (
    TopLevel,
    find_modal_blocks,
    is_blocked,
)


def win(handle, *, cls="TForm", text="", visible=True, enabled=True, owner=0):
    return TopLevel(handle=handle, class_name=cls, text=text,
                    visible=visible, enabled=enabled, owner=owner)


def test_a_visible_dialog_over_a_disabled_owner_is_a_modal_block():
    main = win(1, text="Main", enabled=False)
    dialog = win(2, text="Confirm Delete Record", owner=1)

    blocks, unexplained = find_modal_blocks([main, dialog])

    assert len(blocks) == 1
    assert blocks[0].dialog.handle == 2
    assert blocks[0].blocked.handle == 1
    assert not unexplained


def test_an_enabled_owner_is_not_blocked():
    """A modeless dialog owns nothing and holds nothing.

    Plenty of windows are owned without being modal -- toolbars, palettes,
    find dialogs. Reporting those as blocking would make the signal
    useless.
    """
    main = win(1, text="Main", enabled=True)
    palette = win(2, text="Find", owner=1)

    blocks, unexplained = find_modal_blocks([main, palette])

    assert blocks == []
    assert unexplained == []


def test_a_hidden_owned_window_does_not_count_as_the_blocker():
    """Otherwise a caller is sent to interact with a window that is not
    on screen. The owner is still disabled, so this surfaces as an
    unexplained block instead -- which is the honest description."""
    main = win(1, text="Main", enabled=False)
    hidden = win(2, text="Pooled", visible=False, owner=1)

    blocks, unexplained = find_modal_blocks([main, hidden])

    assert blocks == []
    assert [u.blocked.handle for u in unexplained] == [1]


def test_a_disabled_window_with_no_dialog_at_all_is_unexplained():
    """The state most often misread as "the application has hung".

    A dialog off-screen, on another desktop, or owned by a thread that
    stopped pumping leaves exactly this: nothing responds, and nothing
    visible explains why. Saying so is more useful than silence.
    """
    main = win(1, text="Main", enabled=False)

    blocks, unexplained = find_modal_blocks([main])

    assert blocks == []
    assert len(unexplained) == 1
    assert unexplained[0].blocked.handle == 1


def test_a_stacked_dialog_chain_reports_each_link():
    """Dialogs can open dialogs, and each disables the one below."""
    main = win(1, text="Main", enabled=False)
    first = win(2, text="Edit", enabled=False, owner=1)
    second = win(3, text="Confirm", owner=2)

    blocks, unexplained = find_modal_blocks([main, first, second])

    held = {b.blocked.handle for b in blocks}
    assert held == {1, 2}
    assert unexplained == [], "each disabled window is accounted for"


def test_an_unowned_disabled_dialog_is_not_double_reported():
    main = win(1, text="Main", enabled=False)
    dialog = win(2, text="Confirm", owner=1)
    blocks, unexplained = find_modal_blocks([main, dialog])
    assert len(blocks) == 1 and not unexplained


def test_nothing_blocking_is_the_common_case():
    windows = [win(1, text="Main"), win(2, text="Tool", owner=1)]
    assert not is_blocked(windows)
    assert find_modal_blocks(windows) == ([], [])


def test_a_block_describes_itself_for_an_operator():
    """Both names, because either alone leaves an operator guessing.

    The application caption here is deliberately a made-up one. Targets are
    referred to by their technology profile throughout this project --
    toolkit, bitness, control classes -- never by product or vendor name,
    and sample data is not an exception to that.
    """
    main = win(1, text="Records Client", enabled=False)
    dialog = win(2, text="Confirm Delete Record", owner=1)
    described = find_modal_blocks([main, dialog])[0][0].describe()
    assert "Confirm Delete Record" in described, "which dialog is holding it"
    assert "Records Client" in described, "and which application is held"


def test_an_untitled_dialog_still_names_itself_by_class():
    """A caption is the useful name, but plenty of dialogs have none, and
    "''" tells an operator nothing about what is holding the app."""
    main = win(1, text="Main", enabled=False)
    dialog = win(2, cls="TUDVDialog", text="", owner=1)
    assert "TUDVDialog" in find_modal_blocks([main, dialog])[0][0].describe()


def test_a_disabled_window_is_not_holding_anything():
    """The shape a real target actually has, which the fixture never showed.

    An off-screen application proxy owns both the main window and a dialog,
    and the modal disables the proxy. Both owned windows are visible with a
    disabled owner, so both qualified -- and the tool reported that the
    application was being held by its own main window, naming it as
    something for an operator to go and deal with.

    A disabled window cannot be holding anything. It is being held.
    """
    proxy = win(1, cls="TApplication", text="Records Client", enabled=False)
    main = win(2, cls="TShellWin", text="Records Client - Main",
               enabled=False, owner=1)
    dialog = win(3, cls="TSummaryDetailDlg", text="Error", owner=1)

    blocks, unexplained = find_modal_blocks([proxy, main, dialog])

    assert [b.dialog.text for b in blocks] == ["Error"]
    assert unexplained == [], "the main window is part of the chain, not a puzzle"


def test_the_dialog_still_blocks_when_it_owns_the_chain():
    """The ordinary one-level case has to keep working."""
    main = win(1, text="Records Client", enabled=False)
    dialog = win(2, text="Confirm Delete Record", owner=1)

    blocks, _ = find_modal_blocks([main, dialog])

    assert [b.dialog.text for b in blocks] == ["Confirm Delete Record"]
