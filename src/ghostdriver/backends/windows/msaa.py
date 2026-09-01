"""Assess what the legacy accessibility surface offers.

Controls are probed directly by handle rather than by walking children.
oleacc's default proxy synthesizes a title bar, two menu bars, and scroll
bars for every window whether or not they exist, so a child walk reports
large numbers of push buttons that are pure fabrication. Probing named
handles keeps the counts honest.

The distinction that matters is naming versus actuation: a caption tells
you which control you found, a default action tells you that you can do
something with it. A surface that offers the first and not the second is
identification-only.
"""

from dataclasses import dataclass, field

OBJID_CLIENT = 0xFFFFFFFC
CHILDID_SELF = 0


@dataclass
class MsaaAssessment:
    available: bool
    probed: int = 0
    named: int = 0
    with_default_action: int = 0
    verdict: str = "unknown"
    sample: list[str] = field(default_factory=list)
    error: str | None = None


def verdict_for(assessment: "MsaaAssessment") -> str:
    if not assessment.available:
        return "unavailable"
    if assessment.probed == 0:
        return "empty"
    if assessment.with_default_action > 0:
        return "actionable"
    if assessment.named > 0:
        return "identification-only"
    return "unusable"


def assess_msaa(handles: list[int]) -> MsaaAssessment:
    try:
        import ctypes

        import comtypes
        import comtypes.client

        comtypes.client.GetModule("oleacc.dll")
        from comtypes.gen import Accessibility

        comtypes.CoInitialize()
        oleacc = ctypes.oledll.oleacc
    except Exception as exc:  # pragma: no cover - environment dependent
        return MsaaAssessment(available=False, error=f"oleacc unavailable: {exc}")

    named = 0
    actionable = 0
    sample: list[str] = []

    for handle in handles:
        accessible = None
        try:
            pointer = ctypes.POINTER(Accessibility.IAccessible)()
            oleacc.AccessibleObjectFromWindow(
                ctypes.c_void_p(handle),
                ctypes.c_ulong(OBJID_CLIENT),
                ctypes.byref(Accessibility.IAccessible._iid_),
                ctypes.byref(pointer),
            )
            accessible = pointer
        except Exception:
            accessible = None

        name, action, role = "", "", ""
        if accessible:
            for attribute, target in (
                ("accName", "name"), ("accDefaultAction", "action"),
                ("accRole", "role"),
            ):
                try:
                    value = getattr(accessible, attribute)(CHILDID_SELF)
                except Exception:
                    value = None
                if target == "name":
                    name = value or ""
                elif target == "action":
                    action = value or ""
                else:
                    role = str(value) if value is not None else ""

        if name:
            named += 1
        if action:
            actionable += 1
        if len(sample) < 25:
            sample.append(
                f"hwnd=0x{handle:08X} name={name!r} action={action!r} role={role}"
            )

    assessment = MsaaAssessment(
        available=True, probed=len(handles), named=named,
        with_default_action=actionable, sample=sample,
    )
    assessment.verdict = verdict_for(assessment)
    return assessment
