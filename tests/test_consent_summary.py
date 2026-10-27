"""What attach says about the approval it is acting on (#252). Backend-free:
a Grant is plain data."""

import time

from ghostdriver.policy import ConsentSource, Grant


def test_an_approval_is_dated_and_says_it_sets_no_tier():
    given = time.mktime((2026, 10, 21, 9, 30, 0, 0, 0, -1))
    summary = Grant(pid=1, allowed=True, source=ConsentSource.OPERATOR_TOOL,
                    note="draft the reply", at=given).summary()

    assert summary["source"] == "operator_tool"
    assert summary["note"] == "draft the reply"
    assert summary["granted_at"] == "2026-10-21 09:30"
    assert "sets no tier" in summary["covers"]
    assert "restored" not in summary, "said only when it applies"


def test_a_kept_approval_says_it_was_kept_and_where_it_came_from():
    summary = Grant(pid=2, allowed=True, source=ConsentSource.DECLARED,
                    restored=True, inherited_from=1,
                    standing_for=r"C:\Program Files\App\app.exe").summary()

    assert summary["restored"] is True
    assert summary["inherited_from"] == 1
    assert summary["standing_for"].endswith("app.exe")
