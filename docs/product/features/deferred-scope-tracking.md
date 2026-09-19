---
slug: deferred-scope-tracking
title: Deferred Scope Tracking
state: proposed
labels: [deferred]
---

Every issue the project has deliberately put out of scope stays visible in the feature map, with its reactivation trigger stated, without ever being scheduled as work.

## Problem

Issues #16, #17, #18, #19, #20 are not backlog — each one is explicitly deferred by design, per spec §12 of `docs/superpowers/specs/2026-09-01-desktop-automation-mcp-design.md`, with a named reason or trigger condition recorded in the issue body itself (e.g. #19's "contingency with a named trigger: `hidden_desktop` proving insufficient"; #20's "only if clipboard and export routes both fail," gated on issue #1). None of them fit the existing feature map: `docs/FEATURES.md` and the one entry so far under `docs/product/features/` (`linux-sandboxed-gtk-targets.md`) both describe work that is proposed or in progress, and a deferred-by-design item filed there would misread as scheduled. Without a place that claims them, triage keeps re-raising "where does this belong" for the same five issues.

## Target users

- Maintainers triaging issues, who need to confirm a `deferred`-labeled issue is tracked and visible without accidentally scheduling it.
- Anyone considering picking up a deferred issue, who needs the stated trigger or condition in front of them before starting — several of these issues are explicit that "the current strategy is awkward" is not the trigger, but "the current strategy accepted a target and failed" is.

## Desired outcome

Every issue labeled `deferred` is discoverable from the feature map, each with its reactivation condition stated in one place, so deferred-by-design work stays visible without being mistaken for a queued feature.

## Success metrics

- Every open issue labeled `deferred` has a corresponding entry in this doc; none are undocumented.
- No deferred issue is picked up before its stated trigger is confirmed to have fired.
- Triage stops re-opening "does this belong somewhere" for a `deferred`-labeled issue — the `labels: [deferred]` field routes it here automatically.

## Non-goals

- Scheduling, prioritizing, or estimating this work. "Deferred by design" means none of it is meant to be built until its condition fires; this doc tracks visibility, not a roadmap slot.
- Re-deciding whether an item should be deferred — that call belongs in `docs/DECISIONS.md` and spec §12. This doc does not reopen it. It does not follow that every row has such a record: #16 was dispatched for implementation because it had none, and writing one (D#16) is what closed it. Where an Evidence line below cites only spec §12 and decisions that merely *bear on* the item, the call has not actually been written out, and the next triage run will read the row as unscheduled work.
- A general backlog or "someday" dumping ground. Only issues the spec itself marks deferred (currently #16–#20, all carrying the `deferred` label) belong here — a merely low-priority or unscheduled issue does not.

## Notes

Three of the five (#16, #17, #18) are environment-neutral (`env: any`) — they're deferred on architectural grounds (no interference issue to justify the surface, or belongs to a different layer than the driver), not on a measurement. The other two (#19, #20) are Windows-gated and conditional on a specific future measurement: #19 on `hidden_desktop` proving insufficient, #20 on both the clipboard and export routes failing against a real owner-drawn grid (blocked by issue #1 until that probe runs). None of the five have any code landed — that is the point of the label.

**#16 is now answered rather than deferred (D#16), leaving four.** The two kinds do not behave the same way, and #16 is the evidence. A *conditional* item (#19, #20) survives triage on its trigger: the row says what has to happen first, and a run that checks finds nothing fired. An *architectural* one (#16, #17, #18) has no trigger to check, so "deferred" alone offers a run nothing to bounce off, and #16 was duly dispatched for implementation. The repair is to write the call out where it can be disagreed with, which turns the row from unscheduled into decided. #17 and #18 carry the same shape and no such record yet; that is a gap, not a plan — neither should be picked up to build, and the same reasoning would close them if a maintainer wants it.

## Evidence

- #16 — *Web driver (Playwright) as a first-class target.* **Answered and closed, not deferred — D#16.** No interference issue exists (a browser has its own process and profile), and D58 already drove a real Chromium engine through the existing tool surface adding no tool and no protocol, so a driver would fork the surface rather than extend it (D1). Declined for this repository; a sibling on the orchestration layer if ever. D#16 states the reopening condition, and separates it from the *embedded* browser-protocol question D58 left open, which is a different one.
- #17 — *Deferred: HTTP/API client as a test oracle.* Belongs to orchestration, not the driver — reaching past the surface into the system behind it would blur the D59 boundary (D59, D46).
- #18 — *Deferred: test orchestration and assertion DSL.* The driver already has assertion primitives (operator directory D57, `within=(...)` expectations D31/D32/D48, per-call tracing D62); a DSL on top risks the same boundary creep D60 caught once already.
- #19 — *Deferred: the vm isolation strategy.* Contingent on `hidden_desktop` proving insufficient; not scheduled until that trigger fires (D51, D52, D53, D55). `env: windows`.
- #20 — *Deferred: OCR grid reading.* Contingent on the clipboard and export routes both failing against a real owner-drawn grid; blocked by issue #1 until both are probed (D35, D46, D50). `env: windows`.
- All five issues carry the GitHub `deferred` label (`gh issue view 16|17|18|19|20`), which this doc's `labels:` frontmatter field uses to route future deferred issues here automatically.
