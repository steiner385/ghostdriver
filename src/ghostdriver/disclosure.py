"""What an empty-handed read means, and how to say so.

`read_window_text` returns `str | None`, and `None` has to carry every way a
read can come back with nothing. There are three, and they call for three
different things from a caller:

* **The control did not answer.** The target may be hung. Worth
  investigating.
* **The platform protects it.** A password field, working exactly as
  designed. Nothing to investigate, and nothing a caller should retry.
* **The driver declined to look.** On a platform where a hidden entry is
  indistinguishable from a plain one, editable text is withheld by class
  rather than by detection (D#34b). The control is healthy and the value is
  available on request.

Collapsing any two of those sends a caller to the wrong place. D37 is the
first pair -- "one answer means the target may be hung, the other means a
field is working precisely as designed" -- and D#43 is the second, which
arrived from the other direction when a Linux backend started withholding.

This module is the *reporting* half and holds no platform knowledge: it takes
the verdict a backend already computed and turns it into the fields a caller
reads. Pure, so it is testable without a desktop, and neutral, so both
backends produce the same shape (D59).
"""

from __future__ import annotations

#: Above this fraction of non-background pixels, a control that answered
#: empty is painting something it did not tell us about (D66).
INK_THRESHOLD = 0.02

_PROTECTED_REASON = (
    "this field hides its contents; the system does not disclose them to "
    "another process, and this tool will not type into it. If a person must "
    "fill it in, use await_human"
)

_WITHHELD_REASON = (
    "the control answered; its contents were not read. On this platform a "
    "field that hides what is typed into it is indistinguishable from one "
    "that does not, so editable text is withheld by class rather than by "
    "detection. Pass disclose=true if you need the value, or confirm a value "
    "you already know instead"
)

_UNRELIABLE_NOTE = (
    "answers empty to a text query but renders content; the read path is "
    "unreliable on this control. Verify by capture, or through the value's "
    "effect elsewhere"
)


def describe(class_name: str, raw: str | None) -> dict:
    """The base report for one control's read.

    `None` and `""` stay different answers: one is a control that never
    replied, the other one that replied with nothing. Collapsing them asserts
    a field is empty when it may be full.
    """
    return {"class": class_name, "text": raw, "answered": raw is not None}


def explain_empty_handed(value: dict, *, protected: bool, verdict: str) -> dict:
    """Say *why* a read returned nothing, in place.

    `verdict` is the backend's `disclosure()` answer -- "allowed",
    "protected" or "withheld". `protected` is `is_protected`, which is
    deliberately narrower: it also refuses *typing*, and a wider answer would
    refuse to type into every text field on screen (D38).

    A withheld control is reported as having **answered**, because it did.
    The driver chose not to look, and saying "no answer" would blame the
    target for the driver's own policy -- which is the confusion this whole
    module exists to prevent.
    """
    if protected:
        value["protected"] = True
        value["reason"] = _PROTECTED_REASON
    elif verdict == "withheld":
        value["withheld"] = True
        value["answered"] = True
        value["reason"] = _WITHHELD_REASON
    return value


def note_unreliable(value: dict, ink: float | None) -> dict:
    """An empty answer from a control that is visibly painting something.

    The read path does not work on this control, and reporting "empty" would
    be wrong in the way D66 names -- a caller acts on a blank that is not
    blank. `ink` is None when the desktop cannot be captured to check
    (Wayland, #215); that is said rather than read as "paints nothing".
    """
    if ink is None:
        value["note"] = ("empty, and this desktop could not be checked for "
                         "rendered content -- treat the blank as unverified")
        return value
    if ink > INK_THRESHOLD:
        value["read_unreliable"] = True
        value["rendered_ink"] = ink
        value["note"] = _UNRELIABLE_NOTE
    return value
