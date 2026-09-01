# Iteration 1 Validation Runbook

Run this in a Windows session against a real Profile L1 application. Every
command here is **read-only**: the tool sends only `WM_GETTEXT` and
`WM_GETTEXTLENGTH`, and never a message that can actuate a control.

Refer to the target only by its technology profile throughout this
exercise and in any report you write — toolkit, bitness, control classes —
never by product or vendor name.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest -v
```

On Linux the current suite is 69 passed, 25 skipped: the skipped tests are
gated on `sys.platform == "win32"` and exercise the Windows backend against
a real Tk window in a subprocess. On Windows, none of that platform gate
applies — the whole suite should run, including every test that skips on
Linux, and all of it must pass. A test that still SKIPS on Windows is not
a target-specific quirk; it indicates a platform-detection problem
(something not recognizing the host as Windows) and is worth reporting on
its own, before continuing to the gates below.

## Gate 1 — Target discovery

```bash
ghostdriver list-targets
```

**Pass:** the target application appears with a non-zero window count.

## Gate 2 — Profile correctness

```bash
ghostdriver probe --pid <PID> --out profile.json
```

**Pass:** all of the following are true in `profile.json`.

| Field | Expected for a Profile L1 target |
|---|---|
| `matched_profile` | `L1` |
| `toolkit.inferred` | The target's actual toolkit, with `confidence` `high` or `medium` — or `ambiguous`, which is not a failure; see the `toolkit.confidence` row below |
| `toolkit.evidence` | Names the specific signature modules that drove the inference |
| `toolkit.competing` | A list naming other frameworks whose signatures were also present. Expected empty for a single-toolkit target. |
| `toolkit.confidence` | One of `high`, `medium`, `low`, `ambiguous`. `ambiguous` is not a failure: it means two frameworks' signatures coexist (`toolkit.competing` is non-empty) and the answer is contested rather than clean. When you see it, use the evidence lists to decide which framework is the real host. |
| `executable.bitness` | Matches the target's real bitness |
| `dpi.awareness` | `unaware` for a DPI-virtualized target |
| `uia.verdict` | `unusable` if no element supports a pattern |
| `uia.control_view.with_patterns` | For a target you expect to have no UIA provider: exactly `0`. Any non-zero value means the target exposes real automation patterns and is not the profile you assumed — stop and re-read the tree before continuing. For a target you expect to be accessible: a substantial fraction of `element_count`. |
| `uia.raw_view.element_count` | Recorded, so an empty tree is attributable to the provider rather than the walker |
| `uia.error` | Normally `null`. If set, the UIA walk aborted partway through and the counts it did collect are partial — not wrong, but incomplete. A non-null `error` alongside a non-zero `element_count` means the assessment is incomplete, **not** that the target lacks a UIA provider. |
| `unresponsive_count` | How many controls did not answer a text query within the timeout. Their `text` is unknown rather than genuinely empty. A high count means the tree's text data is not trustworthy overall, and Gate 5 should be read in that light. |
| `msaa.verdict` | `identification-only` when captions exist but default actions do not |
| `window_count` | Within an order of magnitude of the real control count |
| `class_census` | Top entries are the target's real window classes |

The document's other top-level fields — `profile_id`, `integrity_level`,
`command_line`, `actuation_map`, `grid_strategy`, `focus_behavior`,
`denylist`, `environment_allowlist` — are deliberately not part of this
gate: phase 1 either does not determine them or emits them empty for
later curation, so there is nothing here for this gate to check.

**Fail conditions worth reporting rather than working around:**

- `toolkit.inferred` is `unknown` on an application whose toolkit is known.
  The signature table in `probe/toolkit.py` needs an entry.
- `window_count` is small (under 20) for a large application. Enumeration
  is not reaching child windows.
- `uia.raw_view.element_count` is 0 while `window_count` is large. The UIA
  walker is failing rather than the provider being empty.
- `uia.error` is non-null while `uia.verdict` reads `unusable`. This
  combination is ambiguous — the walk may have aborted before it reached
  the elements that would have proved the tree rich — and the probe should
  be re-run before the `unusable` verdict is trusted.

## Gate 3 — Scale, the context-budget question

```bash
ghostdriver describe --pid <PID> --depth 5
ghostdriver describe --pid <PID> --depth 5 --max-nodes 60
```

**Pass:**

- Output is legible and bounded — hundreds of lines, not thousands.
- Repeated sibling controls appear as `[N x ClassName]` rather than N lines.
- Captions survive collapsing.
- With `--max-nodes 60`, output ends with an explicit truncation line.
- `Suggested locators:` lists usable `class=... text="..."` expressions.

**This is the scalability gate.** If a real target's tree cannot be
described within a sensible budget, the summarization thresholds in
`summarize.py` need tuning before Iteration 2 builds an MCP tool on it.

## Gate 4 — Locator correctness

Pick a caption from the suggested locators, then:

```bash
ghostdriver find --pid <PID> --locator "class=<Class> text=\"<Caption>\""
```

**Pass:** matches are correct and the handle, class, rect, and text
columns are populated.

Now the discriminating test. Find a caption that appears on more than one
tab page:

```bash
ghostdriver find --pid <PID> --locator "text=\"<Repeated Caption>\" visible=false"
```

This should return several matches. Scoping one of them to a specific
ancestor is not expressible on the command line in Iteration 1 —
`Locator.parse` has no shorthand syntax for `within`, and there is no flag
that substitutes for it. Verify ancestor scoping from a Python shell
instead, using the API directly:

```python
from ghostdriver.backends.windows.enumerate import enumerate_process
from ghostdriver.model.locator import Locator
from ghostdriver.resolve import resolve

tree = max(enumerate_process(PID), key=lambda t: sum(1 for _ in t.walk()))
loc = Locator(
    text="<Repeated Caption>", visible=None,
    within=Locator(class_name="<TabPageClass>", text="<Tab Caption>", visible=None),
)
print([hex(n.handle) for n in resolve(tree, loc)])
```

**Pass:** exactly one handle is returned, and it differs from the handle
returned when scoping to a different tab page.

**This is the capability gate.** Ancestor scoping is what distinguishes
controls that coordinates cannot tell apart. In Iteration 1 it is reachable
only through the Python API shown above; a command-line equivalent is an
Iteration 2 concern once the MCP tool schema exists.

## Gate 5 — Text reading

```bash
ghostdriver read --pid <PID> --locator "class=<EditClass> visible=true"
```

**Pass:** real field values are returned, and they match what is on screen.
No OCR is involved.

If Gate 2 recorded a non-trivial `unresponsive_count`, treat any missing or
suspiciously empty values here with that in mind — an unresponsive control
reports empty text that is unknown, not confirmed blank.

## Gate 6 — Non-interference

While every command above runs, confirm:

- The mouse cursor does not move.
- The foreground window does not change.
- The target's on-screen state does not change.

Any violation is a defect: Iteration 1 sends no message capable of causing
one, so an observed change means an unintended message is being sent.

## Reporting

Record for each gate: pass or fail, the evidence, and anything surprising.
Attach `profile.json`. Note the target only by its technology profile —
toolkit, bitness, control classes — never by product or vendor name.
