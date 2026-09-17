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

`list-targets` and `attach` resolve Bambu Studio to one consistent identity despite its Flatpak identity split (real pid vs. a11y proxy pid vs. X window). Reading through the a11y bus works unconditionally. Committing a value change — which requires a real Enter on this target — is possible only under an explicit, narrowly scoped "operator-present live actuation" consent grant that aborts the moment the foreground or pointer changes. The backend's documented contract matches what the bus can actually reach: `EditableText` fields only, located by position and current value; owner-drawn controls are screenshot-only and out of scope for the bus.

## Success metrics

- `list-targets` / `attach` resolve Bambu Studio to one identity across the a11y bus, XRes, and psutil, with no manual pid lookup by the operator.
- A tier-4 commit against Studio proceeds only when the named window is already the operator's live foreground window; any pointer or focus change during the action aborts it and is reported as a disturbance (D28), never silently falling back to a display-only write.
- `docs/LINUX.md` and `docs/linux-backend-scope.md` describe the actual reachable/unreachable surface — no promise that the bus can locate an owner-drawn control.

## Non-goals

- Driving Bambu Studio's owner-drawn toolbar/sidebar controls (Slice/Print buttons, parameter labels) through the a11y bus — out of scope by measurement (#115, #116); only screenshot-plus-coordinate-click applies there, and that would be a separate capability if it's ever built.
- A general "every sandboxed Flatpak app" solution — the pid-identity bridge (#101, #110) is measured against this one target and stands as precedent, not a guarantee it fits other Flatpaks unchanged.
- Replacing the production tuning path for this printer (`x2d-pro/bambu-studio/tune.py` + `verify.py`); this backend is a research/automation track alongside that path, not a replacement for it.

## Notes

Two decisions in this cluster already landed in code before this doc existed: D#101/D#110 (Flatpak pid identity — XRes-resolved real pid, a11y proxy pid, and `application_name` aliasing, in `src/ghostdriver/backends/linux/tree.py` and `src/ghostdriver/backends/linux/display.py`) and D#102/D#111 (the operator-present live actuation gate, in `src/ghostdriver/tools/live.py`, which folds #103). What has not landed: the `EditableText`-only scope decision (#115) is still an unmerged draft, PR #116 (`claude/linux-backend-scope`, adds `docs/linux-backend-scope.md`).

## Evidence

- #101 — Flatpak a11y proxy pid vs. real pid vs. X window identity; corrects the "Sandboxed applications" paragraph in `docs/LINUX.md`. Decided as D#101 (`docs/DECISIONS.md`).
- #102 — wxGTK3 commit needs a real Enter (tier 4); `grab_focus` both works and steals the X foreground. Decided as D#102.
- #103 — operator-present live actuation consent class; folded into D#111.
- #110 — canonical pid is the a11y application pid; `application_name` aliasing. Decided as D#110; implemented in `src/ghostdriver/backends/linux/tree.py` (`application_name`) and `src/ghostdriver/backends/linux/display.py` (XRes `query_client_ids`).
- #111 — gate the commit path behind operator-present live actuation. Decided as D#111; implemented in `src/ghostdriver/tools/live.py`.
- #115, #116 (PR, draft, unmerged, branch `claude/linux-backend-scope`) — `EditableText`-only write scope, owner-drawn controls are screenshot-only; adds `docs/linux-backend-scope.md`.
- Related test fixture: `tests/test_linux_studio_scratch.py`.
