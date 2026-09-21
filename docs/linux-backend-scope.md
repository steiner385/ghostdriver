# Linux backend scope — what AT-SPI can and cannot reach (2026-09-11)

Evidence from driving Bambu Studio 02.08 (wxGTK3) on GNOME/X11 via the a11y bus
(`gi` `Atspi 2.0`; no `pyatspi`).

## Reachable
- Text fields: `Atspi.Text.get_text` reads them; `Atspi.EditableText.set_text_contents`
  + `Return` commits them and Studio shows its modified marker. Works even when the
  window is minimized (`showing=False`).
- Real widgets (toggle/radio/check buttons, GTK dialogs) expose an `Action` with `click`.
- Two instances of one app are told apart by `get_process_id()` (the bus may report a
  sibling pid a few off the launch pid).

## Not reachable
- **Owner-drawn controls** (Bambu's toolbar Slice/Print buttons, sidebar parameter
  labels, custom dialog buttons): empty names and `INT_MIN` extents. D#10 already
  records "cannot touch owner-drawn controls" for the GTK4 fixture; this measurement
  confirms the same negative on wxGTK3. They cannot be located or identified through
  the bus; only screenshot + coordinate click works, and only when the window is
  actually mapped on screen.
- Un-minimizing / raising a window from a script: mutter refuses non-interactive
  activation (a zero-timestamp `_NET_ACTIVE_WINDOW` is logged as a buggy client).
  D#13's nested-display foreground guarantee is the only robust answer.

## Scope decision
1. Reading is in scope (landed: slices 1–2 of #40).
2. Writing is in scope **only for `EditableText` fields**, located by screen position +
   current value, never by label (labels are not exposed).
3. Everything owner-drawn is out of scope for the bus; expose it, if at all, as an
   explicit screenshot-and-click tier with a mapped-window precondition.
4. This backend is a research track. The production tuning path for Bambu Studio is
   `x2d-pro/bambu-studio/tune.py` (edit the project file) + `verify.py` (gate on the
   sliced gcode), then open in Studio. Do not build Studio-specific tuning here.

See `docs/DECISIONS.md` D#115 for the decision this table supports.
