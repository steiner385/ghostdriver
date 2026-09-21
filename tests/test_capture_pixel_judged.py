"""`capture`'s per-control "judge by pixels" flag (D#63, issue #63).

Backend-free, the same way `surface.py`'s own classifier is tested: what
decides the verdict is structural evidence, not a real window, so a fake
tree and a fake `region_evidence` stand in for both platforms -- including
the platform that does not have one yet.
"""

from types import SimpleNamespace

from ghostdriver.backends import UnsupportedPlatform
from ghostdriver.model.window import WindowNode
from ghostdriver.surface import RegionEvidence
from ghostdriver.tools.screen import _judge_by_pixels


def node(*, text="", children=(), w=900, h=600, responsive=True):
    return WindowNode(
        handle=1, class_name="Canvas", text=text, rect=(0, 0, w, h),
        visible=True, enabled=True, pid=1, children=tuple(children),
        responsive=responsive,
    )


def test_an_owner_drawn_node_is_flagged(monkeypatch):
    monkeypatch.setattr(
        "ghostdriver.tools.screen.current",
        lambda: SimpleNamespace(
            region_evidence=lambda n: RegionEvidence(accessible_elements=0)),
    )

    surface = _judge_by_pixels(node())

    assert surface is not None
    assert set(surface) == {"kind", "access", "reason", "note"}
    assert surface["kind"] == "owner-drawn"
    assert surface["access"] == "pixels"
    assert surface["reason"] and len(surface["reason"]) > 10
    assert "pixels" in surface["note"] and "enabled" in surface["note"]


def test_a_node_a_window_tree_already_decides_is_not_flagged(monkeypatch):
    """A node with its own text is `native`, not `owner-drawn` -- `enabled`
    answers for it fine, and the field would be noise."""
    monkeypatch.setattr(
        "ghostdriver.tools.screen.current",
        lambda: SimpleNamespace(
            region_evidence=lambda n: RegionEvidence(accessible_elements=0)),
    )

    assert _judge_by_pixels(node(text="Save")) is None


def test_a_region_reachable_through_accessibility_is_not_flagged(monkeypatch):
    """Readable another way is not the case `enabled` gets wrong (D#51)."""
    monkeypatch.setattr(
        "ghostdriver.tools.screen.current",
        lambda: SimpleNamespace(
            region_evidence=lambda n: RegionEvidence(
                accessible_elements=40, accessible_named=13)),
    )

    assert _judge_by_pixels(node()) is None


def test_a_backend_without_region_evidence_is_silently_absent(monkeypatch):
    """Linux does not wire `region_evidence` up yet (`backends/linux`). The
    flag is a Windows-motivated bonus on `capture`, not a new way for it to
    fail on a platform this issue never touched."""
    class NoRegionEvidence:
        @property
        def region_evidence(self):
            raise UnsupportedPlatform("region_evidence is not implemented here")

    monkeypatch.setattr(
        "ghostdriver.tools.screen.current", lambda: NoRegionEvidence())

    assert _judge_by_pixels(node()) is None
