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

Three of the five (#16, #17, #18) are environment-neutral (`env: any`) — they're deferred on architectural grounds (no interference issue to justify the surface, or belongs to a different layer than the driver), not on a measurement. The other two (#19, #20) are Windows-gated and conditional on a specific future measurement: #19 on `hidden_desktop` proving insufficient, #20 on both the clipboard and export routes failing against a real owner-drawn grid (blocked by issue #1 until that probe runs). This section used to close "none of the five have any code landed — that is the point of the label"; D#18 measured that claim and it was false when written. #18's code had landed, under another name, and its stated ground ("belongs to a different layer than the driver") was wrong about where that layer is.

**#16, #17, #18 and #19 are now answered rather than deferred (D#16, D#17, D#18, D#19), leaving one.** The repair was the same in three of the four: write the call out where it can be disagreed with, which turns the row from unscheduled into decided. #18 needed a different repair, described below.

**The two kinds differ in their reasons and not in their fate, and #19 is the measurement that showed it.** This section previously claimed that a *conditional* item (#19, #20) survives triage on its trigger — "the row says what has to happen first, and a run that checks finds nothing fired" — while only an *architectural* one (#16, #17, #18) offers a run nothing to bounce off. #19 was then dispatched for implementation anyway, to a Linux session, against its `env: windows` label. So the prediction was wrong in both halves: neither the `deferred` label nor the `env:` label gates dispatch, and a stated trigger is not something a dispatcher reads. The only state that governs is open or closed. D#19 draws the consequence — an unfired contingency belongs in the decision log, not in an open row that keeps being handed to implementers — and keeps the trigger itself intact and reopenable.

**#18 is the measurement that this doc's whole premise is weaker than it reads, and it is the one worth learning from.** This section previously read "#18 is architectural with no record yet; the same reasoning that closed #16 and #17 would close it". D#18 found otherwise: the DSL #18 defers *is already built*, as the macro format, over five issues between D#84 and D#112, during which `src/ghostdriver/workflow.py` went from 297 lines to 948 and acquired params, guards, branches, bounded loops and handlers. No commit in that series mentions #18. So a deferred row does not merely fail to stop a dispatcher (#19's finding) — **it fails to stop the work even when no dispatcher is involved**, because the row is phrased as a subsystem ("a DSL") and the work arrived as five extensions to a file that already existed. Nobody consults a deferral list to add a key to a JSON format. The second success metric above — "no deferred issue is picked up before its stated trigger is confirmed to have fired" — is therefore not met, and was never checkable: this doc can make deferred work *visible*, and that is all it can do.

#20 is what is left. It is conditional and still genuinely blocked on issue #1's probe, so its trigger is checkable in a way #19's was not. It should not be picked up to build. Given #19's and #18's findings, the honest expectation is that being open is what governs, so it will be dispatched anyway; D#19 sets what that session should produce.

## Evidence

- #16 — *Web driver (Playwright) as a first-class target.* **Answered and closed, not deferred — D#16.** No interference issue exists (a browser has its own process and profile), and D58 already drove a real Chromium engine through the existing tool surface adding no tool and no protocol, so a driver would fork the surface rather than extend it (D1). Declined for this repository; a sibling on the orchestration layer if ever. D#16 states the reopening condition, and separates it from the *embedded* browser-protocol question D58 left open, which is a different one.
- #17 — *HTTP/API client as a test oracle.* **Answered and closed, not deferred — D#17.** Reaches past the D59 model into a system that is one target's own, which the fixed-surface constraint (D1) cannot generalize the way it does everything else built here. Declined for this repository; a sibling on the orchestration layer if ever. D#17 states the reopening condition, and separates the real read gap D46 leaves open from the question of where an oracle for it should live.
- #18 — *Test orchestration and assertion DSL.* **Answered and closed, not deferred — D#18. Built, not declined:** the only row of the five answered by reading the source. The macro format *is* the DSL — params, guards, `when` branches, bounded `repeat_until`/`for_each` loops, `on_disturbance` handlers, dotted-path assertions, provenance — shipped across D#84, D#85, D#97, D#106 and D#112 while the row still read "Separate spec, built on this one". The boundary creep D60 caught, and which the issue body predicted, did *not* happen: `workflow.py` imports nothing that drives, every leaf is an ordinary re-authorizing tool call under `RUNNABLE_TOOLS` (D#83), and every control-flow form is bounded by construction. D#18 records the measurement, disambiguates the "orchestration layer" that D#16 and D#17 point at (a different sense, still out), and gives the toolbox-only boundary the test guard the issue asked for.
- #19 — *The vm isolation strategy.* **Answered and closed, not deferred — D#19.** Still contingent rather than declined: the trigger is `hidden_desktop` accepting a target and then failing to isolate it, and nothing on record shows that (D51's guarantee is structural, and D53's real-target run produced the *unfitted* case, which the issue names as not the trigger). What #19 lacked was anywhere for a firing to be written — `docs/VALIDATION.md` names no isolation strategy in any gate — so D#19 restates the trigger, records the check, and makes the firing a decision entry citing it. `env: windows`.
- #20 — *Deferred: OCR grid reading.* Contingent on the clipboard and export routes both failing against a real owner-drawn grid; blocked by issue #1 until both are probed (D35, D46, D50). `env: windows`.
- All five issues carry the GitHub `deferred` label (`gh issue view 16|17|18|19|20`), which this doc's `labels:` frontmatter field uses to route future deferred issues here automatically.
