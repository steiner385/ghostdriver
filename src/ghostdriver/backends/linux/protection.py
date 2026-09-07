"""What a Linux read may disclose, given that it cannot tell what it is reading.

Windows never had to decide this. The OS refuses a cross-process `WM_GETTEXT`
on a password field, so the value is not available to leak; `is_protected`
exists there only to tell "protected" from "hung", because both come back
empty-handed (D37). The platform is fail-closed and the driver explains.

AT-SPI does the opposite. It hands the value over -- `Atspi.Text.get_text`
returned the real password for both a `Gtk.PasswordEntry` and a `Gtk.Entry`
with `set_visibility(False)` -- and measured across thirteen surfaces, that
hidden entry is *identical* to a plain one: role, states, interfaces,
attributes, description, accessible id, actions, relations, default text
attributes. The only difference is the content. GTK's input-purpose is not
exposed over the bus, and AT-SPI has no `PROTECTED` state to fall back on
(45 state members; none names one).

So the field that must be protected cannot be detected, and the platform will
not protect it. What is left is to **withhold by class rather than by
detection**: a secret is typed into an editable text entry, so editable text
entries do not disclose their contents by default.

The blast radius is kept deliberately small. Labels, tables, captions, page
tabs and buttons are not somewhere a password is typed, and they read
normally -- which is most of what `read` is for. `SINGLE_LINE` would have
narrowed it further, but GTK does not set it; measured, not assumed.

Nothing here imports `gi`: it takes the role and states as plain data, so the
policy is testable without a desktop and is not entangled with the reader.
"""

from collections.abc import Callable
from enum import Enum

#: Roles whose contents a person types, and could therefore be a secret.
_TYPED_INTO = {"text", "password text", "entry"}

#: The role AT-SPI does identify. `Gtk.PasswordEntry` carries it;
#: `Gtk.Entry(visibility=False)` does not, which is the whole problem.
_DECLARED_PASSWORD = "password text"


class Disclosure(Enum):
    """What may be said about a control's contents."""

    #: Not a field a secret is typed into. Read and return it.
    ALLOWED = "allowed"
    #: The platform says this is a password field. Never disclosed.
    PROTECTED = "protected"
    #: Might be a hidden entry and nothing can say otherwise. Not read
    #: unless the caller explicitly asks for the value.
    WITHHELD = "withheld"


_REASONS = {
    Disclosure.ALLOWED: (
        "not a field contents are typed into, so its text is returned normally"
    ),
    Disclosure.PROTECTED: (
        "this field hides its contents and the toolkit says so; the driver "
        "will not disclose them and will not type into it. If a person must "
        "fill it in, use await_human"
    ),
    Disclosure.WITHHELD: (
        "an editable text field, and on this platform a field that hides its "
        "contents is indistinguishable from one that does not -- so the value "
        "is not read at all. Ask for it explicitly if you need it, or confirm "
        "a value you already know without disclosing it"
    ),
}


def classify(role: str, states: frozenset[str]) -> Disclosure:
    """What may be disclosed about a control with this role and these states."""
    if role == _DECLARED_PASSWORD:
        return Disclosure.PROTECTED
    if role in _TYPED_INTO and "EDITABLE" in states:
        return Disclosure.WITHHELD
    return Disclosure.ALLOWED


def reason(verdict: Disclosure) -> str:
    """Why, in terms a caller can act on."""
    return _REASONS[verdict]


def read(
    role: str,
    states: frozenset[str],
    *,
    read: Callable[[], str | None],
    disclose: bool = False,
) -> tuple[Disclosure, str | None]:
    """The verdict, and the text if the verdict allows it.

    `read` is **not called** unless the value may be returned. Not disclosing
    is not enough on its own: a value that has been fetched exists in this
    process, and from there it reaches a traceback, a log line or a debugger
    without anyone deciding that it should.

    `None` here means *withheld or protected*, never *empty* and never *did
    not answer* -- three different facts, and a caller told the wrong one acts
    on the wrong thing.
    """
    verdict = classify(role, states)
    if verdict is Disclosure.PROTECTED:
        return verdict, None
    if verdict is Disclosure.WITHHELD and not disclose:
        return verdict, None
    return verdict, read()


def confirms(
    role: str,
    states: frozenset[str],
    *,
    expected: str,
    read: Callable[[], str | None],
) -> bool | None:
    """Whether the field holds `expected`, without disclosing what it holds.

    This is what makes withholding affordable. D29 has `set_value` check the
    display after writing, and that needs a *comparison*, not a disclosure --
    the driver already knows what it typed. The answer is a yes or a no, so
    nothing reaches a result, the operator directory's trace (D62), or a
    model's context.

    Returns `None` when the field did not answer, which the deadline (D#9)
    reports as a read that timed out. That is not a mismatch, and saying it
    was would send a caller to fix a value that may be correct.
    """
    if classify(role, states) is Disclosure.PROTECTED:
        return None
    seen = read()
    if seen is None:
        return None
    return seen == expected
