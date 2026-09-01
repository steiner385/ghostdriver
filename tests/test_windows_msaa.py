from tests.conftest import on_windows


def _handles(pid, limit=20):
    from ghostdriver.backends.windows.enumerate import enumerate_process
    return [n.handle for n in enumerate_process(pid)[0].walk()][:limit]


@on_windows
def test_probes_controls_and_reports_counts(tk_target):
    from ghostdriver.backends.windows.msaa import assess_msaa
    got = assess_msaa(_handles(tk_target))
    assert got.available is True
    assert got.probed >= 1


def test_verdict_is_identification_only_without_default_actions():
    from ghostdriver.backends.windows.msaa import MsaaAssessment, verdict_for
    assert verdict_for(MsaaAssessment(
        available=True, probed=50, named=40, with_default_action=0,
    )) == "identification-only"


def test_verdict_is_actionable_when_default_actions_exist():
    from ghostdriver.backends.windows.msaa import MsaaAssessment, verdict_for
    assert verdict_for(MsaaAssessment(
        available=True, probed=50, named=40, with_default_action=30,
    )) == "actionable"


def test_verdict_is_unusable_when_nothing_is_named():
    from ghostdriver.backends.windows.msaa import MsaaAssessment, verdict_for
    assert verdict_for(MsaaAssessment(
        available=True, probed=50, named=0, with_default_action=0,
    )) == "unusable"


@on_windows
def test_counts_never_exceed_the_handles_supplied(tk_target):
    """Named and actionable counts must not exceed the handles we asked about.

    oleacc's default proxy fabricates a title bar, two menu bars and scroll
    bars for every window whether or not they exist. An implementation that
    walked children would count that furniture and push these totals above
    the number of handles supplied -- which is the failure this module's
    direct-probing design exists to avoid. Asserting on `probed` alone cannot
    see it, because `probed` is assigned from len(handles) regardless.
    """
    from ghostdriver.backends.windows.msaa import assess_msaa
    handles = _handles(tk_target, limit=5)
    got = assess_msaa(handles)
    assert got.probed == len(handles)
    assert got.named <= got.probed
    assert got.with_default_action <= got.probed


@on_windows
def test_invalid_handles_do_not_raise():
    from ghostdriver.backends.windows.msaa import assess_msaa
    assert assess_msaa([0xDEADBEEF]).probed == 1
