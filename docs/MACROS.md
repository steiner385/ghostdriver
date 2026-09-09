# Macros: a specification, built on what already exists

Status: specified, not built. This document is the design for issue #81 --
record, modify, replay and delete macros over MCP, and let a macro respond
to what the UI does rather than only run a fixed line. It is written the way
`docs/LINUX.md` is: the model stated so it can be contradicted by the first
measurement, and a phase order so the risky part comes last.

The one-line reframe, because it is the most useful thing here: **a macro is
`workflow.py` and `batch` joined and given a lifecycle.** Neither is new. The
work is to connect them, persist the result, parameterize it, and add a
small, declarative control-flow vocabulary -- not to build a new subsystem.

## What already exists, and what it becomes

| Piece | Today | In a macro |
|---|---|---|
| `workflow.py` -- `Workflow`, `Step`, `dig`, `check` | A JSON file of steps with dotted-path assertions, run under an interference watch, stop-on-first-failure, a report written to the operator directory. Run from the CLI only. | The **storage format and assertion engine**. Extended with params, control flow, and provenance. |
| `batch` (D#75) | An ephemeral, in-memory list of `{tool, args}` steps with per-step `expect`, an allowlist, per-step tier re-checks, per-step verdicts. | The **execution core**. A macro's linear body runs through it; "save the batch I just ran" and "replay a macro" are one engine. |
| operator dir `workflows/` | Holds `<name>.json`; `list_workflows`, `workflow_path`. | Where macros live. Operator data, never the repo (D60). |
| the ledger (`trace`, operator `logs/`) | Every tool call, with provenance, already recorded. | The **recording source** of last resort -- "recover what I just did". |

Nothing above is discarded. The macro layer is sequencing, persistence,
parameters and branching on top of tools that already refuse what they must.

## The load-bearing principle

**Every leaf of a macro is an ordinary tool call that re-authorizes the
session, re-checks the denylist, refuses ambiguity (D33), and never takes the
foreground.** The macro layer adds order and choice; it never adds a path
around consent. This is the same property that makes `batch` safe (D#75), and
it is what keeps a macro from becoming a way to do, unattended and unchecked,
what a person declined to allow. Three consequences that are not negotiable:

- The batchable **allowlist** governs macro steps too. Lifecycle and consent
  tools (`attach`, `release`, `grant_*`, `launch_isolated`) and the two that
  interrupt a person (`foreground`, `await_human`) are never macro steps.
- A macro carries the **tier** it was recorded at and is enforced per step,
  so a macro grants nothing the live session could not do.
- A **disturbance is still reported, never a verdict** (D28), and a
  **measurement never overrules the person** (D35). A macro that reacts to
  the UI (phase 3) does so only through handlers the operator declared, never
  a general "handle whatever appears".

## The format

A superset of today's `Workflow` JSON. The linear fields are unchanged, so
every workflow that runs now is a valid v1 macro.

```json
{
  "name": "embed-illustrations",
  "description": "Embed every illustration in the resource palette",
  "tier": "interactive",
  "profile": "target-profile-v2",
  "params": {
    "plan_id": {"required": true, "note": "the plan to author"}
  },
  "provenance": {
    "recorded_at": "2026-09-10T14:00:00Z",
    "recorded_against": "ca4904e488df3d61",
    "revision": 3
  },
  "steps": [
    {"tool": "click", "args": {"locator": "type=TabItem name=Illustrations",
      "expect": {"locator": "type=TabItem name=Illustrations", "selected": true}},
     "verified": true},
    {"tool": "click", "args": {"locator": "class=THtLeftPanel", "at": {"x": 11, "y": 100}},
     "verified": false, "delivery_only": true,
     "note": "painted gutter; offset click, cannot verify by locator"}
  ]
}
```

Three additions to a step, all in service of honesty:

- `verified` -- whether this step carried a postcondition that held when it
  was recorded. A step with no `expect` is `verified: false`.
- `delivery_only` + `at` -- an offset click on a painted region. **The least
  replayable thing a macro can hold** (handles recycle, offsets shift, D66),
  and the format says so out loud rather than pretending a coordinate is a
  control.
- `params` at the top, referenced as `${plan_id}` inside `args`. A macro
  that embeds a specific id is a screenshot; one that binds a param at replay
  is a tool. Unbound params are **refused, not guessed** (D33).

`provenance.recorded_against` is a profile id. A macro replayed against a
different profile is warned about, because a locator recorded on one target
class means nothing on another.

## The lifecycle verbs

New MCP tools, named for the verbs in the roadmap. Each is thin over the
existing pieces.

| Tool | Does | Tier |
|---|---|---|
| `macro_record` / `macro_save` | Bracket a session (`record_start` ... `record_save <name>`), buffering the **verified** session-tool calls, then write the macro. Or persist a `batch` step-list directly. Refuses to capture typed secrets, same line `send_keys` already draws. | read-only (it captures) |
| `macro_list` / `macro_show` | Enumerate; read one back with its provenance and per-step verified/delivery flags. | read-only |
| `macro_replay` | Bind `params`, run the body through the batch engine under the interference watch, write a report. `dry_run` resolves params and returns the actions **without acting** -- the plan a mutating macro shows before its first run. | the macro's own tier, per step |
| `macro_delete` | Remove one. Operator data, so it archives rather than hard-deletes, and looks before it removes. | read-only bookkeeping |

Modify is deliberately not a tool. A macro is operator data like a profile;
editing the JSON file, or re-saving over it, is how it changes -- with
`provenance.revision` bumped. A structured-edit tool would be a worse editor
than a text editor and a new surface to get wrong.

### Recording, and the two honest problems

- **Verified steps only, by default.** A recording that keeps blind
  `delivery_only` steps is a pile of clicks nobody can audit. The recorder
  keeps the steps whose `expect` held, and keeps an offset click only when it
  is flagged `delivery_only` so replay knows it cannot confirm it. This is
  the honesty-about-certainty rule made structural.
- **Secrets are never recorded.** Typing characters into a protected field is
  already refused; recording honors the same boundary and points a credential
  step at `await_human`, which by design never carries the value.

## The control-flow vocabulary

Declarative, bounded, and every condition expressed as a locator/`expect` --
the same vocabulary the tools already speak -- so the whole macro stays
inspectable and diff-able. **Deliberately not arbitrary code.** A macro that
embedded Python or JS would stop being something you can read, denylist-check
and trust; it would become a security surface. The power comes from a few
well-chosen forms, not from a general language.

```json
{"when": {"locator": "class=TsfGlowButton name=Filter", "pressed": true},
 "then": [ ... ],
 "else": [ ... ]}

{"repeat_until": {"locator": "class=TsfDBGrid text=\"${target}\""},
 "max": 20,
 "do": [ ... ]}

{"for_each": "row", "in": "${rows}", "do": [ ... ]}

{"on_disturbance": {"window": "class=TConnLostDlg"},
 "handle": [ {"tool": "click", "args": {"locator": "...OK"}} ],
 "then": "retry"}
```

The three shapes, in the order they earn their place:

- **`when` / branch.** "If the funnel reads pressed, click once; else twice."
  Solves the toggle-state problem directly and covers most repetitive work.
  (`pressed` depends on issue #77 landing a readable toggle state; until then
  the condition is a `find`/capture the branch reads.)
- **`repeat_until` / `for_each`.** Page a grid until a value appears
  (generalizing `grid_seek`), or run the embed loop across every illustration
  row. `for_each` over a param list is what turns the ~16-call embed sequence
  into one macro.
- **`on_disturbance` handler.** "When a connection-lost dialog appears,
  dismiss it and retry" -- the exact dialog that froze the app in D20/D48.
  This is the ambitious tier and the one that touches the core principles
  most, so it is phase 3 with its own consent design (below).

## Why reactive handlers are last, and bounded

A general "react to whatever the UI does" is the opposite of this project's
grain: it makes decisions for the operator and turns a reported disturbance
into an automated verdict (D28, D35). So the reactive tier is deliberately
small and operator-owned:

- A handler fires only for a disturbance the operator **named** -- this
  window class, this dialog -- never a wildcard.
- Its actions are ordinary macro steps, so they re-enter the safe tool layer
  and are denylist-checkable. A handler cannot click something a live call
  could not.
- Handlers live in the macro (or the profile), where a person wrote and can
  read them -- not inferred, not learned.
- A handler that would take the foreground, or actuate a denylisted control,
  is refused like any other step, mid-reaction.

The test of the design: a reactive macro can do nothing an operator watching
the screen could not have authorized in advance by naming the case. If it can
surprise them, the scope is wrong.

## The phases, in the order they unblock things

Modeled on how the Windows backend was built -- the smallest useful thing
first, each phase standing on its own.

1. **v1 -- record / replay / delete of linear + `when` macros.** The batch
   engine gains persistence, params, and one branch form. `macro_record`
   (verified steps only), `macro_replay` (with `dry_run`), `macro_list`,
   `macro_show`, `macro_delete`. Provenance marks verified-vs-delivered. This
   alone captures the funnel toggle and any fixed repetitive sequence.
2. **v2 -- loops.** `repeat_until` and `for_each`. Turns the embed loop and
   grid paging into single macros. Needs a bound on iterations (`max`) so a
   macro cannot spin, the same instinct as `pace`'s cap.
3. **v3 -- reactive `on_disturbance` handlers.** Operator-declared, scoped,
   consent-designed as above. Built last because it is where autonomy and the
   consent model meet, and it must not be rushed.

## Open questions, to settle by building

- **Recording source.** Bracketed `record_start`/`record_save` for clean
  intent, with the ledger as a "recover what I just did" fallback -- or is the
  ledger enough on its own with a curation step? The bracket is proposed.
- **`dry_run` fidelity.** How much can a plan show before acting, on a target
  where the next window's existence depends on the previous click? A plan is a
  best effort, and should say which steps it could not resolve without acting.
- **Resumability.** A macro that fails at step 9 of 16 -- replay from the
  start (idempotency not guaranteed on a real application) or resume? v1
  replays from the start and reports where it stopped; resume is deferred.
- **Portability.** A macro recorded against one profile, replayed against
  another: warn, or refuse? Proposed: warn on a profile-id mismatch, refuse
  only when a step's locator cannot resolve.

## How this maps to the code

- `workflow.py` gains the params, control-flow and provenance fields on
  `Workflow`/`Step`, and the runner gains the branch/loop/handler evaluation
  -- still pure with respect to the desktop (toolbox and watch handed in), so
  it is tested with fakes and the tools are tested with the fixture (the
  existing split).
- The execution core is `batch`'s dispatcher, factored so the workflow runner
  and the `batch` tool call the same thing.
- New tools register in `mcp_server.py` and the tier table in `policy.py`,
  exactly as `batch` and `pace` did.
- Everything a macro touches -- the files, the reports -- stays in the
  operator directory. The source tree holds no macro, as it holds no profile
  or workflow (the structure guard, D60).
