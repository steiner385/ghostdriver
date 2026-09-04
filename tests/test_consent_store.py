"""The consent store must never take the server down (D65, hardened).

A desktop relaunch started two servers within a second; the second could
not delete a stale entry the first still held open, and the unhandled
PermissionError ended it before it served anything.
"""

import json
import os
import stat

from ghostdriver.consent import ConsentStore


def test_an_undeletable_stale_entry_is_skipped_not_fatal(tmp_path):
    folder = tmp_path / "consent"
    folder.mkdir()
    stale = folder / "999999.json"
    stale.write_text(json.dumps({"pid": 999999, "started": 1.0, "allowed": True,
                                 "source": "operator_tool", "note": "", "at": 1.0}),
                     encoding="utf-8")
    os.chmod(stale, stat.S_IREAD)  # Windows refuses to delete a read-only file
    try:
        kept = ConsentStore(folder).load()
    finally:
        os.chmod(stale, stat.S_IWRITE | stat.S_IREAD)

    assert kept == []
    assert stale.exists(), "left for next time, not fatal"


def test_an_unreadable_entry_is_skipped(tmp_path):
    folder = tmp_path / "consent"
    folder.mkdir()
    (folder / "bad.json").write_text("{not json", encoding="utf-8")

    assert ConsentStore(folder).load() == []
