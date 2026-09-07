"""L2: what AT-SPI will and will not tell you about a control.

`docs/LINUX.md` measurement 2 asks which controls answer `Text` and which
only `Name`. The answer is straightforward and is asserted below. What the
measurement did not anticipate is what it turned up on the way, which is a
security finding rather than a reading one:

**AT-SPI hands out the contents of a password field in cleartext, and one of
the two ways of making a password field is indistinguishable from a plain
one.** Both facts are pinned here so that the Linux backend cannot be built
without confronting them, and so that a GTK version which fixes either will
fail these tests loudly rather than quietly widening what the driver reads.

Against GTK 4.14.5. See D#34a.
"""

import pytest

from tests.conftest import on_linux
from tests.test_linux_atspi import report  # noqa: F401  (module-scoped fixture)

pytestmark = [on_linux, pytest.mark.slow]


def _named(tree, name):
    """One node from the shared report, by its accessible name."""
    return tree["by_name"][name]


def test_entries_answer_text_and_buttons_only_name(report):  # noqa: F811
    """The split the measurement asked for. A control that answers `Text` can
    have its value read; one that does not is a `Name` and nothing more."""
    for name in ("plain entry", "password entry", "bound entry"):
        assert "Text" in _named(report, name)["interfaces"], name
    for name in ("Recalculate", "New", "Save", "Find"):
        node = _named(report, name)
        assert "Text" not in node["interfaces"], f"{name} gained a Text interface"
        assert node["name"], "a button with no name is unreachable by a locator"


def test_the_owner_drawn_grid_answers_no_text_at_all(report):  # noqa: F811
    """It paints three rows and offers neither children nor `Text`. Nothing in
    the accessible tree can read it, which is what makes the copy route the
    only exact one (D50, and the Linux half of issue #1)."""
    grid = _named(report, "results grid")
    assert grid["children"] == 0
    assert "Text" not in grid["interfaces"], (
        "the grid answers Text now -- if real, that is a better read route "
        "than the clipboard and issue #1 should hear about it"
    )


def test_a_hidden_entry_is_indistinguishable_from_a_plain_one(report):  # noqa: F811
    """The finding that matters. `Gtk.Entry` told not to show its characters
    reports the same role, the same states and the same interfaces as an
    entry showing them. There is no `PROTECTED` state in AT-SPI to fall back
    on -- 45 state members and none names one -- so on this evidence a driver
    *cannot tell* it is looking at a password field.

    D38 says nothing types into a field that hides its contents. On Windows
    `EM_GETPASSWORDCHAR` answers that question. Here, for this widget,
    nothing does.

    If this test starts failing, GTK has begun distinguishing them and the
    Linux backend gained a signal it does not currently have. That is good
    news and wants acting on, not deleting.
    """
    plain, hidden = _named(report, "plain entry"), _named(report, "password entry")
    assert hidden["role"] == plain["role"] == "text"
    assert hidden["states"] == plain["states"]
    assert hidden["interfaces"] == plain["interfaces"]


def test_the_dedicated_password_widget_is_at_least_distinguishable(report):  # noqa: F811
    """`Gtk.PasswordEntry` does carry a distinct role, so the one signal that
    exists is the role and not a state. A Linux `is_protected` has to be
    built on this, and will therefore be right about the dedicated widget and
    wrong about the entry above."""
    assert _named(report, "password widget")["role"] == "password text"


@pytest.mark.parametrize("field,secret",
                         [("password entry", "hunter2"), ("password widget", "hunter3")])
def test_both_password_fields_hand_out_their_secret_in_cleartext(report, field, secret):  # noqa: F811
    """Neither hiding a field's characters nor using the dedicated widget stops
    `Atspi.Text.get_text` returning the real value. The screen shows bullets;
    the bus gives the password.

    Asserted deliberately, and it is *not* an approval. It is the reason a
    Linux `read` cannot be a thin pass-through of the Text interface: the
    value would land in a tool result, in the trace the operator directory
    keeps (D62), and in a model's context. D37 and D38 exist for exactly
    this, and on Linux they have to be enforced by the driver because the
    toolkit does not enforce them.
    """
    assert _named(report, field)["text"] == secret, (
        "the password no longer comes back in cleartext -- if GTK fixed this, "
        "delete the assertion and say so in the decision log"
    )
