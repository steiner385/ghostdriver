# Desktop Automation MCP — Design

**Date:** 2026-09-01
**Status:** Approved design, pending implementation plan
**Scope of this spec:** Windows backend and core model. Linux/X11 gets its own spec.

---

## 1. Purpose

An MCP server that lets an agent drive desktop applications programmatically, for
automated testing and unattended task execution, **without contending with a human
user working on the same machine**.

The general-purpose goal is constrained by one hard requirement: it must efficiently
drive applications in the **legacy message-driven toolkit** profile (§2.1). That
profile is the tier most automation frameworks skip, and skipping it is what makes
them useless against the large installed base of enterprise line-of-business software.

### 1.1 Success criteria

1. An agent can locate, actuate, and read controls in a Profile L1 application.
2. Doing so does not move the user's mouse cursor.
3. Doing so does not steal the user's foreground window.
4. Onboarding a new application requires running a probe, not writing code.
5. An action that cannot verify it succeeded reports failure, never success.
6. Driving a target connected to a disallowed environment is refused by the tool.

### 1.2 Non-goals

- Replacing API-level or protocol-level testing. Where a backing service exists, it is
  a better test *oracle* than the GUI. This tool drives the UI because the UI is the
  system under test, not because it is the most convenient interface to the data.
- Pixel-perfect visual regression testing.
- Recording and replaying human input sessions.
- Driving applications that render entirely to a canvas with no window structure and
  no accessible surface. Those require OCR-only operation, which is supported but
  explicitly second-class.

---

## 2. Target capability profiles

A **capability profile** describes how an application exposes itself to automation. It
is the unit of generalization: the driver is written against profiles, never against
applications.

### 2.1 Profile L1 — legacy message-driven toolkit

The primary hard target. Characteristics, all confirmed by direct measurement against
a reference application:

| Property | Observed |
|---|---|
| Architecture | 32-bit, running under WOW64 |
| Toolkit | Delphi VCL (Embarcadero, VCL/RTL package generation 17.0) |
| UIA provider | **None.** Generic HWND fallback only |
| UIA tree | 92 elements, **100% `ControlType.Pane`**, **zero** elements supporting any of 12 tested patterns |
| UIA stability under Raw view | Identical to Control view at depth 16; tree terminates naturally at depth 12 |
| UIA `Name` | Internal component name or empty — *not* the user-visible caption |
| UIA `AutomationId` | The HWND in decimal; regenerated per run, useless as a selector |
| MSAA | Captions available as `accName`; **no `accDefaultAction`**; roles report `client` |
| Window structure | ~1,100 HWNDs, one per control, vendor-registered classes |
| Caption readability | `GetWindowTextW` returns real user-visible captions cross-process |
| Data grids | Owner-drawn, **zero child HWNDs**, no text via any accessibility surface |
| Text fields | Superclassed native `EDIT` (`ES_AUTOHSCROLL｜ES_AUTOVSCROLL｜ES_MULTILINE`, `WM_GETDLGCODE`=`0x8D`) |
| Custom buttons | `WM_GETDLGCODE`=`0`, `GWL_STYLE`=`0x54000000`, no `BS_*` bits, app-registered class atom |
| DPI | Virtualized. Logical 1536×900 vs physical 1920×1125 at 125% scaling |
| Embedded web | A WebView2 subtree hosts part of the UI |

**Actuation findings — the core of the design:**

| Message form | Result |
|---|---|
| `PostMessage(BM_CLICK)` | No-op |
| `SendMessageTimeout(BM_CLICK)` | No-op, returns 0 |
| `PostMessage(WM_LBUTTONDOWN)` + `PostMessage(WM_LBUTTONUP)` | **Works** |
| Same, while target is backgrounded | Works |
| Same, while target is minimized | Works, and the window stays minimized |
| Cursor disturbed | **Never** |
| Foreground disturbed | **Yes** — target self-foregrounds 300 ms–1.3 s after actuation, from its own handler |

`wParam` = `MK_LBUTTON` on the down message; `lParam` = `MAKELPARAM(clientX, clientY)`
at the control's client-relative centre.

**Why `BM_CLICK` fails:** it is implemented by the comctl32 `BUTTON` window procedure.
A vendor-registered class has no such procedure, so the message reaches `DefWindowProc`
and is discarded.

**Generalized rule — send input-shaped messages, never semantic ones.** Semantic
messages (`BM_CLICK`, `LVM_*`, `TVM_*`) assume a specific window class. Input-shaped
messages (`WM_LBUTTONDOWN`/`UP`, `WM_CHAR`, `WM_KEYDOWN`/`UP`) assume only that the
toolkit implements mouse and keyboard handling, which every GUI toolkit does. This is
what allows one driver to serve VCL, MFC, VB6, PowerBuilder, and older WinForms rather
than needing a separate implementation per toolkit.

### 2.2 Profile M1 — modern accessible toolkit

WPF, WinForms, UWP/WinUI, and Chromium with renderer accessibility enabled. Rich UIA
tree with working patterns. Tier 1 of the ladder applies directly. Supported, but not
the design driver — most existing tools already handle it.

### 2.3 Profile W1 — embedded web content

A Chromium-family web view hosted inside a native shell. Detected by window class and
loaded modules. Addressed by a separate driver, not by native-window techniques.

### 2.4 Profile O1 — opaque

No accessible surface, no per-control windows. OCR and coordinate input only.
Supported and explicitly degraded: assertions are fuzzy and DPI-fragile.

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────┐
│  MCP tool surface          15 stable tools           │
├──────────────────────────────────────────────────────┤
│  Session manager                                     │
│    target lifecycle · isolation strategy · profile   │
├──────────────────────────────────────────────────────┤
│  Core model            (platform-agnostic)           │
│    Locator · Element · action verbs · tier selection │
├───────────────┬──────────────┬───────────────────────┤
│ Windows       │ Linux/X11    │ Web                   │
│ pywinauto +   │ AT-SPI       │ Playwright            │
│ custom layer  │ (later spec) │ (later spec)          │
└───────┬───────┴──────────────┴───────────────────────┘
        │
   Tier ladder — per element, selected by profile:
     1  UIA pattern invoke
     2  MSAA default action
     3  input-shaped window messages      ← Profile L1 tier
     4  synthetic input at resolved rect
     5  capture + OCR                     (read-only)
```

### 3.1 Foundation

The Windows backend **extends pywinauto** rather than reimplementing it. pywinauto's
`win32` backend already provides window enumeration, locator resolution with retries,
DPI handling, and a large body of edge-case fixes. Its weakness is precisely Profile
L1: it treats vendor-registered classes as generic and has no actuation strategy for
them beyond synthetic input.

We add:
- **Custom control adapters** keyed on window class, supplying actuation and read
  strategies per class.
- **The input-shaped message tier**, which pywinauto does not implement as a
  first-class fallback.
- **The capability probe and profile document** (§5).
- **Tier selection and fallback** across the ladder.

### 3.2 Cross-platform guard

The Linux backend is out of scope for this spec. To avoid baking Win32 assumptions
into abstractions that will later need to serve AT-SPI, the core model's public
surface must not expose Win32 types — no `HWND`, no window messages, no `LPARAM`
packing above the backend boundary. Backends translate. This is a type-discipline
rule, not additional work.

---

## 4. Core model

### 4.1 Locator

A declarative, serializable query. Stable across process restarts. This is what the
MCP tools accept and return.

```
Locator {
  class?    string      window class name, exact or glob
  text?     string      caption, exact or regex
  role?     enum        normalized role, mapped per profile
  within?   Locator     ancestor scoping
  visible?  bool        default true
  index?    int         nth match; last resort, discouraged
}
```

**`within` and `visible` are mandatory features, not conveniences.** The reference
application contains identically-captioned controls occupying identical rectangles on
different tab sheets — distinguishable only by ancestor — and control classes with 79
instances of which zero are visible. A locator model lacking either predicate fails on
Profile L1 immediately.

### 4.2 Element

A resolved handle plus metadata. **Ephemeral.** Never crosses the MCP boundary, never
cached across calls, invalidated aggressively.

**Rationale, learned by direct observation:** when a profiled process terminated,
every previously captured handle became void, because the OS recycles handles. Any
design that hands out handle-shaped identifiers is broken. Element references are
always re-resolved from a locator at call time.

Stale-element policy: re-resolve once transparently, then fail with a distinguishable
error.

### 4.3 Action verbs

Each verb is implemented at multiple tiers; the profile selects the starting tier and
failures fall through the ladder.

| Verb | Tier 1 (UIA) | Tier 3 (messages) | Tier 4 (synthetic) |
|---|---|---|---|
| `click` | `InvokePattern` | `WM_LBUTTONDOWN`+`UP` pair | `SendInput` at rect |
| `read` | `ValuePattern` / `TextPattern` | `WM_GETTEXT` | OCR (tier 5) |
| `set_text` | `ValuePattern.SetValue` | `WM_SETTEXT` or `WM_CHAR` sequence | typed `SendInput` |
| `set_value` | `SelectionItemPattern` etc. | class-specific adapter | synthetic navigation |
| `send_keys` | — | `WM_KEYDOWN`/`WM_CHAR`/`WM_KEYUP` | `SendInput` |

**`set_text` open behavior:** for data-bound superclassed `EDIT` controls, whether
`WM_SETTEXT` propagates through the toolkit's data-binding layer is unverified. The
`WM_CHAR` sequence is the safer default because it traverses the toolkit's own
keyboard path, and is therefore the tier-3 default with `WM_SETTEXT` as an opt-in
fast path. Resolving this is a task in the implementation plan (§11).

### 4.4 Pre- and post-conditions

Every action verb accepts optional `expect_before` and `expect_after` predicates.

An action with a declared `expect_after` that cannot verify it **reports failure**. An
action with a declared `expect_before` that does not hold **does not execute**.

**Rationale:** during reconnaissance, a trial was correctly discarded because
"the state is X now" was equally consistent with "the action worked" and "neither the
setup nor the action did anything." For a tool whose purpose is testing, an action
that cannot distinguish success from no-op manufactures false passes. This belongs in
the framework, not in the discipline of whoever writes the test.

---

## 5. Capability probe and profile document

The probe automates the reconnaissance methodology. Its output is a **profile
document** — plain JSON, cached per `(executable_path, file_version)`.

```jsonc
{
  "profile_id": "…",
  "matched_profile": "L1",
  "executable": { "path": "…", "file_version": "…", "bitness": "x86", "wow64": true },
  "toolkit": { "inferred": "delphi-vcl", "evidence": ["…"], "confidence": "high" },
  "integrity_level": "medium",
  "dpi": { "mode": "virtualized", "logical": [1536,900], "physical": [1920,1125] },
  "class_census": { "<VendorButtonClass>": 39, "<VendorGridClass>": 10 },
  "uia": { "element_count": 92, "with_patterns": 0, "richness": 0.0, "verdict": "unusable" },
  "msaa": { "named_nodes": 260, "with_default_action": 0, "verdict": "identification-only" },
  "actuation_map": {
    "<class>": { "click": "wm_mouse_pair", "read": "wm_gettext", "verified": true }
  },
  "grid_strategy": "clipboard | export | api_oracle | ocr | unknown",
  "focus_behavior": { "self_foregrounds_on_click": true, "delay_ms": [300, 1300] },
  "denylist": ["(?i)\\b(submit|complete|accept|reject|delete|approve)\\b"],
  "environment_allowlist": ["…"]
}
```

`actuation_map` is the load-bearing field. The probe **learns** that a given control
class actuates via a mouse-down/up pair and not via a semantic click message, and
records it. Onboarding a new application becomes running the probe.

### 5.1 Probe safety

The probe is destructive-by-nature if done carelessly — it must actuate controls to
learn what works. Rules:

- Phase 1 is read-only: module fingerprint, class census, UIA/MSAA trees, style and
  dialog-code queries. No messages that could actuate.
- Phase 2 actuation learning requires an explicit **safe-control allowlist** supplied
  by the operator. The probe never selects its own actuation targets.
- Phase 2 is skipped entirely unless the session tier is `full`.
- Blind `WM_USER`-range probing is never performed; it can trigger arbitrary
  application-defined behavior.

### 5.2 Profile curation

Probe output is a starting point, not gospel. Profiles are checked into version
control and may be hand-edited — particularly `denylist`, `environment_allowlist`, and
`grid_strategy`, which encode operator judgment the probe cannot infer.

---

## 6. MCP tool surface

Eighteen tools, fixed regardless of how many applications are onboarded.

> **Amended during Iteration 2.** This read fifteen. Iteration 1's
> validation added three capabilities — `surfaces`, `modals` and
> `restore` — and they are exposed as tools rather than folded into
> existing ones. The constraint that matters is unchanged: onboarding a
> new application must not grow the surface. These are capabilities of
> the tool, not of any application. See `docs/DECISIONS.md` D1.

| Group | Tool | Purpose |
|---|---|---|
| Lifecycle | `list_targets` | Enumerate automatable processes and their profile status |
| | `attach` | Attach to a running target; returns session id and profile summary |
| | `launch` | Start a target under an isolation strategy |
| | `release` | Detach and tear down |
| Discovery | `describe` | Summarized element tree for a session |
| | `find` | Resolve a locator; return matches and properties |
| Interaction | `click` | Actuate, with optional pre/post conditions |
| | `type_text` | Enter text into a located control |
| | `set_value` | Semantic set — selection, toggle |
| | `send_keys` | Raw key sequence to the focused control |
| Reading | `read` | Text or value of matched elements |
| | `capture` | Screenshot of window or region |
| Meta | `probe` | Run or refresh a capability profile |
| | `wait_for` | Block until a locator matches a condition |
| | `await_human` | Pause the run, surface the target, and wait for the operator |
| Surface | `surfaces` | Classify each region by which mechanism can drive it |
| | `modals` | Report whether a modal dialog is holding the target |
| | `restore` | Un-minimize a target without taking the foreground |

### 6.1 `describe` must be engineered against context exhaustion

A Profile L1 target has ~1,100 windows. A raw dump is fine in a file and fatal in a
tool result. `describe` therefore:

- defaults to `visible: true`, which removes roughly 90% of nodes on this profile
- caps depth, with an explicit `depth` parameter
- collapses repeated siblings to counts rather than enumerating them
- returns **suggested locators** alongside structure, rather than raw handles
- hard-caps output size and reports truncation explicitly rather than silently

### 6.2 Implicit waits

Every interaction verb waits for its target to exist and be actionable before acting,
with a configurable timeout. `wait_for` exists for conditions that are not tied to a
single action. GUI automation without waits is flaky by construction.

---

## 7. Isolation strategies

A strategy interface with four implementations, shipped in cost order.

```
IsolationStrategy {
  prepare()       stand up the surface
  launch(cmd)     start a target inside it
  attach(pid)     adopt a running process; may raise Unsupported
  capture()       how screenshots are obtained
  teardown()
}
```

| Strategy | Guarantee | Status |
|---|---|---|
| `none` | None. Live desktop | Dev and debugging only |
| `minimized` | Observed: no focus theft while minimized | **Ships first** |
| `hidden_desktop` | Structural: no foreground exists to steal | Second |
| `vm` | Total, plus deterministic start state via checkpoints | Later |

### 7.1 `minimized`

Keeps the target minimized. Confirmed by measurement: actuation succeeds while
minimized and the window does not restore itself. Nearly free to implement.

Its guarantee is **observational, not structural** — a single long-running trial is
not proof, and a modal dialog may break it. Hence the watchdog.

### 7.2 The watchdog is a feature, not a mitigation

If the target restores or foregrounds itself, `minimized` re-minimizes it — and emits
an `unexpected_foreground` event with an attached capture.

**Rationale:** a background application that suddenly demands the foreground is almost
always raising a modal — an error box, a confirmation, a session timeout. For a
testing tool that is high-value information no assertion would have caught. Treating
focus theft purely as a nuisance to suppress discards a free modal detector.

### 7.3 `hidden_desktop`

Launches the target into a `CreateDesktop` desktop object. A window on a non-input
desktop has no foreground to steal, making the guarantee structural rather than
observational. Capture via `PrintWindow` with `PW_RENDERFULLCONTENT`.

Known limitation: interactive login requires a deliberate `SwitchDesktop` handoff,
during which the operator's whole screen changes. Credentials supplied at launch
avoid this where the target supports it.

---

## 8. Safety model

### 8.1 Session capability tiers

Set at `attach`/`launch`, immutable for the session's lifetime.

| Tier | Permits |
|---|---|
| `read_only` | `describe`, `find`, `read`, `capture`, `wait_for`, `surfaces`, `modals`, `restore`, probe phase 1 |
| `interactive` | Adds actions, **except** locators matching the profile denylist |
| `full` | Everything, including probe phase 2 |

### 8.2 Denylist

Caption patterns in the profile document. Expresses constraints such as "never
actuate anything that submits, completes, accepts, approves, or deletes" as an
enforced rule rather than a remembered one. Matched against resolved element captions
before any action executes.

### 8.3 Environment guard

A target's own command line commonly contains the server endpoint it is connected to.
The session manager refuses to attach or launch unless that endpoint matches the
profile's `environment_allowlist`.

This converts "never drive a client pointed at production" from operator discipline
into a tool-enforced check, using evidence the target supplies for free. When no
endpoint can be extracted, the guard fails closed and requires explicit override.

### 8.4 Credentials

The server never accepts credentials as tool arguments. Tool arguments are logged to
transcripts, server stdio, and MCP client history. Authentication is handled by one of:
launch-time arguments supplied from the operator's own environment, a pre-authenticated
profile or saved session, or an explicit human handoff via `await_human` where the
operator types into the target directly.

---

## 9. Error handling and evidence

Every action returns a structured outcome:

```
ActionResult {
  ok                      bool
  tier_used               int
  tiers_attempted         [int]
  precondition_verified   bool | null
  postcondition_verified  bool | null
  elapsed_ms              int
  capture                 image | null
  error                   { kind, message, locator } | null
}
```

Error kinds are distinguishable and actionable: `not_found`, `ambiguous`, `stale`,
`not_actionable`, `denied_by_policy`, `denied_by_environment`, `tier_exhausted`,
`postcondition_failed`, `timeout`.

`ok` is never true when a declared postcondition is unverified.

---

## 10. Test fixture

A driver for a no-UIA, owner-drawn, custom-window-class toolkit cannot be developed
against production business software: the iteration loop is slow, the application
state is precious, and the failure cases that most need handling cannot be induced on
demand.

**The fixture is a small purpose-built application that reproduces Profile L1.** Built
with **Lazarus / Free Pascal**, which produces genuinely LCL-based Win32 binaries at no
licensing cost and reproduces the profile faithfully.

Required fixture characteristics:

1. Vendor-registered custom window classes with no `BS_*` styles and
   `WM_GETDLGCODE` returning `0`
2. Custom buttons that respond only to `WM_LBUTTONDOWN`/`UP`, not `BM_CLICK`
3. An owner-drawn grid with zero child windows and no text via any accessible surface
4. Superclassed native `EDIT` fields, both plain and data-bound
5. A handler that grabs foreground on click, with configurable delay
6. Controls with identical captions at identical rectangles on stacked tab pages
7. A configurable modal that appears mid-run, to exercise the watchdog
8. DPI virtualization
9. No UIA provider

Items 5, 6, and 7 exist specifically to reproduce failure modes observed in the wild
that a naive fixture would not exhibit.

---

## 11. Build order

Delivery is **iterative**: each iteration must end in something runnable and
validatable against a real target, not only against internal tests.

### Iteration 1 — Read-only reconnaissance against a real target

1. Core model: `Locator`, `Element`, `ActionResult`; read paths only
2. Windows backend: enumeration and locator resolution, extending pywinauto
3. `read` via `WM_GETTEXT`
4. Capability probe, phase 1 — read-only profiling, profile document emission

**Validation gate.** Run against a real Profile L1 application. Passes when:
the emitted profile correctly identifies toolkit, DPI mode, and UIA/MSAA
verdicts; locators resolve unambiguously across identically-captioned controls
on stacked tab pages; and a ~1,100-window tree yields a profile document and a
`describe` result that fit a practical context budget.

**No fixture is required for this iteration, and none should be built for it.**
The fixture's value is in developing actuation and inducing failure modes on
demand. For the read path a real target is the *stronger* validation, because
it is the only thing that genuinely has ~1,100 windows, vendor-registered
classes, overlapping rectangles, and ~90% hidden controls. Read-only operation
against it carries no risk to application state.

### Iteration 2 — MCP server, read-only tier

5. MCP server: tool surface, session manager, `describe` summarization
6. Safety: session capability tiers, denylist, environment guard

**Validation gate.** An agent explores a real Profile L1 application end to end
through MCP at `read_only` tier, and the environment guard demonstrably refuses
a target pointed at a non-allowlisted endpoint.

> **Met.** Against a live 196-window L1 client: `list_targets` → `attach`
> refused with an uncurated profile, refused again with a production-only
> allowlist (naming the endpoint it refused), then attached with the correct
> one → `describe` → `surfaces` → `find` → `wait_for` (`settled`) →
> `capture` of an owner-drawn region → `modals` → `release`. Zero foreground
> changes and zero cursor movement throughout.
>
> `launch` is deferred to the iteration that ships an isolation strategy; the
> gate does not require it. See `docs/DECISIONS.md` D2.

### Iteration 3 — Fixture, then actuation

7. Fixture application per §10
8. Actuation tier developed against the fixture: input-shaped messages, tier
   fallback, pre/post conditions. Resolve the `set_text` data-binding question (§4.3)

**Validation gate.** All fixture failure modes (§10 items 5–7) are handled, and
actuation succeeds without moving the cursor.

### Iteration 4 — Supervised actuation against a real target

9. Capability probe, phase 2 — supervised actuation learning with an
   operator-supplied safe-control allowlist
10. Isolation: `minimized`, including the watchdog and `unexpected_foreground`

**Validation gate.** A view-only control on a real target actuates through the
full stack, cursor undisturbed, with the watchdog demonstrably re-minimizing
after the application self-foregrounds.

### Iteration 5 — Remaining gaps

11. Grid strategy — probe clipboard and export routes before building OCR
12. Isolation: `hidden_desktop`

## 12. Deferred

| Item | Reason |
|---|---|
| Linux/X11 backend (AT-SPI, Xephyr, MPX) | Separate spec. Core model guards against Win32 leakage (§3.2) |
| Web driver (Playwright) | Separate spec. Solved problem; no interference issue |
| HTTP/API client as test oracle | Separate spec. Belongs to orchestration, not the driver |
| Test orchestration and assertion DSL | Separate spec, built on this one |
| `vm` isolation strategy | After `hidden_desktop` proves insufficient |
| OCR grid reading | Only if clipboard and export routes both fail |

---

## 13. Open questions

| Question | Resolution path |
|---|---|
| Does `WM_SETTEXT` propagate through toolkit data binding, or is `WM_CHAR` required? | Fixture item 4, step 5 of build order |
| Do control classes beyond the proven one actuate identically? | Fixture items 1–2; then supervised probe phase 2 against a real target |
| Can owner-drawn grid contents be read via clipboard or export? | Step 10; probe both before committing to OCR |
| Does minimized-mode's freedom from focus theft hold over long runs? | Fixture item 5 with soak test; watchdog makes failure observable regardless |
| Is `attach` to an existing process supportable under `hidden_desktop`? | Likely not — desktop assignment is fixed at process creation. Confirm and document as `Unsupported` |
