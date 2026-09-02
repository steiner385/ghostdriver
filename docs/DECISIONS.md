# Decision log

Decisions and assumptions made while building, with the reasoning and the
evidence behind them. Written so that a decision can be *disagreed with*
later — which needs the reason, not just the outcome.

Newest last within each iteration.

---

## Iteration 2 — MCP server, read-only tier

> **D3, D5, D6 and D7 were superseded on 2026-09-02.** They described an
> environment allowlist curated in a profile document. It was built,
> reviewed, and replaced by session-scoped consent — see R1 at the end
> of this section. They are left in place because a decision log that
> quietly deletes what was overturned is worth less than one that shows
> the overturning.

### D1. The tool surface grows to 18, not 15

**Decision.** `surfaces`, `modals` and `restore` are exposed as their own
MCP tools rather than folded into existing ones.

**Context.** The design spec (§6) fixes the surface at "fifteen tools, fixed
regardless of how many applications are onboarded". Iteration 1 added three
capabilities that are not among them. I recommended folding them into
`describe` and `attach` to preserve the constraint; the operator chose
separate tools.

**Consequence.** §6 of the spec no longer describes what is built. The spec
is updated rather than left to drift. The fixed-surface constraint now reads
as eighteen, and the argument for keeping it fixed — that onboarding a new
application must not grow the surface — still holds: these three are
capabilities of the *tool*, not of any particular application.

### D2. `launch` is deferred entirely

**Decision.** Iteration 2 supports `attach` only.

**Reasoning.** `launch` requires an isolation strategy, and the spec ships
`minimized` in Iteration 4. A `launch` offering only the `none` strategy
would ship the thing the project exists to avoid — an automation run on a
live desktop with no guarantee against focus theft — and would need
replacing. The iteration's validation gate asks only for `attach`.

### D3. Curated policy lives in the profile document

**Decision.** `denylist` and `environment_allowlist` are read from the
profile document the probe emits, hand-edited by an operator.

**Reasoning.** One artifact per application, versionable alongside the
application it describes, and the probe already defines the schema.

**Known cost.** A re-probe overwrites the file and takes the curated policy
with it. Accepted for now; the mitigation, if it bites, is for `probe` to
merge rather than replace. Recorded so that the first person it bites knows
it was foreseen.

### D4. `restore` is permitted at `read_only`

**Decision.** The one tool in the read-only tier that changes what is on
screen.

**Reasoning.** The tier's promise is about the target's *application state* —
its data and its workflow — and restoring a window touches neither.
Excluding it would make `read_only` useless against a minimized target,
which is the state a target is most often found in and the one where nothing
can be read at all. It is also the only operation here measured not to take
the foreground.

**Assumption.** That operators read the tier as "cannot change the
application", not "cannot change anything". If that is wrong, the fix is a
fourth tier below `read_only`, not a change to this one.

### D5. Failing closed, three times over

**Decision.** In the environment guard: an empty allowlist refuses; an
endpoint matching nothing refuses; an endpoint that cannot be extracted at
all refuses.

**Reasoning.** The probe emits `environment_allowlist` empty for curation.
Reading empty as "no restrictions" would make every freshly probed
application automatable against production by default — precisely the
failure the guard exists to prevent.

`indeterminate` is kept distinct from `refused` because the remedies differ:
one needs the allowlist widened, the other needs a human to say what the
target is actually talking to.

**Assumption.** That a URL-shaped command-line argument is the endpoint that
matters. Verified against one real target, whose client carries
`/od http://<host>:<port>/<env>/gateway`. A target that identifies its
server some other way — a DSN, a bare `host:port`, a config file — extracts
nothing and is refused as `indeterminate`, which is the safe outcome but not
a helpful one. Revisit when a second target says otherwise.

### D6. UNC paths are not endpoints

**Decision.** Only URL-shaped (`scheme://`) arguments are extracted.

**Reasoning.** The real target's command line also carries
`\\fileshare\...\Root.p7b`, a certificate it reads. That is not the
environment it is driving. Treating file shares as endpoints would make
operators allowlist things that carry no risk, and an allowlist that is
tedious to curate gets written as `*`.

### D7. An override records the verdict it overrode

**Decision.** `override_environment` attaches, and the refusal verdict stays
on the session.

**Reasoning.** An override that erased the finding would leave nothing to
audit afterwards, and the point of a guard is that its decisions are
inspectable after the run, not only during it.

### D8. Iteration 2 work continues on local `main`, unpushed

**Decision.** No push while the operator is away.

**Reasoning.** The safety core had already landed on local `main` before
this stretch began, so branching now would split one iteration across a
branch and `main` for no benefit. Pushing is outward-facing and nothing
depends on it happening tonight. `main` is a local superset of `origin/main`
and can be reviewed, amended or reset in the morning.

### D9. The protocol layer holds no decisions

**Decision.** `tools.py` returns plain data and carries every rule;
`mcp_server.py` is a thin adapter over it.

**Reasoning.** Everything that can be wrong — a tier not enforced, a result
that blows a context budget, an error that says nothing actionable — is
wrong in the toolbox, where it can be tested without a protocol client. The
binding is tested separately, for wiring only: a tool registered but
unreachable, or a schema that rejects an argument the implementation
accepts, fails there and nowhere else.

**Test of whether this is holding.** If a rule about tiers, truncation or
error shape appears in `mcp_server.py`, it has leaked out of where it can be
tested.

### D10. Errors are results, not exceptions

**Decision.** Every tool returns `{"ok": false, "error": {...}}` rather than
raising through the protocol.

**Reasoning.** An agent has to read a refusal and change course. A
protocol-level exception gives it nothing to act on, and the error kinds
(`denied_by_environment`, `ambiguous`, `timeout`) are the whole point of
having distinguishable ones.

### D11. Results cap themselves and say so

**Decision.** `find` returns at most 50 elements; `describe` spends one node
budget across all windows; both report what they left out.

**Reasoning.** A target with ~1,100 windows can answer almost any query with
more than a caller can read. A cap that stays silent is worse than no cap:
it produces a confident, incomplete answer.

### D12. Tool returns are `dict[str, Any]`, not `dict`

**Decision.** A concrete annotation on every tool.

**Reasoning.** The SDK refuses a bare `dict` for structured output. Without
the annotation a client receives JSON text it has to parse rather than a
structured result. Verified: all twelve tools publish an output schema.

**Pinned consequence.** `mcp` is pinned `>=2.1,<3`. FastMCP was renamed to
MCPServer at the 2.0 boundary, so 1.x and 2.x are not interchangeable.

### D13. Fixture targets need an environment override

**Assumption made visible by testing.** Fixture targets are
`python -c <script>` and carry no URL, so the guard cannot determine what
they are connected to and refuses them as `indeterminate`.

**Consequence.** Every test that attaches to a fixture passes
`override_environment=True`. That is the honest path — the guard is right
that it cannot tell — and it exercises the override in the process.

### D14. Class names are case-sensitive, and the system rewrites their case

**Gotcha, found by a failing test.** The fixture registers its controls as
`"BUTTON"`; Windows canonicalises that and reports `Button`. Class matching
is `fnmatchcase`, so `class=BUTTON` matches nothing.

**Consequence.** A locator must use the class name the system *reports*, not
the one the application registered. `describe`'s suggested locators are
generated from reported names and are therefore always correct — which is
one more reason to prefer them over hand-written ones.

### D15. `*profile*.json` is ignored, not `profile*.json`

**Decision.** Widened after `dev-profile.json` — written during the
validation run — was not caught by the original pattern.

**Reasoning.** A profile document carries the target's executable path, full
command line, host names and window captions. Operators name these files
whatever suits them. `docs/example-profile.json` is negated back in, since
it carries only placeholders and is the documentation for curating one.

### R3. The process owning a window is not always the process owning the app

**Signposted, not solved.** Deliberately.

**What was measured.** A UWP application and its visible frame live in
different processes, and *nothing in the window tree connects them*:

    ApplicationFrameHost   ApplicationFrameWindow      rect (-7,-7,1543,919)
    SystemSettings.exe     Windows.UI.Core.CoreWindow  rect (-25600,-25600,...)

Both top-level. Neither is the other's parent or owner. The frame host owns
the window a person can see; the application's own window is parked
off-screen. So a caller who attaches to the pid owning the visible window --
which is the pid a target listing shows -- profiles a title bar, and nothing
said so.

**What was built.** Recognition of both ends, at two deliberately different
strengths. A result *measured from* a hosted frame carries a warning saying
so and pointing at what to attach to instead. A process that merely *owns* a
frame among its own windows gets only the weak claim, because a shell does
exactly that and telling its user "this describes a frame" would be false.
The first draft conflated them and mislabelled the shell; the distinction is
now pinned by tests.

**Why not solved.** There is nothing to follow. Pairing frame to application
would need a heuristic -- matching titles, say -- that can pair the wrong
application when two have similar ones.

**A lead, tested and inconclusive at first.** UIA element objects carry a process id,
and a UIA tree can in principle span processes, so walking the frame's UIA
tree and reading those ids would resolve the pairing without heuristics.
Walking it returned one element, belonging to the frame host. *But the
application was suspended at the time* -- UWP apps are suspended when not in
the foreground, which is why its window was parked off-screen. This does not
settle whether UIA crosses the boundary for a running application. Retest
with the application in the foreground before concluding anything.

**Resolved, 2026-09-02.** Retested with the application awake, and the lead
holds decisively. Walking the frame's UIA tree returned 211 elements, of
which **203 belonged to the application and 8 to the frame host's chrome** --
a 96% majority. UIA does span the process boundary; the earlier reading was
an artefact of measuring a sleeping application.

So the pairing is now resolved from evidence rather than signposted: count
the process ids of the elements beneath a window, and the process owning a
clear majority of them is the application inside it. No title matching, no
heuristic on names. `probe` and `attach` name the application and its pid.

Three properties worth keeping:

- The majority threshold is high (60%). Pointing a caller at an unrelated
  process is worse than admitting the answer is unclear.
- The walk is bounded -- a few hundred elements, a few levels deep -- because
  it runs during `attach`. The answer is a majority, not a census.
- An unidentified application is reported as *suspended*, not as failure.
  That is what it usually is, and the remedy is to bring the window forward
  rather than to look for a bug. Getting that wrong once already cost an
  hour of believing UIA could not cross the boundary.

**Still open:** this addresses hosts that compose another process's UI into
their own window, which is the shape UWP has. Whether process-per-tab
browsers and other broker architectures resolve the same way is untested --
the method is general, the evidence is not.

**The general shape.** UWP is the instance visible on one desktop.
Process-per-tab browsers and other broker architectures have the same
shape, and a signpost keyed to one window class does not address them. The
honest framing is that a target listing presents "process owns windows" as
though that mapping were the whole truth, and it is not.

---

## Iteration 3 — fixture, then actuation

### D16. The fixture is built on ctypes, not Lazarus

**Deviation from spec section 10, taken deliberately.**

The spec calls for Lazarus / Free Pascal, on the grounds that it "produces
genuinely LCL-based Win32 binaries at no licensing cost and reproduces the
profile faithfully". No Pascal toolchain exists on the development machine,
and none of gcc, clang, MSVC or Rust either -- only .NET, which is the wrong
tool because a WinForms application ships a UIA provider and section 10
item 9 requires none.

So the fixture is built directly on the Win32 API through ctypes, the same
way the four smaller test fixtures already in this repository are.

**What that costs.** Not the listed characteristics -- all nine are
reproduced and each is asserted by a test rather than assumed. What is lost
is *emergent* behaviour: the quirks a real toolkit exhibits that nobody
thought to write down. Those are exactly the kind of thing this project
keeps discovering on live targets, so the loss is real even though nothing
on the list is missing.

**Why it is acceptable.** The driver develops against the fixture's
behaviour, not its language. An LCL build can replace this later and the
actuation work and its tests point at that instead, unchanged.

### D17. "One window per control" is the profile, not decoration

**Found by measurement, and it nearly shipped wrong.**

The first fixture had sixteen windows, several of them native `EDIT` and
`STATIC` controls. The HWND-to-UIA bridge describes those with patterns, so
the tree came out at 7 pattern-bearing elements from 16 -- a ratio of 0.44,
which classifies as **M1**. The fixture whose entire purpose is to reproduce
Profile L1 was reproducing the profile the project is not about.

A measured L1 target carried 105 windows in its main tree and exposed 29 UIA
elements between them, because almost every control is a vendor class the
bridge can only describe as a bare pane.

The fixture now carries a detail panel of caption/value pairs, each its own
window in a vendor class, and classifies L1 at 57 windows. That is not
padding to hit a threshold: rows of captions and values, one window each, is
what a real business form *is*, and it is the same structure that produces
the ~1,100-window trees this tool exists to summarize.

### D18. Disruptive characteristics are opt-in at two levels

Section 10 items 5 and 7 -- an application that grabs the foreground after
acting, and a modal that appears mid-run -- exist precisely because a naive
fixture would not exhibit them. They are also the two that make a machine
unpleasant to work at.

They are off by default in the application, enabled by command-line flags,
and the test that induces focus theft is additionally skipped unless
`GHOSTDRIVER_ALLOW_FOCUS_TESTS=1`. A suite has to be runnable on a machine
somebody is using -- a lesson this project learned by disrupting its
operator during iteration 1 -- and a failure induced on demand is more
useful than one that happens ambiently anyway.

Both were verified once, deliberately, with the operator informed.

---

### D19. `WM_SETTEXT` is sent, not posted

**Decision.** Every actuation primitive posts, except `WM_SETTEXT`, which is
sent under a hard timeout.

**Reasoning.** Not a preference — a correctness requirement discovered by the
integration gate. `WM_SETTEXT` carries a pointer in its lParam, and the
system marshals a pointer across a process boundary only for a *sent*
message. Posted, the target receives an address in the sender's address
space: `PostMessage` returns success and the control does not change.

Worth recording because of how it hid. In-process it works, so the fixture's
own tests passed. It failed the first time a driver in one process aimed it
at a control in another, which is the only configuration that matters. A
unit test could not have found this.

`SMTO_ABORTIFHUNG` with a 500ms budget keeps the exception from reintroducing
the blocking call the rest of the module exists to avoid.

### D20. Actuation checks the ancestor chain, not the control

**Decision.** `blocking_ancestor` walks from the control to the root, and
`verbs.unblocked` is the precondition built on it.

**Reasoning.** Measured: with a modal up, the top-level reports disabled and
its buttons report **enabled**. `IsWindowEnabled` answers for one window and
no further — a modal disables the top-level, and the children are only
unreachable *through* it. A driver that asks the control alone sees nothing
wrong.

That matters more than it would for real input, because posted messages do
not respect modality at all. The system drops a person's click before the
control sees it; a posted message is delivered straight to the window
procedure. Whether the control then acts is up to the control — well-behaved
classes check, and the fixture checks for that reason — so the observable
outcome varies by target, and a driver relying on it is relying on an
accident.

The check is made at act time rather than read from a tree, because a modal
that appears between reconnaissance and actuation is the case worth catching.

### D21. Tier 1 has the same silent-split hazard as the fast path

**Finding, not a decision.** The HWND-to-UIA bridge synthesises a Value
pattern for anything derived from a native EDIT. `SetValue` on it writes the
control's text without the toolkit's keyboard path running — so a
data-bound field displays one value while the application holds another,
exactly as `WM_SETTEXT` does. One rung higher than the fast path, and not
opt-in.

Tier 1 stays first anyway: on a target that publishes a *real* Value pattern
that is the surface to use, and the ladder recovers on its own when a
postcondition names the committed value rather than the display. What this
changes is the documentation and the emphasis — an unverified `set_text` is
not a safe `set_text`, and the result says so by leaving
`postcondition_verified` unset rather than claiming success.

This is the concrete answer to the `set_text` question the spec left open.
The default ladder is UIA, then typing; `WM_SETTEXT` is offered only to a
caller who asks for `fast_path`.

### D22. "The cursor did not move" is skipped, not failed, on a busy desk

**Decision.** The cursor assertion samples twice before asserting and skips
if the cursor is already moving.

**Reasoning.** The claim can only be made about a cursor nobody else is
moving, and this suite runs on a desktop with a person on it. Without the
guard, a hand on the mouse reports a correctly-behaving tool as broken —
which is worse than not asserting, because it trains whoever runs it to
ignore the result. Two samples separate the cases: the tool either moves the
cursor at the moment it acts or never, while a hand keeps moving. The
foreground assertion needs no such guard and is made unconditionally.

### D23. The tree carries `actionable` alongside `enabled`

**Decision.** `WindowNode` gains `actionable` — this window and every
ancestor enabled — computed while the backend walks the tree. `enabled`
keeps its old meaning: the window's own flag, and nothing more.

**Reasoning.** D20 fixed actuation; this is the same finding on the read
side, which is where an agent meets it first. Reconnaissance is what a
caller acts on, and `describe` showing every control in a modally held
application as enabled gives the agent no reason not to try.

Both are reported rather than one replacing the other, because "enabled, but
something above it is holding the application" is a more useful thing to see
than either half alone. `_element` emits `actionable` only when it is False:
a key on every element in the ordinary case would cost the result budget to
say nothing.

`wait_for(condition="enabled")` now means actionable. Anyone waiting to act
on a control means "until I can act on it", and the old reading returned
immediately on a blocked application — a wait that hands the caller a green
light into the block is worse than no wait at all.

Free in system calls: the ancestry is already in hand during the walk.

### D24. Typing is left subject to the control's own limits

**Finding, and a decision not to fix it.** A single-line field without
`ES_AUTOHSCROLL` stops accepting keystrokes at the visible width. Measured:
about twenty characters, while `WM_SETTEXT` writes all eighty, because the
programmatic path is not subject to the control's input handling.

So the two paths are wrong in opposite directions. The fast path sets a value
the application never accepted; typing sets only as much as the control would
take, silently, as a prefix.

Typing stays the default anyway, and stays unmodified. It is faithful
*because* it is subject to whatever the control does to input — the same
property that makes a bound value commit is the one that makes a length
limit bite. A driver that widened the field or raised its limit to get the
whole string in would be changing the target in order to make its own action
succeed, which is the opposite of what this tool is for.

**The consequence that matters.** The control answers `EM_GETLIMITTEXT` with
30000 and accepts about twenty. The number that decides the outcome depends
on the rendered width of the glyphs actually typed, so there is nothing to
ask beforehand. Combined with D21, an unverified `set_text` can be wrong in
two unrelated ways, neither detectable in advance. Reading the value back is
the only way to know.

That is a requirement for the actuation tool surface, which does not exist
yet: `set_text` should verify by default rather than on request. Truncation
is detectable generically — compare the resulting display against what was
asked. Whether the value *committed* is not, and still needs an expectation
only the caller can state.

## Open, for whoever picks this up

- **The denylist is enforced but unexercised.** It matches captions and
  refuses, and is unit-tested, but nothing calls it end to end because no
  action verb exists yet. Iteration 3 is where it first does something.
- **A re-probe overwrites curated policy** (D3). Foreseen, not yet
  mitigated. The fix, if it bites, is for `probe` to merge rather than
  replace.
- **The endpoint-extraction assumption is n=1** (D5). One real target, whose
  client happens to put its endpoint in the command line as a URL. A target
  that identifies its server another way extracts nothing and is refused as
  `indeterminate` — safe, but unhelpful.
- **`capture` has no OCR behind it.** It returns pixels. Reading an
  owner-drawn grid from those pixels is Iteration 5 per the spec, and the
  spec is right that clipboard and export routes should be probed before
  anything is built on OCR.
- **The region model still mixes three axes.** See the Iteration 1 scoping
  note in the published validation report. Deliberately unresolved until
  there is a second target to decide against.

---

## Revision, 2026-09-02

### R1. Target selection is interactive and session-scoped, not configured

**Supersedes D3, D5, D6, D7.**

**What was wrong with the old design.** It decided in advance a question that
arises in the moment. A person doing a task knows which application they want
touched and which they need left alone *then* — not when the server was
installed. Curating an allowlist per application, in a JSON file, ahead of
time, answered a question nobody had asked yet, and the machinery it needed
(three verdicts, an override that records itself) was complexity spent on the
wrong model. It was also unlike how comparable MCP servers handle this: the
convention is to bind the boundary at launch, or to let the client prompt.

**What replaced it.**

- `list_targets` shows each candidate *with the endpoint read from its own
  command line*, so a person can see what they are approving.
- `attach` on an undecided target elicits directly from the operator through
  their own client. Consent obtained that way cannot be fabricated by the
  agent, which is the property the old design never had.
- Where the client cannot be asked, `attach` returns `needs_consent` and
  names `grant_targets`. The agent asks in chat; the client's own
  tool-approval prompt is what the operator actually sees and approves.
- Grants live in the server process. For stdio that process *is* the chat
  session, so they expire exactly when they should, with nothing to persist
  or clean up.
- Decisions are revisable, and a restriction stops a session already open on
  that target. Otherwise "leave that one alone" would apply only to work not
  yet started, which is not what anyone means by it.

**What survived.** Endpoint extraction, demoted from gatekeeper to informant
(D6's reasoning about UNC paths still holds — a certificate share is noise in
the question being asked). The caption denylist, which answers a different
question and is unaffected. Capability tiers, likewise.

**Assumption.** That the operator is present and reachable during the
session. This model has no answer for unattended runs — there is nobody to
ask. When that case arrives, the answer is probably a launch-time flag
naming pre-approved targets, which is the convention this design deliberately
did not adopt for the interactive case.

### R2. Tools carry read-only annotations

**Decision.** Every read tool is marked `readOnlyHint`; `attach` and
`restore` are not.

**Reasoning.** A gap found while answering "what do comparable servers do".
MCP tool annotations let a client decide for itself how much ceremony a call
deserves rather than treating every tool as potentially destructive.
`restore` is excluded deliberately: it changes no application state but does
change what a person can see on their screen, and a client is entitled to
treat that as worth a prompt.
