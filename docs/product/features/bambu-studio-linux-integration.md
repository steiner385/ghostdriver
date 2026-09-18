---
slug: bambu-studio-linux-integration
title: Bambu Studio Linux Integration
state: in-progress
---

Ghostdriver can identify, read, and safely drive Bambu Studio's Flatpak wxGTK3 UI on Linux, within the part of the accessibility tree that is actually reachable.

## Problem

On Linux, Bambu Studio runs sandboxed (Flatpak, wxGTK3) and breaks several assumptions the Linux backend made for ordinary targets: its X windows carry no `_NET_WM_PID`, AT-SPI reports the sandbox's `xdg-dbus-proxy` pid rather than the application's real pid, its wxGTK3 fields don't commit on a display-only write (committing needs a real Enter keystroke — tier-4 live actuation), and `grab_focus` steals the X foreground as a side effect of focusing a field. Its custom-drawn toolbar and sidebar controls aren't exposed on the a11y bus at all. Before this cluster of measurements, a target like this was filed as one the strategy couldn't fit (D53) rather than scoped and driven. Issues #101, #102, #103, #110, #111, #115, #116 are the connected findings and decisions that turn Bambu Studio into a working, explicitly scoped target.

## Target users

- Operators driving Bambu Studio's slicer settings on their own Linux desktop through Ghostdriver, who need the automation to never take the X foreground away from them mid-task.
- Ghostdriver maintainers extending the Linux backend to other sandboxed Flatpak GTK/wx applications, who need the pid-identity and live-actuation patterns established here as precedent.

## Desired outcome

`list-targets` and `attach` resolve Bambu Studio to one consistent identity despite its Flatpak identity split (real pid vs. a11y proxy pid vs. X window). Reading through the a11y bus works unconditionally. Committing a value change — which requires a real Enter on this target — is possible only under an explicit, narrowly scoped "operator-present live actuation" consent grant that aborts the moment the foreground or pointer changes. A write to an unnamed field is addressed by place *and* by what it shows, and confirmed by comparison rather than by reading the value back (D#105), so a wrong-field write is impossible rather than merely unlikely and nothing Studio displays reaches a result, a trace or a model's context. The backend's documented contract matches what the bus can actually reach: `EditableText` fields only, located by position and current value; owner-drawn controls are screenshot-only and out of scope for the bus.

## Success metrics

Status below is as of 2026-09-18, checked against the tree rather than against
issue state — five of the seven driving issues are still open with their
decisions recorded and their code merged (see Notes), so the issues do not
answer this question.

- **Met.** `list-targets` / `attach` resolve Bambu Studio to one identity across the a11y bus, XRes, and psutil, with no manual pid lookup by the operator.
- **Met.** A tier-4 commit against Studio proceeds only when the named window is already the operator's live foreground window; any pointer or focus change during the action aborts it and is reported as a disturbance (D28), never silently falling back to a display-only write.
- **Met on Linux; the Windows half is unverified.** A `set_value` against one of Studio's unnamed, withheld setting fields reports success when the write landed and failure when it did not — confirmed through `confirms_value`, without the field's contents appearing anywhere (D#105, D#34b). Before this, every successful write on a withheld field reported as a failure. `confirms_value` is a cross-platform contract name with a Windows implementation (`backends/windows/text.py`) that D#105 says needs re-verifying on a Windows host; issue #105 stays open on that half alone.
- **Met, and measured.** Reading the element view of a ~2,300-node Studio tree costs no bus traffic beyond the enumeration that already happened (D#104) — measured against a real AT-SPI target in commit `2c4246c`.
- **Met.** `docs/LINUX.md` describes the actual reachable surface: the sandboxed-target correction from D#101, and `set_text`'s two rungs — tier-1 display-only, or tier-4 with a real Enter behind the live-actuation gate (D#102, D#111).
- **Not met, and now blocked mechanically.** `docs/linux-backend-scope.md` states the unreachable half — `EditableText` only, owner-drawn controls screenshot-only, no promise that the bus can locate one. The file is absent from `main`; it exists only on the draft PR #116, which as of 2026-09-18 GitHub reports `mergeable: CONFLICTING` — in one file, measured, not in the file this metric names. This is the capability's one genuinely outstanding metric, and the thing standing in its way is no longer authorship — see Notes.

## Non-goals

- Driving Bambu Studio's owner-drawn toolbar/sidebar controls (Slice/Print buttons, parameter labels) through the a11y bus — out of scope by measurement (#115, #116); only screenshot-plus-coordinate-click applies there. That separate capability now has driving items on both platforms, not just this one (#141, #63 on the Windows side), which is the argument for filing it as its own entry rather than growing this one.
- A general "every sandboxed Flatpak app" solution — the pid-identity bridge (#101, #110) is measured against this one target and stands as precedent, not a guarantee it fits other Flatpaks unchanged.
- Replacing the production tuning path for this printer (`x2d-pro/bambu-studio/tune.py` + `verify.py`); this backend is a research/automation track alongside that path, not a replacement for it.

## Notes

**Most of this cluster has landed.** PR #113 merged the live wxGTK3 slice in one piece, which is why the driving issues read as unbuilt while the code is present: D#101/D#110 (Flatpak pid identity — XRes-resolved real pid, a11y proxy pid, and `application_name` aliasing, in `backends/linux/tree.py` and `backends/linux/display.py`), D#102/D#111 (the operator-present live actuation gate — the tool-layer half in `tools/live.py`, the tier-4 commit and its abort conditions in `backends/linux/live.py`, folding #103), and the two that arrived with it, D#104 (the element view as a read of the enumeration registry, `backends/linux/elements.py`) and D#105 (the place-plus-value locator and `confirms_value`, in `model/locator.py` and `resolve.py`).

**Issues #101, #102, #103, #110 and #111 are still open even though their decisions are recorded and implemented** — treat the decision record, not the issue state, as the signal here, and check `docs/DECISIONS.md` before scheduling any of them as work.

**What is genuinely outstanding**, as of 2026-09-18: the `EditableText`-only scope decision (#115) remains an unmerged *draft* PR #116 (`claude/linux-backend-scope`, adds `docs/linux-backend-scope.md`, last touched 2026-09-11) — so the metric above that names that file is not yet met.

**The outstanding work is written, not unwritten — it is a stale branch, not a blank page.** Whoever picks #115 up should expect a rebase, not an authoring task. The branch already contains both halves: `docs/linux-backend-scope.md` (32 lines: *Reachable* / *Not reachable* / *Scope decision*) and a drafted `### D#115. Linux backend scope: EditableText writes only, owner-drawn controls are screenshot-only` (39 lines appended to `docs/DECISIONS.md`). Two files, both docs, no code. The claim that no `D#115` exists is true only of `main`. What blocks it is that the branch forked at `3e64469` and has not moved since 2026-09-11, while `main` has kept going — the gap widens every week the rebase is deferred, so the count is not worth recording here (it has already been re-edited once); the merge base `3e64469` is the stable fact.

**The conflict is confined to one file, and it is not the new one.** Test-merging `5f9fe2c` against `main` (`git merge-tree --write-tree`, merge base `3e64469`) conflicts in `docs/DECISIONS.md` and nowhere else; `docs/linux-backend-scope.md` applies cleanly, because nothing on `main` has ever touched that path. So this is not a 24-commit rebase — it is re-placing 39 lines in the append-only ledger, which is where this repo's rebases usually collide, because every merged decision appends near the same place. Rebase the decision text into the current iteration by narrative section rather than at the file tail, then mark the PR ready. There is no `D#116` and there should not be: #116 is the PR that carries #115's decision, not a decision of its own.

Issue #105 also stays open on its Windows half: `confirms_value` is an `env: both` contract name, and the Windows implementation needs re-verification on a Windows host before the pair is done. **That Windows half is currently invisible to environment-based triage** — D#105 declares the contract `env: both`, but issue #105 carries the `env: linux` label, so the rule in `CLAUDE.md` ("do not start an issue whose environment you are not on") points a reader at Linux only, and the re-verification has no host that claims it. Whoever picks #105 up should reconcile the label with D#105 first.

**The outstanding item is also the one triage cannot see.** #115 and #116 carry **no GitHub labels at all** — not `env: linux`, not any other — as of 2026-09-18. The work is Linux-only by its nature (it scopes the Linux backend's write surface against an AT-SPI bus), so the environment rule in `CLAUDE.md` has nothing to read and no host claims it. That is the same failure as #105's, in the opposite shape: #105 is labelled and labelled *wrongly* (`env: linux` against a `env: both` contract), #115 is not labelled at all. Both leave a piece of this capability invisible to whoever is choosing what to pick up next. Labelling #115 and #116 `env: linux` costs nothing and is the cheapest unblock available here.

This doc carries no `labels:` field on purpose, and the two facts above are why it cannot usefully acquire one. There is no label common to this cluster: the decided-and-implemented issues (#101, #102, #103, #110, #111) are `env: linux`, which also covers unrelated Linux work (#6, #15, #40), so routing every `env: linux` issue here would be wrong more often than right — while #115 and #116 carry nothing to route on. New issues in this cluster need adding to Evidence by hand.

## Evidence

- #101 — Flatpak a11y proxy pid vs. real pid vs. X window identity; corrects the "Sandboxed applications" paragraph in `docs/LINUX.md`. Decided as D#101 (`docs/DECISIONS.md`).
- #102 — wxGTK3 commit needs a real Enter (tier 4); `grab_focus` both works and steals the X foreground. Decided as D#102.
- #103 — operator-present live actuation consent class; folded into D#111.
- #110 — canonical pid is the a11y application pid; `application_name` aliasing. Decided as D#110; implemented in `src/ghostdriver/backends/linux/tree.py` (`application_name`) and `src/ghostdriver/backends/linux/display.py` (XRes `query_client_ids`).
- #111 — gate the commit path behind operator-present live actuation. Decided as D#111; implemented in `src/ghostdriver/tools/live.py` (the gate and the sandbox-aware naming) and `src/ghostdriver/backends/linux/live.py` (the tier-4 commit, its foreground/pointer re-checks, and the abort-as-disturbance path).
- #115, #116 (PR, **still draft, unmerged, and now conflicting** as of 2026-09-18, branch `claude/linux-backend-scope` at `5f9fe2c`, last touched 2026-09-11) — `EditableText`-only write scope, owner-drawn controls are screenshot-only. Adds two doc files and no code: `docs/linux-backend-scope.md` (absent from `main`) and 39 lines appending `D#115` to `docs/DECISIONS.md`. So the decision text exists on the branch; it is `main` that lacks it. Forked at `3e64469`, `mergeable: CONFLICTING` — measured with `git merge-tree`, the only conflicting path is `docs/DECISIONS.md`; `docs/linux-backend-scope.md` itself applies clean. Both items carry **no labels**, so neither appears in any environment-filtered view — see Notes.

Supporting items, not in the original cluster but load-bearing for it:

- PR #113 (merged) — *"Linux backend: drive a live wxGTK3 target (Bambu Studio)"*. The change that delivered the code behind D#101, D#102, D#104, D#105, D#110 and D#111 together, across `src/ghostdriver/backends/linux/`, `src/ghostdriver/resolve.py`, `src/ghostdriver/model/locator.py` and `src/ghostdriver/session.py`.
- #104 (closed) — the element view is a read of the enumeration registry, not a second bus walk; measured on Studio's ~2,300 nodes. Decided as D#104; implemented in `src/ghostdriver/backends/linux/elements.py`. Measured against a real AT-SPI target in commit `2c4246c`.
- #105 (open, labelled `env: linux`) — `region=` plus `value=` locator and the `confirms_value` contract name; the fix that lets the live commit verify itself on a target whose fields are withheld. Decided as D#105; implemented in `src/ghostdriver/model/locator.py` (the `region` and `value` fields) and `src/ghostdriver/resolve.py` (the `confirm(node, expected)` callback). D#105 itself declares the contract `env: both` and says the Windows side "needs re-verification on a Windows host"; the issue's label does not say so.
- Why "located by position *and* current value" is not a contradiction of the withholding policy (D#34b): the value half is matched by *comparison*, never by disclosure. `_current_value` (`src/ghostdriver/backends/linux/elements.py`) returns `""` for any editable entry, because AT-SPI cannot tell a plain `Gtk.Entry` from a password field — so a `value=` locator is resolved through a `confirm(node, expected) -> bool | None` callback whose contents never reach the resolver, a result, a trace or a model's context (D#105, D#34b). The backend half of that comparison is `confirms_value` in `src/ghostdriver/backends/linux/reading.py`. A consequence worth stating in the map, because it is the behaviour an operator meets first: a `value=` locator supplied *without* a `confirm` is **refused**, not matched loosely (`_value_matches`, `src/ghostdriver/resolve.py`) — the D33 rule applied to withheld content, where the resolver cannot see what it is being asked to match.
- #141 (open, `bug`, `env: windows`) and #63 (open, `env: windows`) — the Windows-side counterparts of the owner-drawn finding: a grid whose `WM_GETTEXT` answers with a generic label rather than its content, and a per-control "state unknowable, judge by pixels" flag. Cited here only to show the owner-drawn non-goal is cross-platform and wants its own entry; neither is work for this capability.
- Related test fixture: `tests/test_linux_studio_scratch.py`.
