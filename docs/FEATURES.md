# Feature Map

## Windows Popup Menu Handling

**Status:** Proposed (triage from issues #135, #136)

**Issues:** #135, #136

### RICE-lite Scores
- **Reach:** 4 — Menu items are common UI elements in desktop applications
- **Impact:** 4 — Menu operations are critical when they fail (command doesn't execute or wrong content rendered)
- **Effort:** 3 — Localized fixes in menu modal loop and capture z-order picking logic
- **Confidence:** 4 — Issues are well-described with clear root causes

### Rationale
Comprises two closely related Windows-specific bugs in popup menu handling:

- **#135** — Clicking menu items closes the menu without posting `WM_COMMAND` to the owner, preventing the menu action from firing. The menu modal loop handles the button pair click but doesn't send the command; fix is localized to menu handling.

- **#136** — Capturing a region over a popup menu renders the window beneath instead of the menu itself (z-order is lost). Current picking logic uses overlap area and size; fix is to prefer the frontmost window at the region's center when it is a candidate.

Both issues affect the core interaction pattern (menus are ubiquitous), and both have clear solutions within isolated code paths.

### Deliverables
- Menu item click posts `WM_COMMAND` to owner after handling close
- Capture region respects popup menu z-order; frontmost window at center preferred in picking

---

## Operator Profile Annotations

**Status:** Proposed (triage from issue #137)

**Issues:** #137

### RICE-lite Scores
- **Reach:** 3 — Useful for power users and repeat operators who want to document control behavior quirks
- **Impact:** 3 — Improves UX by surfacing operational knowledge across sessions, reduces trial-and-error
- **Effort:** 4 — Requires profile storage layer, retrieval during find/click, display integration across multiple surfaces
- **Confidence:** 3 — Request is clear but implementation details need further thought

### Rationale
Cross-platform enhancement: add optional notes per control class to operator profile (e.g., "Toggle Block Edit bar is keyboard-only, not a mouse target"). Surface these notes in `find` and `click` results.

Retains operator knowledge across sessions without manual re-learning. Mechanism is generic: profile key `notes: {class_pattern: text}` (declared in D35), referenced during find/click, displayed in result context.

Spans multiple systems (profile storage, find logic, click result formatting) requiring coordination across code boundaries.

### Deliverables
- Profile schema extended with `notes` field
- Find results include matching notes from profile
- Click results include matching notes from profile
- Operator documentation on profile note syntax and usage
