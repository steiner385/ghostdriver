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

### D25. `WM_SETTEXT` is deleted, not kept as a fast path

**Decision.** The programmatic write is gone. `set_text` types, and at robot
cadence offers a UIA Value pattern above it.

**Reasoning.** D19 made it work; measuring it made the case for keeping it
collapse. It bought about **twelve milliseconds** on a twenty-character
field — 0.3ms against 12ms — while every action pays a 250ms settle before
anything is verified. A field would have to run past four hundred characters
before typing cost as much as the settle already does.

Against that: it splits display from committed value (D21), it is not
subject to the control's input handling so it writes values the application
would have refused (D24), and it produces **no input events at all**, which
is the most detectable thing this module could do on a target that watches
for automation (D26). It was also the one call in the module that had to be
sent rather than posted, so deleting it makes "posted, not sent"
unconditional.

The remaining case was a long unbound memo field. If one turns up, it comes
back as its own verb with a name that says what it does, rather than as a
boolean called `fast_path` on the verb agents reach for by default.

### D26. Typed input is paced, and the cadence changes the ladder

**Decision.** `cadence` on the typing primitives. `robot` sends at queue
speed and is the default; `fast_human` puts uneven gaps of roughly 80ms
between characters, longer after a word ends.

**Reasoning.** Posted characters land about 0.6ms apart, which is a rate no
person types at, and some applications look. The messages are identical
either way — only the timing changes — so this is not a second code path,
which is asserted rather than assumed.

Robot stays the default because most targets do not look and human pacing
makes a long field take minutes. That cost has to be chosen, so it is
per-call and recorded per target (D27) rather than global.

**A non-robot cadence drops tier 1 from `set_text`.** A caller asking for
human pacing is saying this target watches its input; a pattern call
produces no input events at all. Offering it first would satisfy the action
and defeat the reason for asking, silently — the one failure mode a cadence
must not have.

**What this cannot reach.** Three things are observable to a detector:
timing, event shape, and physical key state. Cadence fixes the first. The
second — real keystrokes arrive as `KEYDOWN`/`CHAR`/`KEYUP`, and we post a
bare `CHAR` — is fixable but not free: posting the full triple double-types,
because the target's own `TranslateMessage` synthesises the `CHAR` from the
`KEYDOWN`, and letting it do so makes uppercase and symbols depend on a
shift state we cannot set from outside. The third is not reachable at tier 3
at all: `GetAsyncKeyState` only moves for real or synthetic input. A target
checking key state can only be satisfied at tier 4, which needs the
foreground — so for that target, unattended and undetected cannot both be
had, and the operator has to choose.

### D27. Input sensitivity is recorded per target, and declared beats learned

**Decision.** An `input_sensitivity` section in the profile document, read
at attach and reported in the session summary.

**Reasoning.** The fact cannot live in a chat session. Sessions forget, and
clients do not share notes, so every new session would rediscover it the
only way it can be discovered — by tripping the target at machine speed,
which is what the note exists to prevent.

Two sources, and the asymmetry is the point. **Declared** is the only kind
that helps on a first encounter, and one failure mode is invisible: a target
can accept the input and flag the account server-side, where nothing
observable will ever reveal it. Only a person can say so in advance.
**Learned** means a session ran the differential — same action, robot
failed, human succeeded — which is the single observation that separates
input sensitivity from an ordinary validation failure.

Keyed by target *and surface*, because a native shell hosting web content is
two detectors in one window and they will not agree. A web region counting
DOM events and a native toolkit that does not look are different answers to
the same question about the same process.

**This does not weaken R1.** Consent cannot be persisted because a person
has to be *asked*; a cadence note carries no authority and gets nobody
access to anything. It is a fact about the target, like its toolkit.

A typo in a hand-edited note raises rather than defaulting to robot, for the
same reason the rest of the file does: silently downgrading a caller who
asked for pacing means they find out from the target.

### D28. Actions report disturbances, and disturbances are never a verdict

**Decision.** `ActionResult.disturbances` lists what moved around an action
— a window that appeared, the application becoming held, the target taking
the foreground, the target going away. It never affects `ok`.

**Reasoning.** A postcondition answers one question the caller thought to
ask. It will never mention the dialog that appeared next to it, and an
action can succeed on its own terms while the application ends up somewhere
the caller did not expect — measured against the fixture, and it is exactly
how a driver walks into a held application on the following call.

Not a verdict, because every observation has a benign twin. A new dialog is
the application rejecting what was typed, or the confirmation the action was
meant to raise. A vanished target is a robot-speed logout, or an idle
timeout. The tool cannot tell, and a result that guessed would be wrong in
whichever direction it guessed. The caller has the context; this makes sure
the caller also has the observation.

**The differential is the caller's to run, not the server's.** Retrying at
`fast_human` is the experiment that separates the twins, and the error text
says so. It is not automatic: a second attempt on a target that just flagged
the first is a judgement call, and for a non-idempotent action a silent
retry is a double click.

**Instrumentation cannot break the action.** Both snapshots are guarded. An
observer that throws reports no disturbances rather than failing an action
that really happened — caught by a test written for exactly that, which
failed the first time because only the second snapshot was wrapped.

### D29. `set_value` always checks the display, and says what it did not check

**Decision.** Three things can be true after setting a field, and the tool
can see only two of them: the input was delivered, the field displays the
value, the application accepted it. `set_value` always verifies the second
and reports `verified: "display"`; it verifies the third only when the
caller names where the committed value appears, and then reports
`verified: "committed"`.

**Reasoning.** Both failures are silent and unrelated (D21, D24), and
neither can be predicted — the control's declared limit says thirty thousand
while it accepts twenty, and no property distinguishes a real Value pattern
from a bridge-synthesised one. Reading the display back is free and catches
truncation without the caller asking for anything. Reading the *committed*
value is impossible without knowing where it surfaces, which only the caller
knows.

The result never says a bare `ok`. A success that verified only the display
carries an `unverified` line saying so in words, because "it worked" and "it
looks like it worked" are the distinction this whole design exists to keep.

**A reformatting field fails the first call, deliberately.** A date mask
turning `01012026` into `01/01/2026` fails the display check, and the caller
re-sends with `expect_text="01/01/2026"`. One extra round trip, and the
reformatting becomes something asserted rather than skimmed past. The
alternative — a non-failing warning — is the pattern the actuator was built
to avoid: it depends on the reader's discipline, and the reader is the party
who most wants the action to pass.

### D30. Tier 1 runs only when something would catch it failing

**Decision.** `set_text` offers the UIA rung only when the caller supplied a
commit expectation (or explicitly allows it). `set_value` passes
`allow_pattern=commit is not None`.

**Reasoning.** Sharpens D21. Nothing distinguishes a real Value pattern from
one the HWND bridge synthesised at the point of calling it: both answer, and
only one commits. With a commit postcondition that is fine — the useless one
delivers, fails verification and falls through to typing. Without one it is
a coin flip whose losing side is silent, so it is not offered.

Measured both ways against the fixture: the plain field resolves at tier 1
and stops there; the bound field with a commit check reports
`tiers_attempted [1, 3]` and `tier_used 3`.

### D31. `within=(...)` is expressible in the locator string

**Decision.** The locator parser accepts `within=(...)`, nested, with quotes
respected while scanning for the closing paren.

**Reasoning.** Found by the ambiguity error message, which told callers to
"add within=... to scope it" — advice the parser could not accept. The
field existed on the dataclass and resolution honoured it, so `within` was
reachable from Python and not from a tool call, which is the only way an
agent reaches any of this.

It matters more here than anywhere else: scoping by ancestor is *the* way
two identically-captioned controls are told apart on this class of target —
the same caption at the same offset on two pages — and actuation refuses
ambiguity outright. Without it the refusal had no answer.

`describe()` now emits the same syntax `parse` accepts, so a locator quoted
in an error message can be copied back into a call.

### D32. A malformed expectation is an error, not an unmet one

**Decision.** `expect`'s locator is parsed before anything is sent. A bad
one returns an error naming it; it is not evaluated as a condition that
happens not to hold.

**Reasoning.** Found by a typo in a test — an unquoted regex containing a
space, which `shlex` split into a nonsense key. The condition swallowed the
parse failure and returned False, so the action ran, failed its
postcondition, and reported that the application had not done what was
expected.

Those two outcomes look identical from outside and mean opposite things. One
says the target misbehaved; the other says the caller mistyped. Reported as
the first, an agent goes looking at the application — and since a malformed
locator can never hold, every action would fail and a working target would
look like one that never responds.

### D33. Actuation refuses ambiguity rather than picking

**Decision.** An actuation locator must resolve to exactly one element. More
than one is an error carrying the candidates.

**Reasoning.** Reads cap ambiguity and carry on, which is right for them: a
read of eight matching fields returns eight values and the caller sees what
happened. A click on eight matching buttons picks one, and the caller finds
out from the consequences. The cost of being wrong is not symmetric, so the
rule is not either.

The candidates are returned because the answer to "which one did you mean"
is in them, and the message names both ways out — `within=` to scope,
`index=` to choose.

### D34. A learned note rests on what the server saw, not on what it is told

**Decision.** The server keeps a small in-memory ledger of its own action
outcomes, and `record_input_sensitivity` reads the differential out of that.
A caller cannot assert one.

**Reasoning.** `Source.LEARNED` is supposed to mean the differential held —
the same action, on the same element, failing at robot cadence and
succeeding at a human one. Something has to check that, and taking the
caller's word is the one option that cannot: the agent asking for a note
recorded is the party that most wants it recorded, and its account of its
own history is indistinguishable from a guess. Later sessions will trust
this file, so the evidence behind it has to be first-hand.

Both halves must match on element *and* tool. "Something failed and
something else worked" is two unrelated facts, not evidence about input
speed, and a failed `click` must not vouch for a `set_value`.

Order does not matter. An agent that hits the wall, retries paced, and then
records is the ordinary case; one told a target is sensitive, working paced,
that later confirms by trying robot is the same experiment run backwards and
produces the same evidence.

A refusal names which half is missing. The caller believes it saw something,
and a bare no leaves it guessing whether to retry, re-measure, or give up.

The ledger is bounded and forgotten on release: it is working evidence for
one session, not history.

### D35. A measurement never overrules a person, at any grain

**Decision.** A learned note is refused if *any* declared note applies to
its surface — not merely if one exists on the same surface.

**Reasoning.** The same-surface check was written first and had a hole the
test found. A learned note for `native` does not *replace* a declared note
for `*`, so a same-surface check let it through — but it *beats* it at act
time, because a specific note wins over a blanket one. A measurement could
therefore override an operator by writing at a finer grain, which is the
exact thing the rule exists to prevent, reached by the side door.

The rule stops short of blanket refusal: a declaration about `web` says
nothing about `native`, and does not block a measurement there.

The asymmetry is deliberate and worth restating. A person who declared
`robot` has not been contradicted by a session that measured otherwise —
they may know the target flags without ever visibly refusing, which is a
failure mode no measurement can reach. A declaration can still be replaced
by another declaration; the rule protects a person from a measurement, not
from another person.

### D36. The note is written where the operator pointed, or handed back

**Decision.** The note goes into the profile document supplied at attach.
With no profile document, the note is returned for a person to place.

**Reasoning.** The operator naming a profile path is the act that opts in to
it being written; writing a file nobody pointed at would be a side effect
nobody asked for. But the measurement is still worth something, so it comes
back rather than being discarded.

The whole document is read, modified and written back, because these files
are hand-curated: a writer that rebuilt the document from what this process
happens to model would silently drop anything an operator had added. Written
to a temporary file and moved into place — an interrupted write that
truncated a profile would leave every later session refusing to attach.

### D37. A password field is protected, not unresponsive

**Finding, and the fix it forced.** Windows refuses a cross-process
`WM_GETTEXT` on a password field. Measured: the read comes back with no
answer at all — which is exactly what a control that has stopped pumping
messages looks like.

That the read is blocked is good and was worth confirming. Reporting it as
`responsive: false` was not: one answer means the target may be hung, the
other means a field is working precisely as designed, and a caller told the
first goes off diagnosing a hang that is not happening.

Detected with `EM_GETPASSWORDCHAR` rather than the `ES_PASSWORD` style bit.
The bit is 0x0020, which means something else entirely on a non-EDIT class,
and a superclassed field keeps its vendor class name — so nothing in the
name says whether to read the bit that way. The message is implemented only
by EDIT-derived windows and answers 0 everywhere else; verified across every
class the fixture has.

Asked only when a read came back empty-handed, so the ordinary path pays
nothing for it.

### D38. Nothing types into a field that hides its contents

**Decision.** `set_value`, `type_text`, and `send_keys` with any single
character refuse a protected field. Named keys are allowed.

**Reasoning.** The value would have to pass through this process to be
typed, and no amount of care makes that worth the convenience. Putting the
boundary in code rather than in a caller's judgement is the whole point: an
agent under time pressure with a password in hand should find this
impossible rather than inadvisable.

Named keys are a different question. `tab` out of a field a person has just
filled in, or `enter` to submit it, carries nothing — and refusing them
would make the handover useless, because the agent could not continue the
flow it had just handed over.

The refusal names `await_human`, so the caller is told what to do instead
rather than only what it cannot do.

### D39. `await_human` waits on the target, not on a reply

**Decision.** A tool that hands a step to a person, and resumes when a
stated condition holds against the application.

**Reasoning.** Some steps are not the driver's: a credential, an
irreversible action, a step the operator asked to keep, a decision needing
judgement. An agent could simply ask in chat — what this adds is *evidence*.
"Done" is a claim; `until` is an observation. Where the client supports
elicitation the person is also asked directly, and then there are two
independent signals: the person confirmed, and the application agrees.

`absent` is supported because a thing going away is as common a signal as a
thing appearing — a sign-in dialog closing is how you know someone signed
in.

Without `until` it returns immediately and says it verified nothing, rather
than implying a handover succeeded because it was requested.

Bounded, and a timeout is reported as a timeout. A person may be away from
the machine, and a tool that waited indefinitely would take the session with
them. The timeout message says not to attempt the step instead — the reason
it was handed over has not gone away just because nobody did it yet.

**It never carries the value.** There is no parameter for a credential in
either direction, and the elicitation schema is a confirmation with no field
to type into. The secret goes from the person into the application without
passing through here.

**At the read-only tier**, deliberately. Asking is not acting: it changes
nothing itself, the person decides whether to do anything, and the ask is
relayed to them exactly as written. A read-only session needs it as much as
any other — "please sign in so I can see the screen" is the commonest case
there is.

### D40. The fixture stops beeping without stopping truncating

**Decision.** The superclassed edits reject a character past `FIELD_CAPACITY`
themselves, before the EDIT sees it, and swallow Return and Escape.

**Reasoning.** Reported by the operator during a test run: dozens of system
beeps stuttering over each other. A real single-line EDIT beeps on every
character it refuses, and several tests type eighty into a field that stops
at twenty — around sixty beeps each, four times a run, at whoever is at the
machine.

The truncation is real behaviour worth keeping; the beep is not observable
to a driver and has no bearing on anything being tested. Rejecting the
character a layer earlier preserves the first exactly and removes the
second.

Enforced privately rather than through `EM_LIMITTEXT`, so the control still
answers `EM_GETLIMITTEXT` with thirty thousand — which is the point of D24,
and would have been erased by setting a real limit.

Second time a test run has disturbed the machine it runs on (the first was
focus-stealing). Worth stating as a standing property rather than a fix:
this suite runs on a desktop somebody is using, and a test that is
unpleasant to sit next to will not be run.

### D41. Targets are named by profile, including in sample data

**Convention, written down because it was already being broken.** Targets
are referred to by their technology profile — toolkit, bitness, control
classes, Profile L1/M1/W1 — never by product or vendor name. That holds for
code, tests, commit messages and any report.

Sample data is not an exception, and that is where it slipped: a modality
test used a real product name as a window caption. Nothing else in the tree
did, which is the point — a convention followed everywhere except one file
is one edit away from being followed nowhere.

The replacement is a made-up application name rather than a generic one like
"Main". The test asserts that the *held application* is named alongside the
dialog holding it, so the caption has to be distinctive enough to prove it
came from the right window.

The occurrence remains in history, which no going-forward change can alter.
Rewriting published commits was judged not worth it for a private repository
against a partial remedy; if that judgement changes, the two commits are
findable by searching the history for the name.

### D49. The `minimized` isolation strategy and its watchdog

**Decision.** A session may run under `minimized`: the target is kept
minimized, and if a window of it comes on screen the watchdog captures that
window and puts the target back, emitting an event. Policy lives in
`ghostdriver.isolation` (pure, injected clock); sampling, capture and the
no-activate minimize live in the Windows backend.

**The watchdog is the feature** (spec 7.2). A background application that
suddenly shows a window is almost always raising a modal -- an error, a
confirmation, a timeout -- and that is information no assertion would have
caught. The screenshot is the product; re-minimizing is housekeeping.

Four things only a real window taught, each a wrong model corrected:

- **Quiet is "nothing on screen", not "minimized and not foreground".**
  Minimizing without activating anything else leaves the minimized window
  still owning the foreground handle, so a put-away target reads as
  foreground. The first model never saw quiet and never established a
  baseline.
- **On screen is asked of every top-level window, not the main one.** The
  escape that matters is a modal raised as a *new* window while the main
  window stays minimized; watching only the main window's flag would miss
  exactly the case the strategy exists for.
- **The capture must photograph the on-screen window, not the main handle.**
  The main window is minimized when the modal appears; capturing it would
  fail. The backend finds the visible window and shoots that.
- **A grab via `SetForegroundWindow` was the wrong fixture scenario.**
  Measured: a background process calling it on its own minimized window does
  not un-minimize it -- Windows restricts the call -- so nothing comes on
  screen. The realistic escape is a raised window, which the fixture's
  `--modal-after` produces.

**An escape reports how long since the target was last seen quiet, and that
is not the action-to-grab latency.** Under continuous polling it is about
one poll interval. The grab *delay* an operator wants for `focus_behavior`
is measured sparsely from a known action, which is phase 2's job. The field
was documented to over-claim that; corrected.

**Losing gracefully.** A modal the watchdog cannot dismiss keeps the target
on screen. Rather than re-minimizing every poll forever, the watchdog caps
its actions in a window and then only observes, reporting that it stood
down. Both "can't establish quiet" and "keeps fighting back" take that path.

**Gate.** The whole of iteration 4 is met: a view-only control on a real
Profile L1 target actuated through the full stack (D48), and the watchdog
catches and re-minimizes a real self-raised window, cursor undisturbed. The
grab-delay half of `focus_behavior` is phase 2's, measured there.

### D50. Grid strategy: routes to exact text are probed, cheapest-first

**Decision.** `probe_grid` finds how exact text comes out of an owner-drawn
region and records the winning route as `grid_strategy`. Two routes are
tried in order of *interference*, not likelihood: a focus-revealed
accessibility surface, then the control's own copy via `WM_COPY` and the
clipboard. Nothing is built on OCR; when neither works the answer is
`unknown`, which is the verdict the spec defers OCR until.

**Why cheapest-first.** The clipboard is one shared resource for the whole
interactive session -- not per process, not per tool. A copy overwrites
whatever a person had copied, is seen by clipboard history and clipboard
managers, and cannot be restored atomically: anything that copies in the gap
between snapshot and restore loses to the restore. Only text can be put
back; an image or file list on the clipboard beforehand is gone. All of that
is stated in the result's `caveat` rather than hidden behind "restored". So
a region readable without a side effect must never be read with one, and
the free route is ruled out before the clipboard is touched.

**Measured.** On the fixture's painted grid -- the shape a real Profile L1
data grid has, one million pixels with no windows beneath it -- focus
reveals nothing (0 accessible elements before and after), and `WM_COPY`
yields three tab-and-newline rows. The clipboard held a sentinel before and
held it again afterwards. A grid built to ignore `WM_COPY` comes back
`unknown` with "the control did not change the clipboard", not a guess.

**What the profile keeps is shape, not cells.** `grid_evidence` records the
route, whether each attempt worked, and a line count. Cell text is the
target's business and never lands in a versioned document; a caller that
wants the rows asks the route for them at read time.

**Rails, same as phase 2.** Full tier, because the clipboard route sends a
message and reads a shared resource. Exactly one match, operator-named. A
denylisted caption or a held application refuses. And a region that already
answers `read` is refused -- it is not a painted region, and spending a side
effect on something a free call reads is the wrong trade.
`allow_clipboard=false` runs the free route only and reports `unknown`
rather than reaching for the route it was told not to use.

**`WM_COPY` is posted, not sent.** It carries no pointer, so cross-process
posting is fine; contrast D19.

### D51. hidden_desktop is a thread you hand work to, and it is launch-only

**Decision.** The `hidden_desktop` strategy creates a named desktop under
WinSta0, launches the target onto it, and runs every target-touching call on
one thread bound to that desktop with `SetThreadDesktop`. Operations are
marshalled to that thread through `run`.

**Why a thread, not a handle.** Measured against the fixture: a desktop is
bound per-thread, not per-process. A call to enumerate or read the target
from any thread not bound to its desktop returns *nothing* -- the windows
are simply not visible. So the strategy cannot be a handle callers use from
wherever; it has to own the one thread allowed to see the target, and hand
it work. `test_reading_from_the_wrong_thread_sees_nothing` pins the contrast:
the identical call returns the whole tree through `run` and an empty list
off the bound thread.

**The guarantee is structural, and that is the whole point.** `minimized` is
observational -- it watches for an escape and puts the target back, and the
watchdog exists because one quiet trial proves nothing. On a hidden desktop
there is nowhere to escape to: a window on a non-input desktop has no
foreground to steal. Measured: a fixture launched there was invisible to
`EnumWindows` on the Default desktop and its foreground never moved, while
the bound thread saw all ten windows, read them, landed a click, and
captured a valid PNG. Unlike the minimized tests, these need no opt-in flag
-- they cannot disturb the operator, which is the guarantee itself.

**Launch-only, by necessity.** A window's desktop is fixed when the window
is created, so a target already running on the input desktop cannot be moved
to a hidden one. `attach` on a running pid raises `Unsupported` and says so.
This is the first capability in the tool that launches a process; a session
that only attaches cannot use it, and that is correct rather than a gap.

**Its known limit, unsolved and stated.** Interactive login needs the
operator to see and use the target, which means `SwitchDesktop` -- replacing
their entire screen for the duration. Credentials supplied at launch avoid
it where the target allows; otherwise the structural guarantee and an
interactive login are mutually exclusive, and the operator chooses per run.

**Not yet wired into the tool layer.** The strategy is a proven backend
primitive. Making the MCP tools drive a hidden-desktop target means routing
every existing tool's backend calls through the strategy's thread and adding
a launch path with its own consent -- a deliberate, separate change, because
process-launching widens the tool's authority and deserves its own scoping
rather than riding in on this one.

### D52. hidden_desktop is wired through one seam, and launch is consented

**Decision.** A session carries an optional `runner`, and every
target-touching call in the tool layer goes through `session.run`. For an
ordinary session `run` is a plain call; for a hidden-desktop session it
marshals onto the desktop-bound thread. One seam covers every tool, so
`describe`, `read`, `click`, `capture`, `probe`, the actuation ladder and
the grid probe all work against a hidden-desktop target unchanged.

**Why a runner on the session, not a strategy object threaded everywhere.**
The alternative was passing a strategy through every method and every
backend call -- dozens of sites, each a chance to forget one and leak a call
onto the wrong thread, where it silently sees nothing. Routing through the
four chokepoints (`_trees`, `_blocking`, `_resolve`, and a `_perform`
wrapper) instead means the seam is small and the failure mode is impossible
to reach by omission: a call that does not go through a chokepoint is a
direct backend call, and those were already the exception. `session.py`
stays platform-neutral -- it holds a callable and knows a session may route
its calls, not how.

**Re-entrancy is load-bearing.** An actuation is marshalled as a whole, and
inside it a postcondition resolves the tree and a snapshot is taken --
each calling back through `session.run`. `HiddenDesktop.run` executes inline
when already on the worker thread, so those nested calls do not wait on the
worker they are running on. Without it every verified actuation on a hidden
desktop would deadlock.

**Launch is the tool's first process-spawning authority, and it is
consented like everything else.** hidden_desktop is launch-only (D51), so
`launch_isolated` is the only way to open such a session -- and launching an
arbitrary command is the widest thing the tool can do. It is gated the way
R1 gates automation: a launch grant, keyed by the exact command, that the
operator records after being asked. An unapproved command returns
`needs_consent` naming it; approving one command does not approve a
neighbour with an extra argument. The launch itself is then the target
consent -- a pid grant is recorded from it, so no second question is put
about a target the operator just asked to start.

**Teardown is owned by the tool layer.** The `HiddenDesktop` is held on the
Toolbox by session id, not on the neutral Session, and `release` tears it
down -- terminating the target and closing the desktop. A process stranded
on a hidden desktop is invisible, so leaking one is especially bad, and
release is where it is prevented.

**What stays out of reach, and is not pretended otherwise.** A
hidden-desktop target cannot be seen or touched by a person, so anything
needing interactive login (the sign-in this class of target often shows on
launch) cannot proceed there without a `SwitchDesktop` that takes over the
operator's screen -- which this does not do. For those, `minimized` remains
the working strategy.

### D53. hidden_desktop launches the direct pid, and fits only classic Win32

**Two findings from launching a real app onto a hidden desktop, both of
which corrected something.**

**The launched pid is the CreateProcess pid, not an announced one.** The
first `launch` always piped the child's stdout and read a JSON pid line --
because the read-only tests launch a virtualenv `python.exe` that re-execs,
so CreateProcess returns a stub that owns no windows. But a real application
announces nothing and never closes stdout, so waiting for that line hangs
the launch outright. So the announcement is now opt-in (`announces_pid`,
off by default): an ordinary executable uses `pi.dwProcessId` directly, and
only a re-execing launcher asks for the pipe. Off was the only safe default
-- the wrong one hangs on everything that does not print a pid.

**The strategy fits classic single-process Win32 targets, and not
Store-activated ones.** Measured: launching `System32
otepad.exe` onto a
hidden desktop opened, held the guarantee, and tore down cleanly -- but the
session saw no windows, because Windows 11 ships Notepad (and Solitaire, and
Paint) as a Store app. `notepad.exe` is a stub that hands off to a packaged
process the shell *activates* on the input desktop, ignoring the `lpDesktop`
in STARTUPINFO. The real app lands on the operator's screen and the launched
pid owns nothing. `charmap.exe` and `winver.exe` -- classic single-process
Win32 -- launch onto the hidden desktop and are fully driveable there;
Character Map was launched, described, and captured with its window never
appearing on the operator's screen.

This is a genuine limit on which targets `hidden_desktop` fits, and it
compounds the interactive-login limit already recorded: a target must be
both classic Win32 *and* not require a person to sign in for the strategy to
be usable end to end. A Store-activated target cannot be isolated this way
at all, and there is no workaround at this layer -- activation is the
shell's, not ours to redirect.

### D54. Phase A: the gate is one command, the tool surface is a package, and strays cannot hide

**Context.** The audit of iteration 5 found the design sound and the
hygiene behind it: no linter or type checker ran, `tools.py` had reached
1,767 lines, two draft modules had been left beside their real versions in
one session, and tool test coverage was uneven and listed by hand. These
four are Phase A of the roadmap, done before Phase B because Phase B will
generate change and a gate has to be watching first.

**The gate is `pytest`, and nothing else.** ruff and mypy are dev
dependencies with explicit configuration in pyproject.toml, and
`tests/test_quality.py` runs both as tests. A separate lint command is a
command someone forgets; a test cannot be forgotten by anyone who runs the
tests. The rule set is correctness and modernisation (F, B, E, W, I, UP,
SIM, C4, RUF) with five stylistic rules ignored and stated; the security
and blind-except families are deliberately absent, because the backends
catch broad exceptions around Win32 calls on purpose. mypy runs with
`check_untyped_defs` over `src`. The first run found 25 type errors, and
several were real: camelCase keyword arguments to the MCP annotation and
image types (accepted by aliases, so never noticed), an implicit-Optional
context parameter, `truncated` typed as int, and the phase-1 runner using
an Optional tree unguarded.

**The tool surface is a package, composed from one core.** `tools.py`
became `tools/`: `core.py` holds the dataclass fields and every shared
helper (`_trees`, `_resolve`, `_one`, `_prepared`, `_perform`, ...), and
six family modules -- lifecycle, discovery, status, actuation, human,
learning -- each subclass it and hold only their tools. `Toolbox` in the
package root inherits from all six and defines nothing. Every method moved
verbatim; the only change is which class it lands in. Largest module 340
lines; the seam that routes calls onto a hidden desktop still has exactly
one definition. A reader opens the file named for what they are looking
at; a caller still holds one object.

**Strays cannot hide, and the guard found something on its first run.**
`tests/test_structure.py` asserts every module under `src/ghostdriver` is
reachable from an entry point -- transitively, over the source tree,
because "imported by something" lets two dead modules vouch for each
other. Its first run reported that the `minimized` isolation strategy
(`isolation.py` and `backends/windows/isolate.py`) is reachable from
nothing: proven against the fixture in D49, never wired into `attach`;
only `hidden_desktop` was (D52). That is not a stray. It is the strategy
that fits a target which is already running and needs a person to sign
in, which is to say the primary target, and today it cannot be selected.
It is carried as an explicit known-unwired list with the reason beside
each entry, a second test insists the list stays true, and wiring it is
the first item of Phase B. Tests import only from `src`: a module kept
alive by its own test is the case this is meant to catch.

**Coverage by enumeration, not by hand.** `tests/test_tool_contracts.py`
derives the tool list from `Toolbox` itself and checks three promises over
every tool: an unknown or released session is refused first, a lower tier
cannot call a higher tier's tool, and the tool surface and the policy's
tier table name the same tools. A tool added tomorrow is in every
parametrisation the moment it exists; one whose required arguments the
file cannot guess fails loudly rather than being skipped. `release` is
the one exemption from the first promise, by design (idempotent teardown),
and has its own test saying so.

**The suite itself was stealing the operator's focus, and now cannot.**
Reported by the operator mid-run: a window briefly took their focus while
they typed. Measured with a foreground monitor correlated to per-test
timestamps: four ungated tests -- one in the launch tests, three in the
isolation tests -- launched the fixture with `--onscreen`, and that option
showed the window with `SW_SHOWNORMAL` and no `WS_EX_NOACTIVATE`. A new
top-level window shown that way activates itself, and Windows permitted
it because the test runner descends from the process the operator was
typing into (the foreground-lock rule's exception). The operator's focus
went to fixture windows for about four seconds in a row. Nothing under
`src` was involved -- no code there activates a window, and the
tool-driven tests assert the foreground handle unchanged -- but the
promise the tool makes was being broken by the suite that tests it, and
nothing in the suite noticed before a person did.

Two changes. The fixture is now non-activating on-screen as well as off:
`WS_EX_NOACTIVATE` always, `SW_SHOWNOACTIVATE` always; a fixture that
must take the foreground says so with `--grab-foreground-after`, which
calls `SetForegroundWindow` and works regardless. And
`tests/focusguard.py` watches `GetForegroundWindow` for the whole session,
records every change to a window owned by a process descended from the
runner (the operator switching to their own windows is not ours to
record), and `tests/test_zz_focus_guard.py`, last in the run, asserts the
record is empty. It stands down under `GHOSTDRIVER_ALLOW_FOCUS_TESTS`,
whose tests take the foreground on purpose. The watch's logic is proven
with a fed sequence and a real child process rather than by stealing a
real operator's focus to show the guard would notice.

**One flake, made self-explaining.** A full-suite run found a fixture
window minimized that nothing minimized, for the second time; alone it
never reproduces. `restore` now names what it restored -- class and
visibility -- so the next occurrence says which window it was.

### D55. The minimized strategy is wired, and nothing ever un-minimizes

**Context.** Phase A's stray-module guard found the `minimized` isolation
strategy reachable from no entry point (D54): built and proven against the
fixture in D49, never connected to `attach`; only `hidden_desktop` was
(D52). It is the strategy that fits a target which is already running and
needed a person to sign in -- the primary target -- so it was first in
Phase B.

**The wiring.** `attach(isolation="minimized")` locks the main window
handle, puts it away without activating anything else, and starts a
`MinimizedWatch`: a background thread polling `watch_once` under one lock,
the same hold and flap rules D49 proved. The watch is held on the Toolbox
by session id, like a hidden desktop, so the neutral `Session` stays free
of threads and handles. `_trees` reads the locked handle's tree for such a
session rather than selecting by visible nodes, which for a minimized
target can flip to a proxy holding none of the UI. Every session tool
reports what the watchdog saw since the last call as `watchdog_events` on
its own result -- `describe` as readily as `click` -- because the event is
the product and a caller should not have to know which tool to ask; the
wrapper that does it is applied once, in the package root, to every method
whose first argument is a session id. `restore` is refused on such a
session, since the watchdog would put the window straight back. Proven
through the tool layer on the fixture: attach puts it away with nobody's
focus moving, read and click work on the locked window while minimized,
a self-raised modal is caught, photographed, put back and reported on the
next result, once.

**Nothing un-minimizes, ever -- measured, not decided.** The first release
path put the window back with `SW_SHOWNOACTIVATE` and the operator, at
the keyboard, felt it take their focus. Measured against a plain top-level
window (even one with `WS_EX_NOACTIVATE`), each in a fresh process:
`ShowWindow(SW_SHOWNOACTIVATE)`, `ShowWindowAsync(SW_SHOWNOACTIVATE)`,
`SetWindowPlacement(SW_SHOWNOACTIVATE)` and `SetWindowPos(SWP_NOACTIVATE |
SWP_SHOWWINDOW)` all un-minimize *and activate* the window;
`LockSetForegroundWindow` around the show stops the target taking the
foreground but moves the foreground somewhere else instead. The
documentation's "not activated" does not hold for un-minimizing when the
caller is allowed to set the foreground, and every process launched from
the operator's own application is. The no-activate show does hold for the
case `restore` was built on -- a toolkit's minimized owner proxy, whose
forms the application re-shows itself -- which is why its tests passed
while the promise was false in general. So: a released minimized session
leaves the window minimized and says whose doing that is; `restore`'s
documentation now says it can bring the window to the front and that
`took_foreground` reports whether it did; and the operator un-minimizes
from the taskbar, which costs them nothing and cannot surprise them. The
measurement script is not kept: it steals focus by design, and the
finding is recorded here instead.

**The known-unwired list is empty again.** As intended: the test that
insists it stays true made removing the two entries part of the work.

### D56. Elements that are not windows can be named, driven, and denied

**Context.** The primary target's record tabs and its navigator buttons
exist only on the accessibility surface: to the window tree a tab strip is
one control with nothing inside. Locators named windows, so the safest
things to drive could not be named, and the denylist, matching captions,
could not forbid an unlabelled button at all. B1 of the roadmap.

**The locator grows two keys and stays one grammar.** `type=` and `name=`
make an *element* locator: `type=TabItem name="Components"`, or
`type=MenuItem index=1 within=(class=ToolbarWindow32)` for a button with
no name. `text=` is a synonym for `name=` on an element; `class=` matches
the element's own class; `within=(...)` may name an ancestor element or
the host window, and a window scope narrows the *walk*, not just the
matches -- on a target with a thousand windows that is the difference
between a query and a survey. `find`, `read`, `wait_for` and `click` take
either kind; the typing verbs refuse an element and say why (keystrokes go
to a window, and an element without one has nowhere to receive them).
`AccessibleElement` is platform-neutral like `WindowNode`, and answers the
same names (`text`, `visible`, `enabled`, `handle` -- the host) so the
wait conditions and the actuation gate read it unchanged.

**Identity, for the denylist.** An element is known by its caption, its
type-qualified caption (`TabItem:Change Log`), its automation id
(`Button#btnDelete`), and -- the case that motivated this -- its type and
position under its host (`MenuItem#3@ToolbarWindow32`). The denylist
matches any of them, so an unlabelled destructive button is deniable by
what and where it is. Measured on the fixture's real Win32 toolbar: its
buttons reach the surface as MenuItem elements with Invoke and no name,
which is what the primary target's navigator buttons will look like.

**The posted click goes first, and the pattern is the fallback --
measured.** Selecting a tab item through its SelectionItem pattern marks
it selected and the application's page never switches: programmatic
selection on a Win32 tab control sends no change notification, so the
handler a person's click would run does not run. It is D21's split again
-- the surface changes, the application does not know -- and an
expectation on the tab's selected flag *passes* while the effect a person
would see never happens. So `click_element` ranks the button pair posted
to the host window at the element's rectangle before the pattern, and
`Attempt` gained a `rank` so a verb can order a tier later without
misreporting which tier it was (`tier_used` stays the truth). The posted
click goes through the control's own mouse handling, which notifies the
application exactly as a person's click would, and it is the only route
on a Profile L1 target, whose elements publish nothing. The pattern stays
for a host that does not answer posted clicks. The measurement is kept as
a test. The lesson generalises: an expectation should name the effect a
person would see, not the surface's own flag.

**Proven on the fixture**, which grew a real SysTabControl32 whose items
switch its pages and a real ToolbarWindow32 of unlabelled buttons: the walk
sees what the window tree cannot; every suggested locator resolves again;
a tab click switches the page and re-reads as selected; an unlabelled
button is clicked by position; the denylist refuses by typed caption, by
position, and by plain caption pattern; and it all works on a
hidden-desktop session, where the COM client has to be created on the
desktop-bound thread.

### D57. The operator directory, and the workflow runner that reads from it

**Context.** B2 of the roadmap: an end-to-end harness against the real
application. The operator's rule is that knowledge of the target lives in
*no repository* -- not this one, not a private one. So the harness has two
halves: a generic one here, and everything that names a target in a local
directory the tool reads from and nothing else.

**The operator directory is the rule made mechanical.** One configured
path (`GHOSTDRIVER_OPERATOR_DIR`, or `--operator-dir`) holds
`profiles/`, `workflows/` and `reports/`. `OperatorDir.resolve` refuses a
directory inside a git checkout, so target knowledge cannot be one
careless `git add` from a commit by a path the tool will read from; and a
test refuses profile documents, workflow files and report folders
anywhere in the source tree. Its first run found three probe-output
profile documents sitting in the checkout root -- untracked and ignored,
but inside the repository directory, one of them named for the target's
version. They were moved out, not deleted.

**It also refuses a packaged application's virtualized AppData.** Found
while creating the directory: this tool's process tree runs inside the
packaged desktop client, and Windows redirects a packaged app's AppData
writes to `...\Packages\<app>\LocalCache\...`. A directory made under
`%LOCALAPPDATA%` from here landed there, where the operator's own shell
would never see it. Path resolution sees through the redirection, which
is how the refusal can tell; the directory lives under the user profile
root instead.

**A workflow names no target.** It is a JSON file of steps -- one session
tool each, with arguments and optional assertions by dotted path
(`values.0.text`), a `contains` form, and `expect_ok: false` for a step
that exists to prove a refusal -- plus the tier and isolation to attach
under and a profile to attach with. The pid comes from the runner's
argument. Running a workflow *is* the operator's consent for that target:
it is recorded as an operator-tool grant naming the workflow, so the
record says why. The runner stops at the first failed step, because on a
real application the steps after a failure act on a screen nobody
intended; runs the whole thing under an interference watch, where the
target taking the foreground fails the run whatever the steps said and a
moving cursor is reported rather than judged (this tool never moves it,
so movement is the operator, and the operator is expected to be away);
collects every watchdog event; and writes a report -- every step, every
result with its pixels left out, every event -- back to `reports/`.
`ghostdriver run-workflow <name> --pid N` prints the verdict and exits
non-zero on anything but a pass.

**Proven with fakes and with the fixture.** The runner is pure with
respect to the desktop, so its behaviour -- stop on failure, release
regardless, fail on a foreground event, collect watchdog events, refuse
an unknown tool by name -- is proven with a scripted toolbox. The
fixture run goes through the real tools and the CLI: a four-step
workflow in a temporary operator directory, including an element click
and an expected refusal, passes, writes its report, and records no
foreground event. The only application any workflow in this repository
names is the fixture.

**What is now the operator's.** The workflows against the real
application, its profile, its curated lists: written into the operator
directory, run with the command above, asserted against the
application's own audit trail. The template in that directory is the
fixture workflow, so the shape is at hand.

### D58. An embedded web document is driven through the surface it already has

**Context.** C1 of the roadmap. The region model (D41) classified an
embedded Chromium region as `web-document` and could say whether its
accessibility surface was live, and nothing drove its content. The plan
said: reach it through the accessibility tree first, under the same
tiered discipline, and add a browser protocol only for an engine that
cannot be woken. Measured against a real Chromium engine launched onto a
hidden desktop with a fixture page, so nothing could reach the operator's
screen. No browser protocol was needed.

**The first question wakes the engine.** Before anything asked, the
region model reported the document with `access: none` and nothing
reachable: a Chromium host keeps its accessibility tree dormant until an
assistive client asks. The first element walk *is* the ask -- it reaches
the engine as a WM_GETOBJECT -- and the walk a second later carried the
page. So `walk_elements_awake` repeats a walk under a web host until a
Document appears or a three-second budget is spent; outside a web host the
first walk is the answer. `surfaces` then reports the region live, and
B1's element locators name the page's buttons, tabs and inputs unchanged:
`type=Button name="Expand All"`, `type=TabItem name="Components"`,
`type=Edit name="Part number"`.

**Clicks and tabs: the posted click on the host, as on a native target.**
A page button and an ARIA tab were both driven by the button pair posted
to the host window at the element's rectangle, verified by the page's own
effect (its status text, its panel). The Invoke pattern also works on
Chromium; the B1 ladder order stands.

**Typing reaches the page's own script -- measured, one input event per
character.** Characters posted to the host go to whatever the host has
focused, and a posted click focuses the element. So `type_text`,
`set_value` and `send_keys` now accept an element: focus by posted click,
then keys to the host. Three measurements shaped it:

- A web host ignores the edit-control selection messages `set_text` uses
  to clear a field, so `replace_value` clears with keys the host must
  honour: End, then one Backspace per character held. A posted Ctrl+A is
  no use -- posted keys carry no modifier state.
- At machine speed the engine applied one Backspace *after* the text that
  followed it, leaving the field a character short: key-downs and
  characters travel different paths to the renderer. So the clearing is
  waited for -- typing starts only once the field reads empty -- and the
  order is a fact rather than a race.
- The Value pattern *does* commit on Chromium -- SetValue fired the page's
  input and change events -- unlike the native HWND bridge (D21). The
  D30 rule needed no change: offered only under a commit expectation, it
  is taken and verified on Chromium and falls through to typing on a
  bridge. `NAMED_KEYS` gained the caret-movement keys; named keys carry
  nothing, so they stay allowed where characters are refused.

**A finding for B3, recorded so it is not re-measured.** Posting
KEYDOWN, CHAR and KEYUP per character double-typed on Chromium: the
engine runs TranslateMessage, so the posted key-down produced its own
character alongside the posted one, and without shift state the letter
came out lower-case. On a target that translates its own keys, the bare
WM_CHAR is the right shape, which is what the tool sends.

**The boundaries hold on the web too.** A web password field publishes
`IsPassword` on the surface; `AccessibleElement` carries it, and the same
refusal that protects a native password box refuses it: a person types
it, never this. The denylist matches a page button by caption exactly as
it would a native one.

**Proven** on a real engine, launched through `launch_isolated` onto a
hidden desktop and driven through the ordinary session: wake, resolve,
click, tab, replace a value and see the page commit it after a tab-out,
take tier 1 under a commit expectation, refuse the password field. The
test skips where no Chromium engine is installed; the fixture page is
the only web content any test in this repository names.

**What this does not cover.** A host that does not answer posted clicks
or characters -- one that draws its own elements and reads the real input
queue -- would need the pattern route alone, which is on the ladder, or
the browser protocol the plan deferred, which is still deferred: nothing
measured here asked for it.

### D59. The backend boundary is a registry and a contract; Linux is specified, not built

**Context.** C2 of the roadmap, on a machine with no Linux desktop and no
WSL. Everything in this project that mattered was a measurement
contradicting a model, so a Linux backend written here would be code
nobody has run -- the thing the discipline exists to prevent. What could
be done honestly was done: the boundary the Linux backend will fill was
made real, and the specification says what to build and, above all, what
to measure first.

**The boundary.** The tool layer, the CLI and the probe runner imported
`backends.windows` directly at fifty sites. They now ask a registry:
`backends.current()` returns the platform's backend, and every backend
answers the same `CONTRACT` of twenty-nine names -- the tree, reading,
modality, elements, regions, acting, isolation, interference, and the raw
API. The Windows package binds each name to its module lazily, so
importing the backend costs nothing and COM is touched only by a caller
who needs it; the table that binds them is checked against the contract
at import. A test holds the line mechanically: no module above
`backends/` imports a platform package, every contract name resolves on
Windows, and the Linux package refuses every name with the same message
pointing at the specification. The rewiring changed no behaviour: the
full suite is the proof.

**Why a lazy namespace and not a protocol class.** The names are
functions and classes from a dozen modules, used by name at call sites;
a namespace that answers those names is the smallest thing that makes the
seam explicit without rewriting every caller into method calls on an
object. A `Protocol` can be layered on later for the type checker; the
contract tuple is the checkable part today, and the structure guard
sees the bound modules because the package declares them as imports
under `TYPE_CHECKING` -- a table of strings is exactly what would let a
stray hide.

**The specification** (docs/LINUX.md) maps every contract name to its
Windows mechanism, its proposed Linux mechanism, and the decision whose
measurement must be repeated: AT-SPI2 for the tree, reading and tier 1;
`XSendEvent` to a window for tier 3, with the synthetic-event flag named
as *the* measurement that decides whether a Linux tier 3 exists; a nested
X server with its own AT-SPI bus for the structural isolation guarantee,
which needs no thread binding because the display is an environment
variable; EWMH state for modality, restore and the watchdog. It says
what is the same (everything above the backend), what needs its own
decision (Wayland, sandboxed applications, the synthetic flag, MPX --
after the nested server, not before), describes the hostile GTK fixture
in the Windows fixture's shapes, and lists the eight measurements in the
order they unblock one another. A test insists every contract name has a
row in it.

**What was left out, and why.** The backend itself, the GTK fixture, and
every `tests/test_linux_*.py`. WSL2 with `Xvfb`, `at-spi2-core` and
PyGObject is enough to build all of it headlessly; installing WSL is a
system change this tool does not make on the operator's behalf. Until
then `ghostdriver.backends.linux` is a refusal with a pointer, which is
the truth.

### D60. Re-audit after the roadmap: the figures moved, and one promise had slipped

**Context.** The audit at the close of iteration 5 scored the four
constraints met, code quality "good, with smells", coverage "broad,
uneven", real-target testing "thin", and Linux "not started". Phases A
to C of the roadmap (D54 to D59) were meant to move those rows. Re-measured
on 2026-09-03 from the repository, not from memory.

**What moved.** `tools.py` at 1,767 lines is a package of eight modules,
the largest 363; ruff and mypy run under `pytest`; a structure guard
refuses stray modules, target-shaped files and platform imports above the
backend boundary, and on its first runs found an unwired strategy and
three profile documents in the checkout root. 752 tests; every tool's
session and tier gates are checked by enumeration; the per-tool floor
rose from one test file to three; a session-long focus guard fails any
run in which a test-spawned window takes the foreground. Elements that
are not windows and embedded web documents are reached, driven and
deniable. Linux is specified with its seam in place. Those rows now read
"good, guarded", "broad, evened", "reached", "specified".

**What did not move, and must not be dressed up.** Real-target testing
is still thin. The product half of the harness exists -- the operator
directory, the runner, the report -- and no workflow has run against the
real application, because that half is the operator's. The row keeps its
score.

**The slip, and its guard.** A2 promised no tool module over about 400
lines. B1 and C1 grew `tools/core.py` to 451: the element resolution
and the actuation plumbing had both landed there. The actuation plumbing
-- resolve to one, gate, cadence, perform, remember, report, expectation
-- moved verbatim to `tools/acting.py` as `_ActingCore`, which the acting
families subclass; `core` keeps the fields, the tree chokepoints and the
resolver. And the promise is now a test: no module under `tools/` over
400 lines. A promise that lives only in a decision record is one a later
phase breaks without noticing, which is exactly what happened.

**The scorecard page** was refreshed in place rather than replaced, so a
reader sees what changed against what was claimed.

### R5. Consent covers a process tree, and so does a session

**Revises R1.** Found in the first real use after rollout: driving a file
upload into a web application, the operator was asked to approve the
browser's file dialog on every upload. A Chromium browser opens that
dialog in a helper process with its own pid, and R1 keyed consent by pid.
The question it asked was "may I automate the application you just
approved?", and a permission scheme that asks that is keying on the
wrong thing.

**An application is a process tree.** A decision recorded for a pid now
applies to every process descended from it, evaluated at the moment of
the check by walking parents (psutil, which refuses a parent created
after its child, so a recycled pid cannot pose as an ancestor). A
decision about the pid itself wins over an inherited one, in either
direction; a restriction inherits exactly as an approval does; revoking
the ancestor stops a session open on the child. `list_targets` shows the
child as allowed, and the grant record says "via pid N, its parent". The
walk is injectable and proven with a table; the real case is proven with
the fixture spawning a second fixture in a child process.

**And a session sees its target's tree.** Consent that covers the dialog
is only half of it: under per-pid enumeration the dialog was invisible to
the session that needed it, so a second attach was the only way in.
`all_windows=true` now enumerates the target and every descendant, the
main window stays the target's own, every element and window carries its
`pid`, and modality is read across the tree -- a dialog in a helper
process disables the target's window from outside its pid, and reading
the target alone reported a block nothing accounted for. The dialog's
button is the application's button, found and clicked from the one
session, with no second question.

**A defect this exposed.** `index=` was applied inside each window tree
rather than across the combined matches, so it could never name a match
in a second window -- with a session that sees a whole process tree,
exactly where a dialog's controls are. It is applied after the trees are
combined now, for windows and for elements alike, and the fixture test
picks the child's button by index among two identical ones.

**Extended in D71: the watchdog and the interference watch follow the
tree.** Both sampled the target pid alone until then.

### D61. The ask goes where the person is looking, and a click has buttons and modifiers

Two findings from the first real use after rollout, both about the tool
meeting the person halfway.

**`await_human` puts its ask on the screen.** The operator had to expand
a tool call in the chat client to learn what the tool needed them to do,
and while the call blocked, waiting, nobody was told anything. The client
did not carry the elicitation, so the ask lived only in the call's
arguments. Two layers now carry it. The tool's description tells the
agent to say the ask in chat, in its own message, *before* calling --
the call blocks, so afterwards is too late. And for the length of the
wait, the ask is shown in `OperatorNotice`: a small window in the corner
of the operator's screen that says what is being waited for and that the
wait ends on its own once the application shows it done. It is the one
thing this tool ever puts on the operator's screen, and it obeys the
rule everything else obeys: topmost so a full-screen application cannot
hide it, a tool window so it is not in the taskbar, created no-activate
and shown no-activate, and it answers a click with "do not activate me".
Its message loop is its own thread, so the waiting tool is not the one
pumping it. Proven: visible, topmost, never the foreground, on screen
during the wait and gone after, and switchable off. It is a contract
name, and the Linux specification says what it becomes there.

**A click can be a right click, with Ctrl held.** The step the operator
was asked to take was a Ctrl+right-click on a status bar to open a menu;
the tool knew exactly what was needed and could not do it, because
`click` posted a plain left pair and nothing else. It now takes `button`
(left, right, middle) and `modifiers` (ctrl, shift). The button is the
message id; the modifiers ride in the message's own flags, which is the
only place a posted message can carry them -- the real keyboard is not
pressed, so a target that asks `GetKeyState` sees nothing, while one that
reads the flags sees the modifier. A VCL control derives its shift state
from those flags (`KeysToShiftState`), so on the primary target this is
the Ctrl+right-click that opens its menu; the result's `expect` is how a
caller learns which kind of target it has. A pattern has no notion of a
button or a held key, so anything but a plain left click is tier 3
alone, and an unknown button or modifier is refused by name. The fixture
records the button and the flags its window procedure saw, so the test
shows a posted Ctrl+right-click arriving as one and a mismatched pair
completing nothing. The context menu a right-click opens is a new
top-level window, reachable with `all_windows=true` and, by its items,
with element locators.

**And a click can be aimed, and doubled.** From a second session's report:
a search result in a data grid could not be clicked, because the grid
paints its rows and exposes none of them -- to the window tree one grid
with nothing inside, to the accessibility surface only its scrollbars --
so no locator could name the link and `click` had nothing but the grid's
centre to aim at. `click` now takes `at`, a point {x, y} inside the
element (client-relative for a window, from the top-left for an
element), and `count` 2 for a double-click, which is how most grids open
a row. The route this makes possible is the one the surface model
already prescribes for an owner-drawn region: `capture` it, see where
the row is, click there. It is pixels guiding a posted message, not
pixels replacing structure, and nothing is activated. A point outside
the element is refused before anything is sent. A double is posted as a
person's would arrive -- down, up, the button's DBLCLK, up -- whether or
not the class asked for double-clicks, and the fixture grid records
which row was hit. The keyboard remains the other route into a grid:
`send_keys` with `down` and `enter`.

**Two timing-sensitive tests made robust** on the same run: one compared
foreground handles across the moment the operator switched windows of
their own (it now asks whether the *target* came forward, which is the
claim), and one released a session before the watchdog had polled on a
loaded machine (it now waits, bounded, for the event itself).

### D62. Every tool call is traced into the operator directory

**Context.** Asked whether the calls another session was making could be
seen from here, the honest answer was no: each session launches its own
server over stdio, and that process kept no record. Every call, argument
and result vanished with the session unless the model pasted them into
chat, so a report like "it could not click the link" arrived without the
call it had tried.

**Decision.** The Toolbox's one outgoing seam -- the wrapper that already
appends watchdog events to session tools -- now records every public
tool call: when, which session, which tool, the arguments as bound to the
tool's own signature, whether it succeeded, the error kind and message,
the elapsed time, the count of watchdog events, and the parts of the
result worth keeping (tier used, verification, match count, display).
One JSON line per call, appended to
`<operator dir>/logs/ghostdriver-<date>-<pid>.jsonl`, one file per server
process per day. Pixels are left out and long values trimmed: the trace
is for reading, not replaying. `ghostdriver trace` prints the recent
lines of the newest file, or all files, or one session.

**On when the operator directory is configured, and only then.** The
trace holds locators, captions, values read from the target -- target
knowledge -- so it lands in the one place that knowledge is allowed to
land, and nowhere at all when that place is not configured.
`GHOSTDRIVER_TRACE=0` turns it off; `GHOSTDRIVER_TRACE=<path>` names a
file instead. A trace that cannot be written never stops the call it
traces.

**A slip caught by the contract test.** The first accessor for the trace
was a public method on the Toolbox core, so the wrapper wrapped it too
and recursed; the tool-surface test would also have flagged a public
method no tier names. It is private now. The wrapping of every public
method is the boundary the contract test guards, and this was the
boundary doing its job.

### D63. Field feedback from a real session, and what it changed

**Context.** A session driving the primary target (Profile L1, VCL) at the
interactive tier reported back in detail after failing to complete its
task. The report's own through-line was right: the diagnosis layer holds
up, and the actuation layer runs out on input-lossy, owner-drawn targets.
Taken in cost order.

**`capture` could return the wrong pixels, silently.** Naming a modal
rendered the *main* window cropped to the modal's rectangle: the pixels
underneath the modal, returned with confidence. `capture` always rendered
the main window and used a locator only as a crop. It now renders the
top-level window that holds the match -- a modal is its own top-level --
and for a bare region, the window overlapping it most, the smaller one
among equals, since a modal lies inside its owner's rectangle and is the
one on top. The result says `frame: "screen"` (the frame every rectangle
in this tool uses; `find` now says so too), names the window it rendered,
and flags a region it had to clip. A region overlapping no window is
refused, with the frame named. Proven on the fixture's modal, by locator
and by a region copied from `find`.

**Typed text dropped characters, and nothing could deliver the value
whole.** An address field lost `N`, `@`, `ht` and `ch` across six
attempts at both cadences; the read-back caught every one (kept), and
then handed the problem back. `set_text` has a third rung: paste. The
value goes onto the clipboard and in with one WM_PASTE, so a control that
drops a character now and then cannot lose part of it; the clipboard's
prior text is put back. Typing stays first -- it is the toolkit's own
path, and paste uses the session-wide clipboard -- and the read-back
after each rung is what makes the fall-through safe. Attempts now carry
a name, and the result says which `route` delivered.

**No modifiers on `send_keys`.** A posted keystroke carries no modifier
state, so ctrl+ combinations cannot be sent as keys, and saying so is
better than pretending. What Ctrl+A/V/C/X/Z become inside an edit control
are messages, and those are sendable: `send_keys` accepts `select-all`,
`paste`, `copy`, `cut` and `undo`, and a `ctrl+x` token is refused with
that alternative named. Ctrl+End in a grid has no message equivalent; the
caret keys already in `NAMED_KEYS` are the route there.

**Three tools existed and were never found.** The session dismissed a
dialog unread because nothing named `modals` at the moment it learned
the target was held; it searched a grid by paging blind because nothing
named `probe_grid`; it fought a dropping field without
`record_input_sensitivity`. Errors and blocked states now name the tool
that addresses them: every `blocked` report carries the hint to read the
dialog with `modals` and hand it to a person with `await_human`; a
pixels-only region in `surfaces` names `probe_grid`, `capture`, the
point click and the caret keys; a `set_value` mismatch says typing and
pasting were both tried and names `record_input_sensitivity`. `attach`
says when the main window is minimized or hidden and names `restore`.
The consent question says approvals live for one server run, so a
restart is recognised rather than read as a fresh denial. And the
locator parser, shown an unquoted regex with a space, says how to quote
it.

**Not done here, and why.** A `grid_seek` that pages an owner-drawn grid
and matches a value is the right primitive for a target made of such
grids, and the report is right that every caller will otherwise write
that loop badly. It needs the copy route (`probe_grid`) and the caret
keys, both of which exist, and a fixture grid with a selection model to
prove it against; it is the next item. Persisting consent across server
restarts would revise R1's "approvals die with the session", which is
the operator's rule to change, not this session's; the message change
above is what could be done without changing it. The point click on the
target's grid reporting delivered-but-no-selection is consistent with a
VCL grid asking for focus on mouse-down and declining when the
application is not foreground -- the no-focus rule meeting the grid's
own check -- and is why the keyboard, not the click, is the way to move
through it; that is a measurement for the next session on the target.

### D64. The second field report: a shared server, an empty probe, and two grids

**Context.** The same session came back with four observations. Three are
the tool's; the fourth belongs to the target and went to the operator's
own notes.

**"Consent evaporated between attach and the next call."** The trace
(D62) answered this without a hypothesis. At 14:05:24 one chat attached
the sandbox target; at 14:05:27 a *second* chat -- same server process,
same trace file -- recorded `grant_targets(restrict=[that pid])` with a
note saying the operator had told it to leave that target alone; at
14:05:33 the first chat's next call was refused. Not a race and not the
deploy: the operator app runs one server process for every chat, so a
restriction recorded in one chat is a restriction in all of them, and
"leave it alone" had been recorded as a restriction when it needed no
record at all -- nothing is automated without an allow. Three changes:
the refusal names the decision (when, via what, with what note), says
another chat may have recorded it, and says `allow=[pid]` reverses it
and the session then continues; `grant_targets` lists the open sessions
a restriction stops, with a caution; and the server's own instructions
say to restrict only what the operator ruled out. A grant now carries
its time. R1 stands: approvals live for one server run.

**`probe_grid` returned UNKNOWN on both grids, both routes, zero
lines.** The session's own conclusion was right -- the tool behaved and
the target exposes nothing -- and the report should have said so rather
than leave that to be worked out. An UNKNOWN finding now carries a
`meaning`: routes tried, that repeating will not change it, and what
remains (pixels via `capture` and the point click, the caret keys, a
person). Not a bug; a real outcome, said in the result.

**Posted row clicks select in one grid and are ignored by another, same
session, same technique.** Two controls of the same family on the same
target, one taking a posted click and one not, means the difference is
in the control, not the delivery. The likeliest difference is what the
control checks before acting. A VCL grid's mouse-down asks its form for
the active control, which the form records without needing the window
to be active, so that grid proceeds; a control that asks the window
state directly -- is my top-level window the thread's active one? -- can
return without acting. The first assumption here was that a background
application has no active window at all. The fixture disproved it: a
window shown without activation is still its thread's active window,
read with GetGUIThreadInfo. What need not be is a *second* top-level
window of the same thread -- a floating panel, a form docked out of the
main one, which is where a scheduling grid tends to live. This tool
cannot make it active without activating it (D55), and
`AttachThreadInput` -- the known way around that -- merges the target's
input queue with this process's, which moves the keyboard focus the
person is typing into: exactly the theft the tool exists to avoid. So
the answer is measurement, not a workaround: a `click` result carries a
`focus` block -- the thread's active window, its focus window, and
whether the clicked control's top-level is the active one -- with a note
when it is not. Proven on the fixture with a floating second window
holding a grid and a flag that makes grids check the active window: the
grid in the shell selects, the grid in the floating window is handed the
click and ignores it, and the result says why. The next session on the
target can read the two grids' blocks side by side.

**An invalid filter expression raises an error dialog rather than
emptying the grid.** Target knowledge; recorded in the operator's notes
for that target, not here.

### D65. The third field report: consent that lasts as long as the application, menus read from the menu, the clipboard read back

**Context.** Around a hundred and twenty calls against the target in one
session, two session losses, one hand-off to a person that turned out
not to be needed. Eight items; taken in cost order, and one of them
revises a rule.

**R1a: a decision about a target is kept for as long as that process
runs.** R1 said approvals die with the session, meaning the server run.
In the field the server run is shorter than the work: the operator app
relaunches, this server is redeployed, and each time the person was
asked again about an application that had not changed, and a session
found out only on its next call. What the person approved was *that
application, running*. So, when an operator directory is configured,
each decision is kept there -- one small file per pid, carrying the
process start time as the fingerprint, since a pid is reused and a pid
with the same start time is the same process -- and a new server run
reads back every decision whose process is still the one it was about.
Restrictions are kept the same way. Inherited decisions are not kept:
they follow from their ancestor's, which is. Without an operator
directory nothing changes. The trace also outlives the server, so a
call on a session id nobody has open is now told which run opened it,
against what, and how to open another one, rather than "attach first".

**`at` was there and the session did not know.** The first session's
server predated the aimed click; the re-attached one had it. The tool
description now names `at`, `button` and `count` in its first
sentences, not only in the parameter list.

**Address-bar `set_value` cleared the field.** A field with an
autocomplete or history list takes the clear and then the list takes the
keystrokes. Not reproduced on the fixture; what changed is the failure:
when the field reads back empty, the error says the clear took and the
text did not, names any window that appeared while typing, and says to
click then `type_text`, which does not clear first. Unproven text, said
so.

**Context menus were opaque.** `find` returned nothing for a `#32768`
window's items and the session clicked "Copy row values" by an offset
measured off a screenshot. The items of a popup menu are not windows
and, when the application draws them itself, not on the accessibility
surface either; but the menu handle answers for all of them. The window
is asked for its menu (`MN_GETHMENU`), and the menu for each item's
rectangle, state and caption. Menu items are elements now: `type=MenuItem
name="Copy row values"` clicks the captioned one, `type=MenuItem index=1
within=(class=#32768)` the one drawn by the application, whose caption
stays with it (its automation id says `owner-drawn`). Separators are a
type of their own, so indexes count the items a person sees. Proven on
the fixture with a menu of a string item, a separator and an owner-drawn
item. Whether the target's own menus keep a caption in the menu is the
next session's to read off the result.

**The clipboard read.** A target's own Copy command is the one exact
read some grids have, and the tool could trigger it and not read it.
`read_clipboard` reads text, at the interactive tier -- the clipboard is
the person's as much as the target's -- and its result says to read
straight after the copy and not to keep it. The backend contract gained
`read_clipboard_text`; the Linux table has its row.

**A capture can be kept; a wait can be long.** `capture` takes
`save_as`, a bare file name, and writes under the operator directory's
`captures/`; a path is refused, and the image is returned inline either
way. `wait_for` accepts up to 300 seconds and says what it used: a
screen that takes forty seconds to fill is one wait, not four.

**A regex with a space is one token.** `text=/Work Order/` used to be
split by the shell-style tokenizer and refused. A slash-delimited value
is one token to the person writing it, so it is quoted before the split;
the quoting hint remains for other values with spaces.

**Two small ones.** A tool refused for its tier now names the tier that
permits it and how to attach at it. And every result with rectangles
says the display scale when there is one: this server is not DPI-aware,
so at 125% it sees a 1920-wide screen as 1536 wide, and a screenshot
from a DPI-aware tool is in physical pixels; the session converted by
hand once. The number is measured from the display mode, which is not
virtualized, and the note says which frame every offset in this tool
uses. Making the server DPI-aware instead would put its rectangles in
physical pixels while an unaware target still takes client coordinates
in its own logical ones -- a conversion at every posted click, deferred
until a target needs it.

### D66. The fourth field report: a click goes to the window under the pointer, an empty answer is not an empty control, a frozen application says so

**Context.** A working day against two targets of the same toolkit --
the primary target and its configuration tool -- around a hundred and
fifty calls, four session losses, two hand-offs to a person that the
tool could have avoided. Written before D64 and D65 reached the running
server, so the first, fourth and fifth items and most of the tenth were
already answered; what follows is the rest, in the report's order.

**A click posted to a panel over a windowed child is dropped.** Four
clicks on a toolbar reported delivered and did nothing. The toolbar's
buttons were speed buttons -- no window of their own -- on a panel, and
the toolbar itself a window of its own inside another panel: a click
posted to the outer panel at the button's position reaches the outer
panel, whose toolkit hands mouse messages to its *non-windowed* children
only, and a child that is a window never sees a message addressed to
its parent. A person's click goes to the window under the pointer, so
this does too: the innermost visible child under the point, found with
`ChildWindowFromPointEx` down the tree, gets the message in its own
client coordinates, and the result says `delivered_to` whenever that is
not the located window. Proven on the fixture: a click on a page over
the Apply button reaches Apply. The report's other suggestion, real
input through `SendInput` when nothing is under the point, is refused
on the first constraint: real input moves the person's pointer and goes
to the foreground window, which is theirs. A click with nothing under
the point is delivered to the panel and says so; whether the panel does
anything with it is the panel's.

**A write that landed, reported as a failure.** A memo answered `""` to
a text query after a value visibly went in; the read path does not work
on that control while the write path does, and the tool reported the
success as a failure. A control that answers empty and *paints* content
is one whose read path is unreliable, not one that is empty, and the
two are told apart with pixels: the fraction of the control's rendering
that is not its background colour (`ink_fraction`, the most common
colour taken as background, sampled). `read` flags such a control
`read_unreliable` with the fraction; `set_value`, on an empty read-back
from a control that renders content, says the value may well have landed
and the read be the failure, and to verify by capture -- rather than
saying the field was cleared. Proven with the fixture's grid, which
answers empty and paints rows; the set_value path is the same test
applied at a different moment, and unproven against a memo. OCR was
asked for and is not done: the question here is "blank or not", which
pixels answer without reading them.

**A frozen application reported healthy.** `describe` returned every
window with an empty title and `find` said responsive. A hung window's
cached title still reads, so nothing the tool asked distinguished frozen
from busy; the system has that verdict -- `IsHungAppWindow`, a thread
that has pumped no message for five seconds -- and now `modals` lists
`hung_windows` with a hint, and `describe` marks the window. Proven on
the fixture with a thread that stops pumping on a timer.

**A wait that died with the server.** The server restarted during an
`await_human`; the wait died silently while the person was acting on it
and the client timed out later. A dead server returns nothing, so
"fail fast with `server_gone`" cannot be done from the server's side;
what can be done is to leave a mark. A wait's *start* is traced as well
as its end, and the lost-session hint (D65) now says when the previous
run was in a wait when it went, and what the person had been asked. Two
more things a person needed: to know the notice was shown (`notice_shown`
in the result) and to say "not now": the notice has a "Later" drawn on
it -- drawn, not a button control, since a child button takes focus on a
click and focus is what this window must never take -- and clicking it
returns the wait early as `deferred`, a kind of its own, neither refusal
nor timeout. `until` still takes a locator: a free-form "results grid
appears" is not a condition this tool can check, and pretending to would
verify nothing.

**A point read off a physical screenshot.** `display_scale` is on every
`find` and `capture` result now (D65); this adds `frame="physical"` on
`click` and `capture`, which divides `at` or `region` by the scale, so a
coordinate read off a DPI-aware tool's screenshot can be used directly.

**`enabled=` and `handle=`.** Both are reported on every element and were
refused as locator keys. `enabled=true|false` filters; `handle=0x...`
takes a result's `handle_ephemeral` and names one window exactly, valid
until that window goes.

**Not done.** Detecting an autocomplete edit by class and routing
`set_value` around it: the classes are the target's and belong in its
profile, where `record_input_sensitivity` already puts what a session
learns. Tooltips for unlabelled buttons: the toolkit keeps a hint on the
control and shows it only on hover, and nothing cross-process reads it
without the hover; a session that meets such a toolbar reads its
buttons off a capture, and a profile can name them.

### D67. The fifth field report: tightening the results that said ok for nothing

**Context.** A short run after the third and fourth reports landed. The
fixes from those held and two caught real errors within minutes -- a
capture that named the window it rendered, a coordinate note that stopped
a scale mistake. The report's through-line: the diagnosis layer is now
reliable, and what is left is that several results read `ok: true` for a
call that accomplished nothing, each documented in a prose note a
status-skimmer skips. Four such, tightened; two features; one thing not
built, and why.

**A click delivered to an inactive window read as success.** On this
target -- always in the background, never foreground -- a click's window
is never the thread's active one, and most controls act on a posted
click anyway (grids, tabs, buttons), so `ok: true` there is right and
must stay, or the tool reports failure for every working click. But a
control that *checks* focus drops the click, and `ok: true` with
`verified: "delivery_only"` buried the reason in the focus note. Now,
when the window is inactive and no `expect` confirmed an effect, the
result carries a top-level `warning` and `verified` reads
`"delivered_inactive"` -- the two fields a skimmer does read. Two opt-ins
join it: `require_active=true` refuses before delivering into a window
that would ignore the click, and `expect` (already there) confirms an
effect after. Not built: an `activate` that brings the window forward.
It is the one thing asked for that the tool cannot do without the thing
it exists to prevent -- a window is made active either by
`SetForegroundWindow`, which a background process cannot reliably do
(it flashes the taskbar and no more), or by `AttachThreadInput`, which
merges the target's input queue with this one and moves the keyboard
focus the operator is typing into (D64). A reliable `activate` is the
keyboard theft, so the honest answer to "act on a focus-requiring
control" stays: hand it to a person, which is why `await_human` was
made to work in the same report.

**`await_human` without a condition did nothing, silently.** It returned
`ok: true`, waited zero milliseconds, and -- the real defect -- never
showed the notice: the no-condition path returned before the notice was
raised. A hand-off that watches for nothing is refused now, naming the
two ways to give it something to watch. And the exploratory case the
report named -- asking a person to do a thing whose result you cannot
name a locator for, because you have never seen it -- gets
`until_change=true`: it baselines the surface digest `surfaces` already
computes and returns when it moves. That is the case that matters most on
this target, and it was the one `until` could not express.

**A `region` was dropped when a `locator` was also passed.** The smaller
form of the very bug the `rendered` field was added to catch: a parameter
discarded in silence. A region alongside a locator now crops within the
located window rather than being ignored.

**`expect` refused a string.** It is typed as `{locator, text}` and the
name invites a sentence; a bare locator string is now accepted as "this
is present now", the common case.

**A native container hid its addressable parts, and a point click that
missed reported `ok`.** A panel of toggle bars answers `find` with one
match, itself; its bars are either child windows or painted, and a caller
reduced to reading coordinates off a screenshot clicked left of a
twelve-pixel target and spent real time theorising about permissions.
`hit_targets` lists a container's child windows with their rectangles, so
a point click aims at a real one; none listed means the parts are painted,
and the answer is capture-and-offset or a person. The click itself does
*not* flag a point that finds no child window -- on an owner-drawn grid,
whose rows are painted, that is the normal and correct case, and a flag
there would cry wolf on every grid click. `delivered_to` still names an
intercepting child when there is one (D66); the container check is a tool
a caller reaches for, not a warning on every click.

### D68. Hot reload for development: implementation re-imported on change, live state kept

**Context.** The host spawns this server once and takes its tool list
once, at `initialize`. After that an edit reaches a chat only through a
host restart -- which also drops every open session, the loss the field
reports kept counting. Asked: can the server pick up changes without a
restart?

**Three layers, and only one can reload.** The implementation -- `tools/`,
`backends/`, the pure modules they use -- can be re-imported in-process.
State and the types it is made of -- `session`, `policy`, `consent`,
`model`, the ledger and sensitivity records -- must not be: a new class for
an old instance is a bug waiting, and every reloaded module re-importing
the *same* stable modules is what keeps `isinstance` and enum comparisons
true across generations. The tool list and schemas are the host's cache
from `initialize`; a new tool or parameter needs a reconnect, and no
process-side trick changes that.

**The mechanism.** With `GHOSTDRIVER_DEV` set, the server's tool closures
call through a `LiveToolbox` that resolves the current toolbox on every
call. A reloader stats the package's files (throttled to four times a
second) and, on a change to a reloadable module, purges every reloadable
module from `sys.modules` and imports `ghostdriver.tools` again -- whole,
not file by file, because a `from x import y` elsewhere keeps the old `y`
otherwise. The new toolbox is built on the same `SessionManager`, and its
live state (`_desktops`, `_watches`, `_tree_cache`, the trace) is carried
from the old instance, so an isolated session's desktop thread and a
minimized-watch keep running. Retired modules are kept referenced, never
released: the notice's window class points at a callback the old module
owns, and freeing it would leave the class pointing at nothing (the notice
now also reuses a class an earlier generation registered). An edit that
does not import -- a typo, a mid-save -- leaves the previous generation in
place and says so. Every result after an event carries `dev_reload`: what
changed, what reloaded, what needs a reconnect, or what failed and which
generation was kept. Outside dev mode the proxy is a pass-through.

**What it costs, and where it stops.** A stat sweep per call in dev mode
only; a re-import of some sixty modules on change, a few hundred
milliseconds; leaked generations, in development. Edits to the stable
modules or to the server file are reported as needing a reconnect, which
in Claude Code is `/mcp` on this server rather than a relaunch. Proven on
a scratch package: an edit takes effect on the next check, state is
carried, a syntax error keeps the old generation and restores
`sys.modules`, a stable-module edit reloads nothing and asks for a
reconnect.

### D69. The round-3 addendum: the effect arrives later than the action

**Context.** The same session, after D67 and the hot reload. It confirmed
the earlier fixes -- `hit_targets` settled in one call what an hour of
theorising had not (the toggle bars are painted, not windowed), and the
lost-session message was called the standard every error should meet --
and brought three things the tool did not yet say.

**A child listed outside its container.** `hit_targets` returned a
toolbar at y 768-802 inside a container whose rectangle ends at 626: a
child clipped away or scrolled out of view, listed as though a click could
reach it. Such a child is now flagged `outside_container`, counted in the
result, and a container whose only children are outside is reported as
having no *reachable* ones.

**The focus note sent the caller to a no-op.** It said "a step for a
person: await_human", and `await_human` without a condition was then the
no-op D67 fixed. The session found, with a separate tool that does
activate windows, that the same coordinates worked at once. That is the
intended division of labour, and the note now says so: this tool never
activates a window; a control that insists on one is a step for a person
(with `until_change` when what will appear cannot be named) or for a tool
that activates windows, given the coordinates this tool found. The
`activate` opt-in stays unbuilt for D67's reason.

**"The action completed" and "the screen shows the result" are seconds
apart on this target, and nothing marked the gap.** A grid showed one row
four seconds after the click and four at eight; the one-row state was
reported as a finding, and was wrong. Instruction blocks render empty and
fill later; `hit_targets` on them returned nothing while they rendered.
The tell is the target's own busy indicator -- a pair of progress bars in
its status strip. This tool cannot know a target's indicator; a profile
can name it. `busy_indicator` in the profile is either a locator present
while busy or a region that renders ink while busy (`ink_fraction`, D66,
above a threshold). Every actuation result then carries `still_arriving`
with a hint when the indicator shows, and `wait_idle` waits for it to
clear -- one call, not a guessed sleep -- and is refused with
instructions when the profile names none. Proven on the fixture with a
"working" label shown for a while after each click, in both forms.

**Measured on the primary target, read-only.** Its status strip is one
control with no child windows -- the progress bars are painted -- and its
idle rendering is three-quarters ink, so the indicator for that target is
a *sub-region* of the strip with a threshold set from an idle-versus-busy
pair of captures, which needs a busy state to measure and belongs in the
operator's profile, not here. Where those bars sit is target knowledge;
the mechanism that waits on them is the tool's.

### D70. The clipboard is the person's

**Context.** The operator, watching the tool work while doing other
things: it messes with the clipboard, and that is disruptive. It did, in
two places. The whole-value rung of `set_text` (D63) put the value on the
clipboard and pasted it; the grid copy route (`probe_grid`, `grid_seek`)
asks the target to Copy, which writes the clipboard, and put the prior
*text* back -- an image, a file list, a rich-text selection were gone,
and a copy the person made in the gap was lost either way. The tests
wrote it too, several times per quick gate, on the machine the operator
was working at.

**Setting text no longer touches the clipboard at all.** The paste
without the clipboard is `EM_REPLACESEL`: an edit control inserts a
string at its selection exactly as it would a paste, through its own
edit path, and it is one of the few messages whose string the system
marshals across processes. Select-all, then replace-selection, one
message, the value whole -- what the rung was for -- and the clipboard's
sequence number does not move. The rung is named `inserted` now. One
measurement after the fact: the select-all must be *sent* before the
replace is sent, not posted -- a posted select-all can be processed after
a sent replace, which then inserts at the caret and appends; it showed
up under load as `INSERTED-0001plain text` once in a dozen runs. The
`paste` editing action in `send_keys` stays: it pastes what the person
has, and writes nothing.

**The one route that must write it is opt-in per session, and puts
everything back.** A target's Copy command is the clipboard by
definition; there is no other way to run it. So it runs only in a
session attached with `clipboard=true` -- an operator's choice, made
knowing what it means -- and around each copy every clipboard format is
snapshotted (`EnumClipboardFormats`, each global block's bytes) and
restored, not the text alone. Formats that are not global memory (a
bitmap, a metafile) cannot be copied from here and are named as lost.
Without the flag, `probe_grid` skips the route and says why, and
`grid_seek` is refused with the same words. `read_clipboard` reads and
writes nothing; it stays as it was.

**The tests.** Those that write the clipboard carry a `clipboard` marker,
are excluded from the quick gate, and snapshot-and-restore around
themselves. The whole-value rung's test proves the sequence number did
not move, which is stronger than any restore.

### D71. The watches follow the process tree

**Context.** R5 made consent and sessions cover a process tree and left
two watchers behind: the minimized-session watchdog and the workflow
interference watch both sampled the target pid alone. A file dialog in a
browser's helper process coming on screen under the minimized strategy
was not an escape the watchdog saw, and a helper taking the foreground
was not an interference event.

**What changed.** Each watch takes an optional `family` callable that
returns the target and its descendants, asked on every poll, so a helper
that appears later is watched too; the session's cached tree (0.5 s)
supplies it for the watchdog, the backend's `descendants` for the
workflow runner. The watchdog samples every member's top-level windows
and treats a foreground window of any member as the target holding the
front; when the window it photographs belongs to a helper, it puts that
window away itself, since minimizing the parent's main window hides an
owned modal but not another process's window. The interference watch
reports which pid took the foreground and says when it was a process the
target spawned. A snapshot that fails on one poll falls back to the
target alone for that poll. Proven on the fixture: a child-process
window shown on screen under a minimized session is caught, photographed
and put away, and a fed sequence proves the interference watch's family
logic without disturbing a desktop.

**The open items above, revisited.** "Nothing gives exact text out of an
owner-drawn region" is closed as written: `probe_grid` probes the routes
it named, `grid_seek` reads a grid through its own Copy, and
`read_clipboard` reads that copy back (D63, D65, D70). The denylist item
is half closed: an element identity -- a toolbar button by position, a
tab by name -- can be denied since D57; a grid cell still cannot, because
nothing names one.

### D72. A denylist entry can be a place

**Context.** The oldest open item: the denylist matched captions, then
identities (D57), and still could not forbid the controls a person would
most want to -- a grid cell, a row in an owner-drawn list, a painted
button on a toolbar. They have no caption and no identity. What they have
is a place: a rectangle inside a window the profile can name.

**What changed.** A denylist entry may be `{"within": <locator>,
"region": {left, top, right, bottom}, "note"?}`, the rectangle in the
client coordinates of the window the locator names -- the same frame
`at` uses and a capture of that window shows, so an operator reads the
numbers off a capture and writes them down. Every actuation computes
where it will land on screen -- the aimed point, or the control's centre
-- resolves each region's window now, and refuses if the aim falls
inside, naming the note. A malformed entry fails the profile load rather
than silently protecting nothing. Proven on the fixture: a click into the
grid's denied row is refused and a click into the row above it is not; a
`set_value` on a field whose centre lies in a denied region is refused.

**What it does not do.** The region is a rectangle in one window's
frame; a control that scrolls within it is not tracked. That is the
nature of a place; a control that can be named is still better denied
by name.

### D73. Bringing a window forward, on request; and three frame/telemetry fixes

**Context.** A session driving System Manager produced the controlled
experiment the earlier reports could not: three posted clicks across a
fifteen-pixel spread on a Delphi `TSpeedButton` toolbar all returned
`ok`/`delivery_only` and did nothing; one real click at the same point
fired it. A VCL graphic control has no window, and the parent panel
dispatches its clicks from *real* input, not a posted message. Delivery
to that panel is honest and useless. Real input needs the window
frontmost, and the tool had no way to bring it there -- which cost two
hand-offs to the operator, one of them a stray second instance from
computer-use's open_application.

**`foreground`.** The deliberate pair to `isolation=minimized`: one keeps
the target out of the way, this brings it forward. Asked for across three
reports, each time with the operator accepting that it interrupts them, so
it is built -- but never automatic and never a side effect. It attaches
this thread's input queue to the current foreground thread for the length
of one SetForegroundWindow (the dance D64 refused for a *click*, because
it moves the keyboard focus the operator types into) and detaches
immediately. Interactive tier. It reports `took_foreground`: a background
process's SetForegroundWindow can be refused by Windows, and `false` is
that refusal said plainly. The click itself still belongs to a tool that
uses real input; this only makes that possible without a manual raise.
Not built: real input inside this server. Posting is what keeps it
background-safe everywhere else, and one deliberate raise plus the
existing division of labour covers the case.

**Three smaller things from the same report.** `find` and `capture` carry
`physical_rect` beside `rect` when the display is scaled -- logical times
the display scale -- so a coordinate maps into a DPI-aware screenshot
tool's frame with one known quantity instead of a guess. `modals` returns
each dialog's whole text, read from its child controls top to bottom, so
the exception below a scrollable pane's fold arrives in one call rather
than being guessed from the visible summary. And `dev_reload` no longer
rides on an operator's result unless it is actionable (a reconnect is
needed, an edit failed, a reload was held); a routine reload stays in the
log. `grant_targets` reports counts and what it changed, not the whole
standing pid list on every call.

**Still not addressed, deliberately.** A posted click on a windowless
graphic control cannot be told apart from one on an owner-drawn grid that
*does* act on posted clicks -- both are `delivered_to` the container. So
the click still cannot return `no_target_control`; what it can do is what
it does -- name the window it reached, and let `expect` prove the effect
or its absence. When `expect` shows nothing happened, `foreground` plus a
real-input tool is the route, and the focus note says so (D69).

### D74. The suite could not run on Linux, and the rule that says so is a test

**Context.** With the backlog written up as issues, the Linux backend
(D59) became startable work rather than a plan, and the first thing a
Linux implementer does is run the tests. On this repository, on Linux,
`pytest` did not run at all: `Interrupted: 4 errors during collection`.

**What was wrong.** `pytestmark = on_windows` gates the *tests* in a
module. It does not stop the *module* from running. Three test modules
bound `ctypes.WinDLL` at module scope and a fourth imported
`backends.windows.interference`, which binds it for you; each raises
`AttributeError` on import. A binding that raises during collection is
not a skip -- it aborts the whole run, so roughly 470 tests with nothing
to do with Windows never ran either.

**The rule was already the practice.** `conftest` keeps its Win32 in
strings executed only in the Windows subprocess, with a comment saying
why; `tests/test_windows_actuate.py` calls `WinDLL` inside its functions
and defers its backend imports the same way. So the idiom existed, was
understood, and was written down -- in two comments, one of which names
the wrong exception (`OSError`; it is `AttributeError`). Nothing failed
when four modules did it the other way, which is D60's lesson arriving a
second time: a promise that lives only in prose is one a later change
breaks without noticing.

**The decision.** The rule is a test --
`test_no_test_module_binds_a_platform_at_import_time` -- and it is stated
per *platform*, not per symptom: a module-scope `ctypes.WinDLL`, a
`ctypes.windll`, or an import of any `ghostdriver.backends.*` subpackage.
Stated that way it is symmetric, so the Linux backend cannot do the
mirror image of this to Windows when it lands.

**And the copies went.** Six modules each held their own
`ctypes.WinDLL("user32", use_last_error=True)`. That is six chances for
the seventh to be written the other way, so they now share one lazy
`conftest.user32()` and the copies are deleted rather than left to drift.

**What the measurement showed.** Linux went from "cannot collect" to 896
collected, 473 passed, 422 skipped, 0 errors. Two tests turned out to
need Windows and never to have said so: a consent-store case whose whole
premise is that a read-only *file* is undeletable -- true on Windows,
false on POSIX, where deletion is a permission on the *directory* -- and
a watch test reaching `InterferenceWatch`'s real Win32 defaults. The
`[server]` extra is pinned to `mcp` 2.x while `importorskip` accepted any
version, so a 1.x install answered the import and then failed fourteen
tests on an inner path; it checks `minversion` now.

**The 45% that skips is the more important number.** A Linux run reports
no failures having verified less than half the suite and nothing of the
backend. That is why the environment is now part of an issue rather than
folklore, and why `CLAUDE.md` states it: neither platform can confirm the
other, and "no failures" means "no failures among the tests that ran".

**Not verified on Windows.** Recorded as done on one platform only.

### D75. The Linux fixture stands up, and two of the model's assumptions do not

**Context.** With the suite collecting on Linux (D74), L0 -- the GTK fixture
-- became workable. `docs/LINUX.md` specifies its shapes; this records what
building it measured, because the document says plainly that it "was written
on a machine with no Linux desktop" and nothing in it had been run.

**GTK 4, not GTK 3.** PyGObject here offers `Gtk 4.0` and no `Gtk 3.0`. That
costs one shape: GTK4 removed `Gtk.Toolbar`, so the icon-only toolbar is a
box of icon-only buttons. For D56's purposes -- a row of controls that are
not windows and carry no caption of their own -- it is the same thing.
Measured against GTK 4.14.5.

**`present()` is avoidable, and that matters.** The fixture must never take
the foreground incidentally (`gtk_window_present` is what a foreground grab
*is*). In GTK4, `set_visible(True)` maps a window without raising or
focusing it, and the mapped window still has a real X id. So the grab exists
only behind `--present-after`, and L6 can measure a real one instead of
assuming.

**First contradiction: a bare Xvfb has no EWMH.** `docs/LINUX.md` maps
`top_level_windows` to "`_NET_CLIENT_LIST` + `_NET_WM_PID`" and asks L6 to
read `_NET_ACTIVE_WINDOW` before and after every action. On `Xvfb :99` with
no window manager running, **neither root property exists** -- the root
carries `_XKB_RULES_NAMES` and nothing else. Both are set by a *window
manager*, not by the X server. What does work is a tree walk (`XQueryTree`,
which is what `xwininfo -root -children` does) plus `_NET_WM_PID`, which the
application sets on its own window.

Consequences, none of them fatal but all of them planning:
`top_level_windows` on the nested display has to walk the tree rather than
read `_NET_CLIENT_LIST`; L6's foreground assertion is meaningless *on the
nested display* (it stays meaningful on the operator's, which has a WM); and
L7 -- "does the window manager focus an un-hidden window" -- cannot be asked
at all without a window manager to ask. **L1 therefore needs a WM on the
nested display, which the measurement as written does not mention.** None is
installed on this machine.

**Second contradiction, and the bigger one: sent events do not drive an
unfocused window.** L4 is named as the measurement that decides "whether the
Windows ladder maps to Linux at all". Taken early, because the fixture made
it cheap:

| What was sent | State | Acted? |
|---|---|---|
| `XSendEvent` key `ctrl+c` to the window | target **has** input focus | **yes** |
| `XSendEvent` key `ctrl+c` to window B | window **A** has focus | **no** |
| `XSendEvent` `ButtonPress`/`Release` to the window | pointer parked elsewhere | **no** |
| `XTest` click, real pointer on the control | -- | **yes** |

The first row looks like a success and is not one: the target already held
focus, so `XTest` would have done it too. It adds nothing a tier 4 could not
do. Read together, GTK4 routes input by the *real* input state -- keyboard by
input focus, pointer by pointer position -- and discards a sent event that
does not match it.

**So tier 3 does not exist on Linux/GTK4**, and the ladder is tier 1 then
tier 4-under-isolation. Tier 4 is excluded by default (D9) and is acceptable
only where the input being taken is not the operator's -- which makes the
nested X server **mandatory rather than preferred**, where `docs/LINUX.md`
had it as the simpler of two options. It also promotes MPX from "measure it
after the nested server works" to the only route that could ever drive a
target on the operator's own display.

**What this measurement is not.** GTK 4.14.5 only; Qt is untested and GTK3
is unavailable here. No window manager was running, which changes focus
semantics, so the keyboard rows deserve a re-run once L1 has one. The sends
were made with `xdotool` 3.20160805.1; a hand-rolled `XSendEvent` with
different propagation could behave differently, and that is worth one
attempt before this is treated as settled. Recorded now because it changes
what L1 has to build, and finding that out after building it would be worse.

**One thing that worked exactly as hoped.** `Ctrl+C` on the owner-drawn grid
put its exact rows on the clipboard, read back with `xclip`. That is the
Linux half of the route issue #1 is opening on Windows, and it is the first
evidence anywhere in this project that a copy route gives exact text out of a
control that has no children to read.

### D76. The six validation gates, run against a real Profile L1 target

**Context.** `docs/VALIDATION.md` is a six-gate, read-only runbook, and
D60 scored real-target testing "thin" because no part of it had been run
against a real application -- "the row keeps its score." It was run, in an
operator session, against a live Delphi/VCL x86 target (Profile L1). All
six gates were exercised. Five pass cleanly; one carries a finding that
qualifies a claim the whole classification rests on.

**Gate 1 -- discovery. Pass.** Two Delphi/VCL x86 targets appear, 94 and 91
top-level windows. One was probed for the rest.

**Gate 2 -- profile correctness. Pass on the classification, with one
significant finding.** `matched_profile` is `L1`; `toolkit.inferred` is
`delphi-vcl` (confidence `medium`, evidence a set of `TAdv*` window
classes); `executable.bitness` is `x86` under WOW64; `dpi.awareness` is
`unaware`; `msaa.verdict` is `identification-only` (11 of 40 sampled
controls named, none with a default action); `window_count` 108;
`unresponsive_count` 0; `class_census` is all VCL classes. None of the
runbook's fail conditions is met.

The finding is `uia.verdict = "partial"` and
`uia.control_view.with_patterns = 25` -- where the runbook's Gate 2 table
says, for a target expected to have no UIA provider, "exactly `0` ... any
non-zero value means the target exposes real automation patterns and is
not the profile you assumed -- stop and re-read the tree." Re-read, the 25
resolve entirely onto *standard* Win32 controls: `SelectionItem` on the 21
`TabItem`s, `Value` on the 3 `Edit`s, `Selection` on the one `Tab`. Every
one of the 72 `Pane`-classed controls -- the application's own vendor-drawn
buttons, panels and grids -- carries no pattern at all.

So the patterns are the OS's generic HWND-to-UIA provider doing its job
for standard controls, not evidence of an accessibility implementation by
the application. The classifier concluded `L1` correctly, on the low
`richness` (0.2577) and the pattern-less vendor controls, not fooled by
the synthesized patterns on the standard ones. What is wrong is the
model's blanket phrasing -- "no element anywhere supports any pattern" --
and the runbook's "`with_patterns` must be exactly `0`." The true
statement is narrower and is the one the actuation ladder already relies
on (D56): a standard tab control's `SelectionItem` is present but inert
for the application, so a posted click drives the page and the pattern
does not; pattern-*emptiness* is a property of the vendor-drawn controls,
never of the whole tree. A Profile L1 target with any standard tab or edit
control will show a non-zero `with_patterns`, and that is not a
contradiction of L1. `docs/VALIDATION.md` is corrected to say so.

**Gate 3 -- scale. Pass, on a small instance.** The whole tree at depth 12
is 82 nodes / 112 lines; runs of same-class siblings collapse to
`[N x Class]`; `--max-nodes 60` ends with an explicit truncation line;
suggested `class=... text="..."` locators are usable. But this instance is
one loaded editor view -- 108 windows -- not the ~1,100-window whole
application the gate imagines, so the summarizer's scale limits were not
stressed. `describe` behaves and is bounded; the scalability question
itself remains open against a full-size target.

**Gate 4 -- locator correctness and ancestor scoping. Pass.** A plain
`class=` find returns exactly one, fully populated. A repeated caption
matched six controls of one toolbar class; `within=(class=<frame>)`
narrowed it to exactly one handle, a different ancestor selected a
different subset, and an impossible nested `within` chain returned nothing
rather than over-matching. The runbook's ideal test -- the same caption on
two *tab pages* -- was not available, because only one page was loaded;
the ancestor-scoping capability it is meant to prove was proven on the
repeated toolbar caption instead.

**Gate 5 -- text reading. Pass, with the branch that matters still
unexercised.** Standard edit controls returned their real values; a combo
edit answered with a genuine empty string (answered, not silent). Every
control answered -- `unresponsive_count` was 0 and nothing reported
`<no answer>` -- so the `responsive=False` path the runbook flags as
never having run anywhere *still has not run*. Confirming it needs a target
with a control that does not answer, which this session did not have.

**Gate 6 -- non-interference. Pass.** Across the whole exercise, including
a 60-control read batch, the foreground window did not change, the target
never became foreground, and the cursor did not move.

**What this moves.** Real-target testing is no longer unrun: the
read-only diagnosis half of the tool -- discovery, classification, scale,
locator and ancestor scoping, text reading, non-interference -- is
confirmed against a real Profile L1 target, and the one surprise it turned
up is written down here rather than smoothed over. The row moves from
"thin -- nothing has run" to "diagnosis verified on a real target; the
finding recorded." What has still not run is the *actuation* half: no
workflow has driven a control end to end against the real application
under the interference watch (D57, D62). That remains the operator's, and
the scorecard keeps that part of the row open.


### D77. A click can name the surface changing; and the inactive warning yields to evidence

**Context.** A session driving an owner-drawn Delphi/VCL screen hit the
gap the earlier reports circled: two controls -- a Toggle Block Edit bar
(owner-drawn panel) and a hypertext caret box -- took a posted click as
`delivered` and did nothing, and there was no way to say so. The
`expect`/`require_active` machinery did not help, for a reason worth
stating: the click's effect was a palette docking several seconds later,
with no control whose presence could be named as the postcondition. A
real OS click worked first try; five round trips were spent before
switching.

**A whole-surface postcondition.** `expect={"changed": true}` verifies
against the surface shape digest (the one `surfaces` already computes) rather than a named control: the baseline is taken before the
action, and the postcondition holds when the shape moves -- a class
appearing that was not there, an engine waking, a pane docking. Because
that effect can lag the click, `changed` gets a longer verify window than
a named control does (its `timeout_s`, six seconds by default, against
the standard two). It is deliberately blind to position and count (as that digest is): a palette of a *new* class moves it; a row highlight or a status
caption does not -- which is exactly the honest split the report wanted,
"delivered and something changed" from "delivered and nothing did". It
does not make a windowless control that ignores posted clicks suddenly
work; it makes the tool able to *say* it did nothing, so a caller stops
guessing and reaches for `foreground` and a real-input tool (D73).

**The inactive warning yields to evidence.** A click into a window that
is not its thread's active one carried a `delivered_inactive` warning
(D67). It fired even when the click visibly closed a dialog -- the very
result whose own `disturbances` list showed the window gone. The warning
is now suppressed when the click's disturbances show a window appearing
or vanishing: that is the click plainly having acted, and the caveat
"a focus-checking control may have ignored this" is then noise.

**Not changed.** The picker-race trap (a common-dialog whose `expect`
can report failure while `focus` shows it open) is a matter of naming
`all_windows` and the two-second window, not a defect; and the black
`capture` of a Chromium window remains -- its accessible surface, not
its pixels, is the way in, and that is a measurement for the next
session, not a line of code.

> **A note on numbering.** Decisions D1-D77 are numbered sequentially and
> are frozen -- several hundred references across the source tree point at
> them. From here on a decision is numbered by the **issue** it came out of:
> `D#8` is the decision that came out of issue 8. Issue numbers are handed
> out once by GitHub, so two people working at the same time cannot pick the
> same one, which a hand-kept counter could not manage -- it collided three
> times in a day. Numbers therefore skip and arrive out of order, and that is
> expected. If a decision has no issue, open one for it first.

### D#8. L1 stands up, and the isolation needs a session bus of its own

*(Numbered from its issue rather than from a counter, and this entry is why.
It was D76, then D77, then D78: three times, two machines branched from the
same `main`, read the same highest number, and both were right. A shared
counter that every branch reads before any branch writes cannot be made
safe by care. An issue number is handed out by GitHub once, so the question
does not arise.)*

**Correcting D75 first.** D75 said no window manager was installed and that
`at-spi-bus-launcher` and the AT-SPI bindings were missing. All three were
wrong, and wrong the same way: each was checked with `command -v` or an
`import`, and absence from `PATH` was read as absence from the machine. The
operator runs GNOME Shell on `:0` with full EWMH; `at-spi-bus-launcher` is at
`/usr/libexec/`, off `PATH` by design; and the bindings are `Atspi 2.0`
through GObject introspection, which is a third route `docs/LINUX.md` did not
list beside "pyatspi (or raw D-Bus)". Nothing had to be installed. The lesson
is the cheap one: ask the system what it has, do not ask `PATH` whether it
has the names you thought of.

**The fourth piece.** `docs/LINUX.md` measurement 1 names three: `Xvfb`,
`at-spi-bus-launcher`, and something to list the tree. It needs a fourth, and
the fourth is what makes the strategy an isolation strategy rather than a
convenience: **its own D-Bus session bus.** AT-SPI is discovered *through*
the session bus, so a nested display that shares the operator's bus finds the
operator's accessibility bus and enumerates the operator's applications.
`dbus-run-session` keeps them apart.

This was found the honest way: `gnome-shell` refused to start on the nested
display with "org.gnome.Shell already exists on bus and --replace not
specified" -- a singleton on the *session* bus, not a display conflict.

**The guarantee is now asserted, not assumed.** With the operator running a
full desktop on `:0`, the nested bus reports **one** desktop child: the
fixture. `test_the_nested_bus_sees_only_the_fixture` fails if any of the
operator's applications ever appear, which is the check that makes
`HiddenDesktop` mean something on Linux.

**What the tree showed.**

* A `WindowNode` on Linux is an AT-SPI **frame** carrying the window title,
  not an X window. Only toplevels have X ids; controls are accessibles.
* The application node reported `Unnamed` until the fixture called
  `GLib.set_prgname`. An unnamed application node leaves a locator nothing to
  match the *application* on -- the counterpart of the process/main-window
  pairing D3 does on Windows -- so a real target that does not set it will
  have to be matched by pid alone.
* **An owner-drawn control is invisible to a locator by default.** A
  `Gtk.DrawingArea` comes back as a generic `panel` with an empty name, and
  an accessible *label* alone does not change that: it took an accessible
  *role* before the drawn button and the grid appeared as `push button` and
  `table`. So on Linux the D56 problem is sharper than on Windows, where a
  window class is always there to match: a control that declares no role is
  not merely hard to name, it is indistinguishable from layout.
* The grid is one `table` node with **zero children** while painting three
  rows. That asymmetry is D50 exactly, and it is why the copy route matters.
* All three entries -- plain, bound, and password -- report role `text`. The
  password one is not a distinct role, so `is_protected` cannot be answered
  from the role and must read `STATE_PROTECTED` (D33's constraint 4, D37,
  D38). Confirming that state is L2's job.
  **Wrong, corrected by D#34a: there is no `STATE_PROTECTED`.** AT-SPI's
  `StateType` has 45 members and none of them names one. The sentence was
  written from the Windows model rather than from a measurement, which is
  the mistake this document exists to prevent.

**Cost.** The nested stack takes several seconds to stand up, so the L1 tests
share one and are marked slow.

### D#34a. AT-SPI gives out the password, and hides which field is one

**Context.** L2 asks which controls answer `Text` and which only `Name`
(`docs/LINUX.md` measurement 2). The answer is dull -- entries answer
`Text`, buttons do not -- and on the way to it two things turned up that
are not about reading at all. Measured against GTK 4.14.5.

**First: there is no `PROTECTED` state.** D#8 said `is_protected` would have
to read `STATE_PROTECTED`. It cannot: AT-SPI's `StateType` has 45 members
and none of them is one. That sentence was written from the Windows model
(`EM_GETPASSWORDCHAR`, D33 constraint 4) rather than from a measurement.
Corrected in place there.

**Second: one of the two ways to make a password field is invisible.**

| Widget | role | states | interfaces |
|---|---|---|---|
| `Gtk.Entry` | `text` | EDITABLE, FOCUSABLE, SENSITIVE, SHOWING, VISIBLE | Accessible, Action, EditableText, Text |
| `Gtk.Entry` + `set_visibility(False)` | `text` | *identical* | *identical* |
| `Gtk.PasswordEntry` | `password text` | *identical* | *identical* |

The dedicated widget carries a distinct **role**, and that is the only
signal there is. An ordinary entry told not to show its characters is
indistinguishable from one that does -- same role, same states, same
interfaces. So a Linux `is_protected` built on the role will be right about
`Gtk.PasswordEntry` and wrong about the other, and the other is the older
and commoner idiom.

**Third, and worse: both hand out the secret.**

```
password entry   role=text           get_text() -> 'hunter2'
password widget  role=password text  get_text() -> 'hunter3'
```

The screen shows bullets; the bus returns the value. `Atspi.Text.get_text`
does not redact, for either widget.

**Why this matters more than it would on Windows.** D37 says a password
field is protected rather than unresponsive, and D38 that nothing types into
a field that hides its contents. Both were built on `EM_GETPASSWORDCHAR`,
which answers the question honestly, and on a read path that never had the
value to leak in the first place. On Linux the toolkit enforces neither: a
`read` that passed the `Text` interface through would put a real password
into a tool result, into the per-call trace the operator directory keeps
(D62), and into a model's context.

**So the driver has to enforce what the toolkit does not**, and it cannot
do it reliably, because the signal is missing for the commonest case. The
honest options, none of them free:

1. **Refuse `Text` on anything with role `password text`,** and accept that
   `Gtk.Entry(visibility=False)` slips through. Catches the widget a
   modern application uses; misses the older idiom.
2. **Never return `Text` from an editable single-line entry at all** unless
   the caller has said it wants values. Safe and blunt: it takes ordinary
   form-filling verification with it, which is most of what `read` is for.
3. **Ask X, not AT-SPI.** GTK sets an input-purpose on password entries; if
   that is visible over the bus as an attribute it would be a second signal.
   `get_attributes()` returned only `toolkit=GTK` on all three here, so on
   this evidence it is not -- but it was one measurement and worth a second.

Not decided here. It is recorded, pinned by tests that fail if GTK ever
changes either behaviour, and tracked, because choosing between those is a
policy decision and the Linux backend is not built yet.

**The tests assert the leak on purpose.** That is not approval. A test that
says "the password comes back in cleartext" is the thing that will fail
loudly on the day it stops being true, which is the day the driver can
stop working around it.

### D#9. AT-SPI will not bound a call, so the caller does

**Context.** L2 asks "what an unresponsive control does to a bus call (D4)
and what timeout is right". On Windows the OS answers it:
`SendMessageTimeout` with `SMTO_ABORTIFHUNG` returns `None` and the caller
moves on. The Linux question is worse in kind, and `docs/LINUX.md` says so:
AT-SPI is D-Bus, so an application that stops running its main loop stops
answering the *bus*, and a caller waits on the application rather than on one
control.

**`Atspi.set_timeout()` exists and does nothing.** Measured against the GTK
fixture hung for 15 seconds, reading one entry:

| timeout set | caller waited |
|---|---|
| default | 13.1s |
| `set_timeout(500, 15000)` | 12.6s |
| `set_timeout(2000, 15000)` | 14.1s |

All three blocked until the application came back. The variation is when the
read started relative to the hang, not the setting. An earlier 8-second hang
blocked for 8.0s and then *succeeded*, so the call is bounded by the
application's recovery and nothing else.

**So the deadline is the driver's.** `backends/linux/deadline.py` runs the
call on a worker and gives the caller back control on schedule. Measured, a
caller allowing 0.5s got control back in 0.5001s while the application stayed
hung for another fourteen seconds, and the read reported *did not answer*
rather than blocking.

**The number is 200ms, the same as Windows', and measured rather than
copied.** A healthy read over 200 samples: p50 0.19ms, p99 0.46ms, max
1.88ms; a 33-node tree walk 9.2ms end to end. 200ms is about a hundred times
the worst read seen -- room for a loaded machine, none for a hung one. Keeping
the Windows number means the contract reads identically on both platforms,
which is worth more than a Linux-specific figure with no better claim.

**The cost, stated rather than discovered.** The worker is *parked*, not
leaked: it is inside a C call, nothing here can cancel or safely kill it, and
it returns on its own when the application recovers -- observed at 13.08s for
a 15s hang. Reads issued against an application that stays hung park one
worker each until it comes back. The pool is bounded at eight and its threads
are daemons, so a wedged target cannot stop the process exiting; what it can
do is make the ninth concurrent read wait. Accepted: the alternative is
killing threads inside a foreign C stack.

**`None` still means did not answer.** Never *answered with nothing*. An
exception is re-raised rather than folded into a timeout, because a control
that answered with an error answered. Both are the distinction conftest calls
load-bearing, and collapsing them is how a caller silently asserts a field is
empty when it never replied.

**What this does not settle.** The number comes from one fixture on one idle
machine; a real target on a loaded desktop is the case that would move it,
and that is #27's territory rather than this one's. `deadline` is
deliberately free of `gi`, so its semantics are tested on any host and only
the hung-application case needs a desktop.

### D#34b. A Linux read withholds by class, because it cannot detect by field

**Context.** D#34a's measurement found that AT-SPI hands out a password
field's contents in cleartext, and that `Gtk.Entry(visibility=False)` is
indistinguishable from a plain entry. Three options were left open. This
settles them.

**Option 3 is dead, measured properly this time.** The earlier note dismissed
"find a second signal" on one reading of `get_attributes()`, which was not
good enough. Every surface an accessible exposes was diffed between a plain
entry and a hidden one: role, description, accessible id, attributes,
interfaces, the full 45-member state set, action count and names, relations,
default text attributes. **Thirteen surfaces, and the only differences are
the content itself** -- character count, text, and the offsets derived from
them. GTK's input-purpose is not on the bus. There is no signal.

`SINGLE_LINE` would have narrowed the affected class usefully, since a
password is never multi-line. GTK does not set it. Measured, not assumed --
the third assumption in this effort that a measurement killed.

**Why Windows never had to decide this.** Windows refuses a cross-process
`WM_GETTEXT` on a password field, so the value is not available to leak;
`is_protected` exists there only to tell "protected" from "hung", because
both come back empty-handed (D37). The platform is fail-closed and the driver
explains. On Linux the platform is fail-*open* and the driver has to be the
one that closes. That is the whole difference, and it is why the Windows
design does not port.

**The decision: withhold by class.** A secret is typed into an editable text
entry, so an editable text entry does not disclose its contents by default.

| what | verdict |
|---|---|
| role `password text` (`Gtk.PasswordEntry`) | **protected** -- never disclosed, opt-in cannot reach it |
| role `text` + `EDITABLE` | **withheld** -- not read at all unless the caller asks |
| labels, tables, tabs, buttons, captions | **allowed** -- read normally |

Option 1 (refuse on role alone) was rejected because it is a guard that
misses the commoner idiom while looking complete, which is worse than no
guard. Option 2 is what this is, narrowed: the blast radius is *editable text
entries*, not all text, so the reads `read` mostly exists for are untouched.

**The value is not fetched, not merely not returned.** A value that has been
read exists in this process and reaches a traceback, a log line or a debugger
without anyone deciding it should. `read` is not called for a withheld field.

**What makes the default affordable.** D29 has `set_value` check the display
after writing, and that needs a *comparison*, not a disclosure -- the driver
already knows what it typed. `confirms()` answers yes or no, so nothing
reaches a result, the operator directory's trace (D62), or a model's context.
A field that did not answer returns neither: that is the deadline expiring
(D#9), and reporting it as a mismatch would send a caller to fix a value that
may be correct.

**What this costs, stated plainly.** A caller that genuinely wants the text of
an editable field must ask, and the asking is what lands in the trace instead
of the secret. And a plain, non-secret entry is withheld alongside the
password one -- that is the finding rather than a defect, because a policy
that let the plain one through would let a hidden one through too.

**What it does not cover.** A vendor toolkit that gives its password entries
some role other than `password text` is in the withheld class, which is safe.
One that draws an entry as something not in `_TYPED_INTO` at all would read
normally, and that is the hole -- narrow, and worth re-measuring against the
first real Linux target rather than guessed at now. Qt is unmeasured
throughout.

### D#11. Tier 3 does not exist on GTK4/X11, confirmed under a window manager

**Context.** `docs/LINUX.md` names measurement 4 as the one that decides
"whether the Windows ladder maps to Linux at all". D75 answered it
provisionally and flagged two reasons not to trust the answer: no window
manager was running, and the sends came from one tool. This settles the first
and leaves the second stated.

**A window manager does run on the nested display.** D75 said none was
installed; D#8 corrected that to "installed but the nested one refused to
start". Both were wrong about the consequence. `gnome-shell --x11` runs on a
nested display perfectly well **under its own `dbus-run-session`** -- the
earlier refusal (`org.gnome.Shell already exists on bus`) was the shared
session bus, the same root cause as D#8's finding. With it running, `:83`
carries `_NET_SUPPORTING_WM_CHECK`, `_NET_ACTIVE_WINDOW` and
`_NET_CLIENT_LIST`. **That unblocks L6 and L7 (#13, #14)**, which D75 said
could not be asked at all.

**The measurement, with every experiment behind a passing control.**

| | control | result |
|---|---|---|
| `XTest` key, target focused | -- | **acted** (grid copied) |
| `XTest` click, pointer on the control | -- | **acted** (counter 0→1) |
| `XSendEvent` key, target **focused** | both above | **ignored** |
| `XSendEvent` key, target **unfocused** | both above | **ignored** |
| `XSendEvent` button, target focused, pointer away | both above | **ignored** |
| `XSendEvent` button, target unfocused, pointer away | both above | **ignored** |

**GTK 4.14.5 ignores a sent event in every configuration tested.** So tier 3
-- the rung that drives a chosen window without taking the operator's focus
or pointer -- does not exist here.

**This corrects D75 as well as confirming it.** D75 recorded one case that
*worked*: a sent key to a window that already held focus. Under a window
manager it does not, so that row was an artefact of a display with no
window manager and degenerate focus handling. The conclusion is unchanged and
now rests on cleaner evidence.

**What follows.** The ladder on Linux is tier 1, then tier 4 under isolation.
Tier 4 takes the real focus and pointer and is excluded by default (D9), so
it is only acceptable where the input being taken is not the operator's --
which makes the nested X server **mandatory rather than preferred**, where
`docs/LINUX.md` had it as the simpler of two options. MPX moves from "measure
it after the nested server works" to the only route that could drive a target
on the operator's own display, and is now worth its own measurement.

**On method, because this measurement lied three times before it told the
truth.** Three runs produced a confident negative from a harness that could
not have produced a positive: once with no window manager, once with the
pointer aimed at coordinates the window manager had moved the window away
from, and once with focus that silently never took. Each looked exactly like
a real result. The probe now runs its controls **first** and aborts if they
fail, and `tests/test_linux_tier3.py` skips rather than passes when they do,
because a green test that proved nothing is worse than a missing one.

**What is still not settled.** GTK 4.14.5 and GNOME Shell only. **Qt is
unmeasured**, and LINUX.md is right that "GTK ignores sent events" is a fact
about a configuration rather than about GTK. The sends came from `xdotool`
3.20160805.1; a hand-rolled `XSendEvent` with different propagation could
behave differently, and that remains the one cheap check nobody has done.

### D#13. The operator's foreground never moves, and what "put away" means on Linux

**Context.** L6 is the guarantee the project exists to provide, and
`docs/LINUX.md` asks for it the way the Windows suite does: read
`_NET_ACTIVE_WINDOW` on the operator's display before and after every action,
with the target on the nested one, and require it never to change. D75 said
this could not be asked, because a bare `Xvfb` has no such property. With a
window manager on the nested display (D#11) it can.

**Nothing this run launched ever became the operator's foreground.** The
operator was running a full GNOME session on `:0` throughout: the target was
focused, driven with a real click, iconified, left to grab its own foreground
on a timer, and put away again. At no point did a window belonging to a
process the run launched own `:0`'s active window. The isolation is
structural -- a different X server, not a policy -- and is now asserted
rather than assumed.

**Stated as attribution, not stillness, and that was a correction.** The
first version of this test asserted the operator's active window was the
*same handle* at every step. It passed alone and failed in a full suite run,
because the operator clicked something -- which is not a defect in anything.
The Windows focus guard had the framing right all along and this one now
matches it: what must never happen is that a window belonging to a process
this run launched becomes the foreground (`tests/test_zz_focus_guard.py`).
The operator's foreground may move freely; it may never move *to the
target*.

**The control comes first, and this is why.** "The foreground did not move"
is trivially true of a harness that did nothing at all, and an earlier run of
this measurement reported exactly that: a still foreground next to a drive
that had silently failed. The probe now proves it can drive the target before
any non-effect is allowed to mean anything, and the test skips rather than
passes when it cannot.

**Two things the Windows model got right for the wrong reason here.**

*What iconified looks like.* On Windows, minimized is a window state you ask
about directly. Under a compositing window manager an iconified window is
still `IsViewable` -- `Map State` does not move at all. `_NET_WM_STATE_HIDDEN`
is the signal, and code that asks the Windows question gets the wrong answer
confidently.

*Whether a hidden window can still be captured.* This is what makes the
minimized strategy possible: on Windows, `PrintWindow` asks the window to
render itself, so a minimized target still yields a picture (D49, D55). X11
has no equivalent call, and an unmapped window's contents are not guaranteed
to survive. Measured: under the compositor they do, and not merely
"non-empty" -- the iconified capture is *pixel-identical* to the mapped one,
1601 unique colours both, RMSE 0. Checked that way on purpose, because a
capture that succeeds and returns a blank buffer is worse than one that fails
(D66, and the black Chromium capture in D77).

**That is a property of the compositor, not of X11.** A non-compositing
window manager is expected to lose the contents, and is unmeasured. The
minimized strategy on Linux therefore carries a dependency the Windows one
does not, and it should be stated wherever the strategy is offered rather
than discovered by whoever runs it under something lighter.

**The watchdog has something real to watch.** The fixture calls `present()`
on a timer -- which is what a foreground grab *is* -- and it clears
`HIDDEN` and takes the nested foreground. Reproduced end to end: iconify,
grab, re-iconify, capture still good. D49's watchdog does not prevent the
flap; it makes it observable, and on Linux the thing to observe is
`_NET_WM_STATE_HIDDEN` going away.

**Unmeasured.** A non-compositing window manager, Wayland, and the soak that
spec §13 still lists as never having run.

### D#40a. Slice 1: the window tree, and what the contract assumed

**Context.** Every Linux decision so far measured something. This one builds:
six contract names -- `enumerate_process`, `top_level_windows`,
`direct_children`, `process_facts`, `descendants`, `parent_map` -- answer for
real, and `ghostdriver list-targets` lists a target on Linux.

**Why this went before the remaining measurements.** L3, L5, L7 and L8 are
still unmeasured, and the spec order says do them first. Slice 1 needs only
L1, and it answers a question no further measurement can: *are these
measurements sufficient to implement against?* The contract was written from
the Windows backend; if a name needs something AT-SPI cannot give, that is
much cheaper to find on the first slice than after four more measurements
taken on the assumption that it fits. It found two things.

**First: the contract returned a type no other backend could name.**
`ProcessFacts` was defined in `backends/windows/process.py`, which binds
Win32 at import, so the Linux backend could not import the shape it was
contracted to return. Nothing outside that module imported it -- the
platform-neutral layer duck-typed it -- which works exactly until a second
backend exists. Moved to `model/process.py` so both fill one definition
rather than each keeping a copy that drifts.

Its Windows-flavoured fields are kept rather than generalised, because
`probe/runner.py` writes every one into the profile and the profile is a
document an operator reads and diffs. Linux answers `wow64=False`,
`integrity_level=None`, `dpi_awareness="unknown"` -- the absence, not a
plausible reading. X11 scaling is a different model and mapping it would be
a guess dressed as a measurement.

**Second: `WindowNode` assumes Win32's three certainties**, and none of them
survives:

| Field | Win32 | Here |
|---|---|---|
| `handle` | every control has one | only toplevels have an X id, so handles are **minted** and kept in a registry that a new enumeration clears |
| `class_name` | a vendor class, often the decisive toolkit evidence (D47) | the AT-SPI **role name**, which is coarser: every button is `push button` |
| `text` | `WM_GETTEXT` | the accessible **name**, never the Text interface |

The minted handle is not a workaround: `WindowNode` already documents a
handle as opaque, backend-supplied and valid only for the enumeration that
produced it, because Win32 recycles them. Minting is a different way to be
unsafe to persist, and the contract already forbade persisting them.

That `text` is the name and not the contents is load-bearing. A tree walk
that returned contents would hand back every password on screen, which is
the bug D#34b exists to prevent, and a caller enumerating a window has not
asked to read anything.

**The coarser `class_name` has a cost worth naming.** D47 leaned on vendor
class names as toolkit evidence, and role names carry none of that. Linux
toolkit inference will have to come from the loaded objects instead --
`/proc/<pid>/maps`, which `process_facts` now reads -- rather than from the
tree. That is what `infer_toolkit` already prefers when modules are
readable, so the fallback is the primary here.

**Three guards fired on this change, all correctly.** The reachability guard
caught `tree` reached only through a dynamic import (fixed by importing it
plainly, which is safe because `tree` keeps `gi` inside its functions); the
unwired list shrank on its own, because `tree` now calls `deadline`; and
`test_linux_refuses_every_name` was *right until it wasn't* -- it encoded
"nothing is built", and now asserts the thing that stays true as the backend
fills in.

### D#10. Tier 1 works, cannot touch owner-drawn controls, and does not split

**Context.** L3 asks three things of the accessibility API: does it drive a
real button, does it fail on an owner-drawn one, and does writing a value
show D21's split. Two answers match the Windows expectation and the third
does not, which is the useful one.

| | expected | measured |
|---|---|---|
| `Action.DoAction` on a real `Gtk.Button` | acts | **acts** -- `actions=['click']`, returns true, and the application observably ran the handler |
| `Action.DoAction` on the custom-drawn `DrawingArea` | no action | **no action at all** -- `actions=[]`, the call raises |
| `EditableText.set_text_contents` on the bound entry | D21's split | **no split** |

**The owner-drawn negative is sharper than expected.** It is not that the
action fails; there is no Action interface behind the control at all. The
fixture gives that DrawingArea an accessible *role* (D#8), and a role turns
out not to imply an implementation -- it is nameable and not drivable. So
tier 1 cannot reach owner-drawn controls, which is what the rungs below
exist for, and on Linux the only rung below is tier 4 under isolation
(D#11).

**No split, and that is a real divergence.** On Windows, writing a value went
around the toolkit: the control displayed the new text while the binding
never heard of it, so the shown and committed values disagreed until
something forced a commit. That is D21, and it is why `WM_SETTEXT` was
deleted rather than kept as a fast path (D25).

`EditableText` goes *through* `GtkEditable`, so the widget's own `changed`
signal fires and a binding sees the write. **Tier 1 is stronger on Linux than
on Windows**, and the Windows reasoning for deleting the API-level write does
not carry over. Slice 4 should use it as the tier-1 write path rather than
inheriting the Windows conclusion.

**One detail worth pinning rather than discovering.** `set_text_contents`
clears and re-inserts, so `changed` fires **twice** and the first carries an
*empty* value the caller never wrote. Harmless against a mirror; not harmless
against a field that rejects empty, or one that fires a lookup per change. A
driver that writes values has to know the intermediate state exists.

**And a constraint for slice 4.** `Atspi.Component.grab_focus` does not work
-- it raises. Tier 4 is the only actuation rung that exists here and it needs
the target focused (D#11), so focus has to come from the window manager and
keyboard navigation, not from the accessibility API. Recorded now because
slice 4 would otherwise start by assuming the easy route exists.

**Unrelated finding, from the probe failing.** A `Gtk.Label`'s accessible name
is its *text*, and it overrides an explicitly set accessible label. So a label
cannot be given a stable name, and a locator matching one matches its
contents -- which change. Anything that needs to find a label reliably has to
match on something else.

### D#40b. Slice 2: reading, and the third state the contract has no room for

**Context.** Slice 2 wires `read_window_text`, `is_protected`,
`capture_window` and `CaptureError`. The policy was already decided --
withhold by class (D#34b), bound by a caller-side deadline (D#9) -- so this
was meant to be plumbing. It was not.

**`is_protected` stays narrow, and that is a decision.** It is tempting to
answer `True` for the whole withheld class: an editable entry might be a
password and nothing distinguishes them. It would be wrong, because
`is_protected` is *also* what refuses to type into a field (D38,
`tools/acting.py`). Widened, the driver could never type into any text field
at all, which is most of what it exists to do.

So the two questions are deliberately different: **the disclosure policy
governs reading, and the role governs typing.** A `Gtk.Entry` with hidden
characters is withheld but not protected -- undisclosed, still typeable --
and that is the only combination that keeps both properties.

**The contract has two states and the platform needs three.**
`read_window_text` returns `str | None`, and `None` means *did not answer*.
On Windows that is unambiguous: the OS refuses the read only for a password
field, so `is_protected` tells the two apart, which is exactly what D37 is
about.

Here `None` has three causes -- withheld, protected, and a real timeout --
and `is_protected` separates only the declared widget. **A healthy plain text
field therefore reads exactly like a hung one**, which is the confusion D37
was written to prevent, arriving from the other direction.

Not fixed in this slice, and not smuggled around. The fix is a disclosure
opt-in through the contract (`disclose=`, which D#34b's `read()` already
takes), and that changes a signature Windows shares, on a platform this work
cannot verify. Filed instead.

**Two smaller things the wiring settled.**

*A control with no `Text` interface answers with its caption.* Buttons do not
implement `Text`, and `WM_GETTEXT` answers such a window with its caption
rather than failing, so the accessible name is the honest equivalent and
keeps both platforms answering the same question. A control that implements
`Text` and raises anyway did not answer, and `None` says so.

*A capture is of a window, not a control.* Only toplevels have an X id (D#8),
so a handle anywhere in the tree captures its window and `region` crops. The
size is decoded from the PNG rather than reported from the request, because
a capture that returns bytes and no picture is the trap D66 names.

### D#14. Restoring a window and focusing it are one operation

**Context.** L7 asks whether the window manager focuses a window that has
been un-hidden. D55 said to assume it does until measured, and D4 permits
`restore` at `read_only` precisely because it is the operator's escape hatch
-- the one place a focus change is legitimate.

**The answer is stronger than the assumption.** Under GNOME Shell you cannot
un-hide a window *without* focusing it.

| route | what it asks for | hidden after | active after |
|---|---|---|---|
| `XMapWindow` (ICCCM de-iconify) | nothing else | **still hidden** | unchanged |
| `_NET_ACTIVE_WINDOW` (EWMH activate) | focus | **restored** | the restored window |

Both legitimate routes are covered: `_NET_WM_STATE_HIDDEN` is
window-manager-managed and a client may not set it, so a bare map and an
activation are the only two ways to ask. The map does nothing at all -- not
half a restore, nothing -- and activation restores and focuses in the same
motion.

**So restoring and focusing cannot be separated**, and D55's "assume it
focuses" turns out to understate it: there is no version that does not. That
is fine for `restore` itself, which exists to hand the window back and whose
whole point is that the person gets it. What it rules out is any code path
that wants a window *visible but not focused* -- on this window manager there
is not one, and anything designed around that possibility has to be
redesigned rather than configured.

**It also means D55's rule is load-bearing here in a way it is not on
Windows.** "Nothing ever un-minimizes" is a policy on Windows and a
*necessity* on Linux: an accidental un-hide is an accidental focus steal,
with no gentler failure available.

**Measured under GNOME Shell only.** A window manager with a different focus
policy -- one honouring focus-stealing prevention, say -- could plausibly
restore without raising, and that is unmeasured. The two routes tried are the
specified ones; a WM that answers a bare map differently would change this
answer.

### D#40c. Slice 5a: a second sampler, not a second policy

**Context.** Slice 5 is isolation and interference -- five contract names,
615 lines on Windows. The first instinct was that most of it was
platform-neutral and should be lifted out of the Windows backend, the way
`ProcessFacts` was in D#40a. That instinct was wrong, and the codebase said
so before any code moved.

`ghostdriver/isolation.py` describes itself as "pure policy. It is fed
observations and returns decisions; the sampling [is elsewhere]", and
`backends/windows/isolate.py` opens with "the policy in
`ghostdriver.isolation` decides; this samples". **The seam already existed
and was already in the right place.** So Linux supplies a second sampler
feeding the same `Watchdog`, and nothing was moved. Worth recording because
the wrong move -- hoisting a class that was already correctly placed --
would have looked like tidying.

**What is actually platform-specific is small**: what a sample *is*, and how
a window is put away.

| | Windows | here |
|---|---|---|
| on screen | a visible, non-minimized window of the family | a managed top-level the WM has not marked `_NET_WM_STATE_HIDDEN` (D#13) |
| put away | `minimize_no_activate` | a `WM_CHANGE_STATE` client message -- the call D#13 measured as non-activating |
| still there | `IsWindow` | the window answers `get_attributes` |

**A real X connection, not `xprop`.** The watch polls; a sample is several
round trips, and shelling out per poll would spawn two processes each time.
`python-xlib` is declared as a Linux dependency for the same reason
`pywin32` is declared for Windows -- the difference between a watchdog and a
fork bomb.

**The poll is slower here, deliberately.** 100ms against the Windows 20ms. A
sample costs X round trips rather than local calls, and the thing being
watched -- a window flapping into view -- has a human-visible duration.

**Putting a window away is safe; taking it back is not.** There is no quiet
un-hide (D#14), so the watchdog only ever iconifies. On Windows D55's
"nothing ever un-minimizes" is a policy; here it is the only thing available.

**One test had to be loosened, and the reason is a finding.** The fixture's
`present()` produces `unexpected_foreground` on some runs and
`unexpected_restore` on others, because GNOME Shell does not reliably grant
focus to a presenting window. Both are escapes; both are captured and put
back. The test asserts *an escape*, not which kind -- pinning the kind would
pin whether the window manager happened to grant focus that run, which is
neither stable nor this backend's decision. The policy that tells the two
apart is neutral and already tested.

**Not done in this slice.** `HiddenDesktop` and `OperatorNotice` are the
genuinely platform-shaped remainder -- a nested X server as a first-class
strategy, and a notice on the operator's own display -- and `InterferenceWatch`
needs a decision of its own: it is injectable by construction and its logic
is neutral, so it wants lifting rather than reimplementing, which touches
Windows.

### D#23. The type gate runs once per backend, because one run assumes one platform

**Context.** `test_mypy_finds_nothing` failed on Linux and passed on Windows,
on the same tree. `[tool.mypy]` set no `platform`, so mypy assumed the
**host**, and typeshed is conditional on it: on Linux `ctypes` correctly has
no `WinDLL`, no `oledll`, no `WINFUNCTYPE`, no `WinError`. Twenty errors
across eight files in `backends/windows`, none of them real.

A gate that gives two answers for one tree is not a gate. Worse, it gives the
*permissive* answer on the platform that has the backend, so the box that
could act on a finding is the one that never sees it.

**Rejected: `# type: ignore`.** `warn_unused_ignores = true` is set, so every
ignore added to satisfy Linux becomes an unused-ignore *error* on Windows. It
cannot be right on both hosts simultaneously -- which is the same shape as
the bug.

**Rejected: `platform = "win32"` globally.** Correct while `backends/linux`
was a stub and wrong the moment it was not: mypy would check the Linux
backend as though it were Windows. That is the original bug pointing the
other way, and it would have been introduced by the fix for it.

**The decision: one pass per backend, each naming its platform.** The shared
tree plus one backend, with that backend's `--platform`. The shared tree is
therefore checked under *every* platform, which is the property that matters
-- it is the part both backends read, and it has to be clean under either
assumption. Each backend is checked exactly once, under its own.

| pass | `--platform` | checks |
|---|---|---|
| windows | `win32` | shared tree + `backends/windows` -- 69 files |
| linux | `linux` | shared tree + `backends/linux` -- 56 files |

**`--exclude` alone does not work, and the reason is worth keeping.**
`--exclude` filters mypy's directory *crawl*; it does not stop mypy following
an `import`. `backends.load()` imports every backend, so the excluded one is
pulled into the build regardless -- excluding `backends/windows` on a
`--platform linux` pass still produced 24 of the same errors. What separates
them is `follow_imports = "silent"`: modules named on the command line are
always checked in full, so the shared tree still reports; a
followed-but-excluded backend is still *analysed*, so its types stay correct
for its callers, without its errors being attributed to the wrong platform.

That is a relaxation in name only. The gate names the whole of `src`, so
nothing outside a deliberately excluded backend is ever merely followed.

**A backend with no platform target is a test failure, not a silent gap.**
`test_every_backend_declares_a_platform` fails both ways: a package under
`backends/` with no entry in `BACKEND_PLATFORMS` would go unchecked by every
pass while the gate stayed green, and an entry naming a backend that is gone
is stale. This is the D74 failure mode again -- a green run that verified
less than it appears to -- so it is a test rather than a note. Both
directions were confirmed to fail before being relied on.

**mypy is now bounded at both ends: `>=2.1,<3`.** A floor alone let the
gate's verdict depend on who installed what and when; 2.x reports things 1.x
does not. The bound states what has actually been run. `ruff` and `pytest`
were considered and left with floors: their configuration pins the rule set
and the gate does not turn on their version the way it turns on mypy's.

**The `mcp` finding was environmental, and the pin was already right.** The
other 19 errors were `structured_content` / `mime_type` / `read_only_hint`
against an `mcp` **1.x** that a dev box had picked up from user site,
shadowing the `[server]` extra's existing `>=2.1,<3`. Nothing in
`pyproject.toml` needed changing; installing the pinned version cleared all
19. The *runtime* symptom of that mistake is already guarded by
`tests/test_mcp_dependency.py`, which is deliberately ungated (D#39's
anti-pattern). The type gate is not guarded against it, and that is accepted:
mypy's answer necessarily depends on the installed third-party surface.

**What is still host-sensitive, and cannot be fixed here.**
`ignore_missing_imports = true` means an *absent* package types as `Any`.
`pywin32`, `comtypes` and `pywinauto` install only on Windows; `gi` only on
Linux. So each host checks the other's third-party surface as `Any`. That is
inherent -- you cannot type-check against a package you cannot install -- and
it is narrower than the bug fixed here, which was about the *standard
library*.

**Verified on Linux only.** Both passes are clean on this box: 39 errors to
0. `env: both` is the label because the Windows host has to confirm the same
two passes give the same answer there before this is settled.

Evidence: issue #23; D74; `tests/test_quality.py`; `pyproject.toml`.

### D#60. A foreground window of the expected class verifies an `expect`

**The field report.** Driving a browser's file-picker,
`expect=class=#32770 visible=true` returned the *same* `postcondition_failed`
whether the picker opened or not. The picker is a new top-level in a helper
process; a bare-string `expect` resolves against the target's *main* window
only, and a helper-process top-level is not in that tree in either case, so
the postcondition carried no signal at all. The only thing that told success
from failure was the result's own `focus` block: `thread_active_window` was
`#32770` when it worked and `Chrome_WidgetWin_1` when it did not.

**What was measured.** The dialog does not merely exist; it opens *as the
foreground window*, and `GetForegroundWindow` reads that without touching
anything (the same no-activation discipline as the focus block, D64). So the
signal the report found by hand is available to the postcondition.

**The fix, and the two guards that keep it honest.** When an expectation is
purely "a window of this class is up" -- a class locator with no text,
`selected`, `index`, `handle` or `within`, none of which a class alone can
vouch for -- a foreground window whose class matches now counts as the
effect landing. Two guards, because a false green is the same defect as the
false red, pointed the other way:

- **Class must match** the expected locator (`fnmatchcase`, as the resolver
  matches it). "Any foreground change passes any expectation" would be the
  false-green mirror.
- **The window must belong to the target's own process tree**
  (`_tree_pids`), so an unrelated same-class dialog the operator happens to
  have focused -- another program's Open dialog -- is not read as this
  target acting.

A disturbance is still reported, not a verdict (D28): the foreground read
does not *fail* anything, it only lets a real effect be recognised. And
resolution is unchanged -- the corroboration is an added path, checked first
only because it is cheap (three window reads) where resolution enumerates a
tree.

**Not widened.** An expectation that names specific text or a selection
still needs the real element; the class of a foreground window cannot answer
for it, so those short-circuit nothing. And `timeout_s` remains honoured for
`changed` mode only; the locator path polls to the actuator's default window,
within which the corroboration is re-checked each iteration -- the "re-check
after a settle" the report also suggested, already there. *(issue #60)*

### D#51. `enabled` is a bit, not availability, and the contract now says so

**The field report.** `find` returned `enabled: true` for an owner-drawn
command button (a Delphi/VCL control) that rendered grey and did nothing.
The backend owner-draws that control and never sets `WS_DISABLED`, so
`enabled` -- which is `IsWindowEnabled` for a window node -- answered a
different question than the tester was asking. It is not "the user can use
this"; it is only "the `WS_DISABLED` bit is clear." Roughly a third of a
session's assertions read `enabled`, and on an owner-drawn control it is
silently wrong in the reassuring direction -- the opposite blind spot from
the modal case the `WindowNode` docstring already records, where a control
reports `enabled` while unreachable *through* a disabled ancestor.

**Three options, cheapest first, and why the cheapest is barred.** The
report offered: (1) caveat the field when the class is a known owner-drawn
one; (2) return the flag's provenance; (3) rename it so it cannot be read
as "the user can use this."

Option 1 is not available here: we keep **no target knowledge in any repo**,
so a list of owner-drawn class names has nowhere to live. Option 3 breaks a
published surface -- `enabled=` is a documented locator filter and a field
a third of assertions already read, so a rename is a migration, not a fix.

**What was actually done: option 2, at the contract, not per element.** The
provenance of `enabled` is *constant* -- every window-node value is
`IsWindowEnabled`; an owner-drawn control paints its own greyed state
without clearing the bit. A constant fact stamped on every element is the
noise the `actionable`-only-when-False rule (D66) exists to avoid. So the
provenance goes where the caller reads it and where it costs nothing per
element: the `find` and `describe` tool descriptions now say `enabled` is
the `WS_DISABLED` bit and not proof a control will act, and point at
`capture` / `expect={changed}` to confirm availability. The `enabled=`
locator-filter doc and the `WindowNode` / `AccessibleElement` docstrings
carry the same wording, so the source and the contract agree.

**Why the value was not touched.** `IsWindowEnabled` really did return true;
the reading was wrong, not the measurement. The fix is to say what the
measurement is, not to fake a better one -- a per-element "is it owner-drawn"
verdict would need the `surfaces` probe, which `find` deliberately does not
run.

**A guard test, because a promise in prose gets broken.** `test_find_and_
describe_disclaim_enabled_as_availability` asserts both descriptions still
name `IsWindowEnabled` and `owner-drawn`, so the caveat cannot regress out
of the interface silently (the D60 lesson). Platform-neutral text and a
platform-neutral test: verifiable anywhere, motivated by a Windows target.
*(issue #51)*

### D#12. Modality is declared here, and nothing is disabled

**Context.** L5 asks what `_NET_WM_STATE` and AT-SPI say about a modal, and
whether a sent event to a held window is honoured. The second needs no
measurement: D#11 found sent events ignored in every configuration, held or
not, so modality has nothing to add to it. The first inverts the Windows
mechanism.

**Both layers declare it.**

| | during the modal |
|---|---|
| the modal, AT-SPI | role `frame`, states `ACTIVE, MODAL, SENSITIVE, SHOWING, VISIBLE` |
| the modal, X | `_NET_WM_STATE_MODAL`, `_NET_WM_STATE_SKIP_TASKBAR`, and `WM_TRANSIENT_FOR` naming the owner |
| the owner, AT-SPI | `SENSITIVE, SHOWING, VISIBLE` -- it lost `ACTIVE` and **nothing else** |

`WM_TRANSIENT_FOR` is the `owner` field `TopLevel` already carries, available
directly rather than derived. And modality is *stated* rather than inferred,
which is a better position than Windows, where it is only visible as a side
effect.

**The Windows mechanism does not port, and that is the finding.** D48's
`blocking_ancestor` walks up looking for a window that reports **disabled**,
because on Windows a modal disables its owner. Here the owner keeps
`SENSITIVE` throughout. A driver asking whether anything above a control is
disabled gets "no" while the application is completely held.

So the check runs the other way round: not *is anything above me disabled*
but **is anything modal transient-for me**. Slice 3 has to be built that way,
and `blocking_ancestor` returns the modal rather than a disabled ancestor.

**D48's trap is sharper here.** There, the mistake was asking the *control*
instead of the top-level -- the top-level did report disabled, so the
information existed one level up. Here no accessible reports anything wrong
at any level, including the top-level, so the information is not in the
accessibility tree at all. It is in the window manager. A driver that stays
inside AT-SPI cannot see modality, and will actuate into a held application
with every state it can read saying the application is fine.

**One signal that moves but must not be used alone.** The owner loses
`ACTIVE`. So does any window when anything else takes focus, modal or not.
Recorded so it is not mistaken for a modality check.

**A role would not have helped either.** The modal comes back as role
`frame`, not `dialog` -- looking for a dialog role finds nothing.

**A late correction to slice 5a, found by running these two suites
together.** Putting a window away is a *message* to the window manager here,
not a call: `iconify` returns as soon as it is sent, and
`_NET_WM_STATE_HIDDEN` appears whenever the window manager gets round to it.
Windows' `minimize_no_activate` is synchronous, so nothing on that side ever
had to wait -- and `MinimizedWatch.start()`, written from the Windows shape,
read the state back immediately and sometimes saw the window still out. It
passed alone and failed under load, which is the signature of a race rather
than a defect in the thing being watched.

`start()` now waits for confirmation and raises `WatchError` if the window
manager never acts, because a caller that gets a watch back and finds the
target still on screen cannot tell "not yet" from "never".

**Seven suites now stand up a nested X server and five of those a window
manager.** They pass individually and contend when run together; two failures
above were deadlines rather than defects. The skips are honest -- a probe that
produces no report skips rather than failing -- but a silent skip is exactly
the hazard `CLAUDE.md` warns about, so this is a real cost and it is growing.
Worth consolidating onto one shared nested stack before it grows further.

### D#40d. Slice 3: two identifier spaces, and modality lives in the other one

**Context.** Slice 3 is modality and state -- `top_level_state`,
`blocking_ancestor`, `snapshot`, `surface_of`, `restore_process`. D#12 had
already found that the Windows mechanism does not port. What it had not
found, because it read AT-SPI and X side by side rather than through the
contract, is that the two answers are not in the same *currency*.

**Windows has one identifier space; this has two.** An `hwnd` is what the
accessibility layer talks about and what the window manager talks about, so
`top_level_state` reports `handle` and `owner` in one currency without anyone
deciding to. Here the tree mints handles for AT-SPI accessibles, and
`_NET_WM_STATE_MODAL` and `WM_TRANSIENT_FOR` are properties on an *xid*.
`find_modal_blocks` does `by_handle[window.owner]` -- so a backend that
reported `owner` as an xid alongside a minted `handle` would look every owner
up in the wrong space and find none of them, and report a completely held
application as fine. The failure is silent and looks exactly like health,
which is the same shape as the bug D#12 exists to prevent.

**So `top_level_state` answers in xids, and that is the decision.** Modality
is a window-manager fact; the window manager's identifier is the xid; a
top-level *is* an X window. Every field comes from X -- caption from
`_NET_WM_NAME`, visibility from `_NET_WM_STATE_HIDDEN` (D#13), owner from
`WM_TRANSIENT_FOR`, modality from `_NET_WM_STATE_MODAL`. Going to AT-SPI for
the caption, the way the Windows one calls `read_window_text`, would cost a
bus round trip per window to obtain the same string and would reintroduce the
correlation problem for nothing.

**The policy grew a second signature rather than the backend faking the
first.** The neutral `find_modal_blocks` found a block by asking whether the
owner had gone disabled, and its docstring claimed that was universal. The
alternative considered and rejected was to have the Linux backend report
`enabled=False` on a held owner -- synthesising the Win32 signature. That
keeps the neutral layer untouched and makes `enabled` mean "held" on one
platform, which is a lie in a field other code reads. Instead `TopLevel`
carries `modal`, and the policy accepts either signature. Neither is
preferred: they are two dialects of one fact, no platform is required to
speak both, and a platform speaking both de-duplicates by owner anyway.
`modal` is documented as "False means *not declared*, never *not modal*",
because on Windows it is always False.

**`blocking_ancestor` inverts, and returns the modal.** The Windows one walks
up looking for a window that reports disabled. Here nothing is ever disabled,
so that walk returns "no" while the application is held. The question becomes
"is anything modal transient for me", and what comes back is the dialog
rather than the window being held -- which is also the more useful of the
two, being the thing an operator has to go and deal with. Callers only test
it for None, so the change of subject costs nothing.

**The crossing between the spaces was measured, not modelled.** Four routes
tried on the fixture with a modal up:

| route | answer |
|---|---|
| `Accessible.get_attributes()` | `{'toolkit': 'GTK'}` -- **no window id** |
| `get_extents(SCREEN)`, position | **0, 0** for both frames, one of which X had placed at (259, 275) |
| `get_extents(SCREEN)`, size | 520x507 and 240x110 -- **exact**, both |
| accessible name vs `_NET_WM_NAME` | **exact**, both |

So GTK4/X11 does not answer screen *position* through the accessibility
layer at all. Position cannot be used; size can. The key is name and size
together, and ambiguity is refused rather than guessed at (D33).

**That the position is unusable is the finding with the longest reach.** It
is not a modality problem -- it is a problem for anything that hit-tests a
screen coordinate against the accessible tree, which is `deepest_child_at`
in slice 4. Recorded here because slice 4 will otherwise measure it again.

**When the frame cannot be identified, the question is re-asked of the
process.** Two frames of one process with the same title and the same size
are genuinely indistinguishable from outside, and picking one would answer
"what is holding this control" with a coin flip. The fallback -- is anything
in this process modal at all -- can refuse an action on a second, unheld
window of the same process. That is the safe direction: a wrong refusal costs
a caller an attempt, a wrong permission actuates into a held application.

**`RestoreResult` moved to the neutral model**, which is D#40a's move for
`ProcessFacts`, for the same reason: it lived in a module that binds Win32 at
import, so no other backend could name the type it was contracted to return.
`backends/windows/restore.py` re-exports it, so nothing that imported it from
there breaks.

**Restoring takes the foreground here, necessarily.** D#14 measured that a
bare map does nothing at all and only `_NET_ACTIVE_WINDOW` restores -- and it
focuses in the same motion. So `took_foreground` is expected True on Linux
whenever anything was restored, where on Windows it is normally False. The
field now records the difference between the platforms rather than hiding it.
The X call is named `activate` rather than `restore` on purpose: naming it
for the un-hiding half would hide the focus change inside it.

**`winapi` is wired, and deliberately partial.** Thirteen distinct names are
reached through `current().winapi` from the tool layer, and almost all belong
to slices 4 and 6. Wiring them now would mean building against measurements
not taken. This answers the two `restore` needs and refuses the rest *by
name*, with an explanation, rather than an `AttributeError` from three
modules down (D10). The name is a Win32 one and wrong here; renaming it
touches a contract name Windows shares, so it is left for its own change.

**Two gaps shipped knowingly, both asserted as tests so they are visible.**
`surface_of` answers "native" for everything, because `WEB_HOST_CLASSES`
holds Win32 window classes and no AT-SPI role can match one -- what an
embedded document reports is L8 (#15), unmeasured, and guessing at
`document web` would be modelling. And `UnexplainedBlock` is *unreachable*
here rather than merely empty, since it requires a disabled window and
nothing is ever disabled: a caller treating "no unexplained blocks" as
evidence of health would be reading a constant.

**Verified against a live target on the nested display**, through
`backends.current()` rather than through the probes -- a wiring mistake shows
up there and cannot show up in the measurement suite, which never calls the
contract. `blocking_ancestor` on a real `WindowNode.handle` moved from None
to the modal's xid when the dialog came up. Eight tests, all passing.

Evidence: #40 slice 3; D#12; D#13; D#14; D#40a; D33; D59; issue #15 for the
`surface_of` gap.

### D#40e. Slice 4a: one rung, and a write that reaches a held application

**Context.** Slice 4 is acting. D#10 measured the primitives and D#11
measured what is missing, so this was meant to be assembly. It produced one
finding that changes a guard from a courtesy into the only thing protecting
a target.

**Every ladder here is one rung long, or empty, and that is D#11's shape.**
Tier 3 -- the rung that drives a chosen window without taking the operator's
focus or pointer -- does not exist on GTK4/X11: `XSendEvent` was ignored in
every configuration tried, each behind a passing control. The only rung below
tier 1 is tier 4, real synthetic input, which takes the actual keyboard and
pointer and is therefore acceptable only where the input being taken is not
the operator's -- inside the nested X server. `HiddenDesktop` is not built on
Linux (slice 5b), so **tier 4 has nowhere safe to run and is not offered.**

| verb | rungs | why |
|---|---|---|
| `click` | 1 | `Action.DoAction` |
| `click`, right button or modifier | **0** | an AT-SPI action takes an index and nothing else |
| `set_text` | 1 | `EditableText.set_text_contents` |
| `send_keys`, `type_text_element` | **0** | no accessibility pattern for "press these keys" |

**The zeros are a decision, not an omission.** Offering tier 1 for a right
click would perform a *left* click and report it as a successful right one --
a wrong action reported as a correct one, which is the failure this ladder
exists to prevent. An empty ladder becomes `TIER_EXHAUSTED`, a result naming
what the verb offered and what the actuator allowed (D10), which is a target
the strategy cannot fit reported as such (D53). It also reads differently
from a rung that declines: a decline invites a retry, "nothing implements
this" stops one.

**A tier 1 write reaches a modally-held application. This is the finding.**

The Windows `unblocked` precondition exists because posted messages bypass
the modal loop -- real input to a held application is swallowed by the
system, but a posted message goes straight to the window procedure. There
are no posted messages here; tier 1 is a D-Bus call into the application's
own process, and whether the toolkit refuses it while held was open.

Measured with a modal up: `blocking_ancestor` names the modal,
`unblocked` correctly reports False -- and the raw call **returns true and
the binding emits its `changed` signal with the written value.**

So this platform has the *same* hazard as Windows arriving by a completely
different route, and `unblocked` is **load-bearing rather than a courtesy**:
it is the only thing between a driver and a held application. It can only do
that job because `blocking_ancestor` inverts to look for something modal
transient-for the frame instead of a disabled ancestor -- there is never a
disabled one (D#12). The two findings are one mechanism.

**Tier 1 is the preferred write path here, inverting the Windows
conclusion.** D#10 said so and this confirms it through the contract: the
binding hears the write, so there is no D21 split. `allow_pattern` is
therefore accepted and **deliberately ignored** -- on Windows it exists
because the API write is the hazardous path, and honouring it here would
leave no way to set text at all, since the typing path it protects does not
exist. Likewise a non-robot cadence cannot be honoured: an API write produces
no input events, so there is nothing to pace, and dropping the rung would
leave nothing. Both are recorded rather than silently ignored.

**The intermediate empty value is real.** `set_text_contents` clears and
re-inserts, so `changed` fires twice and the first carries an empty value
nobody wrote -- measured through the contract as `["", "slice4-wrote-this"]`.
Harmless against a mirror; not harmless against a field that rejects empty or
runs a lookup per change. It is what the toolkit does and not something the
backend can hide.

**A write cannot be verified by reading it back, and that blocks more than
reading.** `read_window_text` answers None for the entry before *and* after a
successful write, because D#34b withholds by class -- nothing here
distinguishes a plain entry from a password field. So the effect of an action
is unconfirmable through the contract, and this suite has to read the
fixture's own `changed` events, which a real caller does not have.
**Issue #43 is therefore a blocker for the acting slice, not a tidy-up.**

**Handles are enumeration-scoped, and a driver has to respect it.**
`enumerate_process` calls `tree._reset()`, so every previously minted handle
dies. A first draft of the probe re-enumerated to look a value up and then
reused an older handle; it raised, correctly, with a message saying so. Worth
recording because the verbs take handles and the tool layer's usage pattern
therefore matters -- the actuator itself is safe, since `snapshot` is pure X
and re-enumerates nothing.

**Two corrections to how this was measured, both of which produced wrong
answers first.** The fixture's `Recalculate` control is the owner-drawn
`DrawingArea` carrying `AccessibleRole.BUTTON`, so it enumerates as `push
button` -- probing it while calling it the real button reproduced D#10's
negative by accident and would have recorded that a real button offers no
actions. And `WindowNode.text` is the accessible *name*, not the contents;
for an entry it stays "bound entry" whatever is written, so reading it back
made a successful write look inert. Neither is a bug in the backend; both are
ways an honest-looking measurement says the opposite of the truth.

**Not done in this slice.** `NAMED_KEYS`, `EDIT_ACTIONS`, `button_pair`,
`copy_route`, `focus_route`, the clipboard and `ink_fraction` are all tier 4
or capture work, and `deepest_child_at` additionally needs the screen
position D#40d found AT-SPI does not report. They wait on slice 5b.

Evidence: #40 slice 4; D#10; D#11; D#12; D#34b; D#40d; D10; D53; issue #43.

### D#43. The third state gets a name instead of borrowing `None`

**Context.** `read_window_text` returns `str | None`, and `None` meant *did
not answer*. On Windows that is unambiguous: the OS refuses a cross-process
`WM_GETTEXT` only for a password field, so `is_protected` tells the two
apart, which is what D37 is about.

On Linux `None` had **three** causes, and only two were separable:

| cause | had a name |
|---|---|
| the control did not answer within the deadline (D#9) | -- |
| the toolkit declares it a password field | yes, `is_protected` |
| an editable entry, withheld because nothing distinguishes it from a password (D#34b) | **no** |

So a perfectly healthy plain text field read exactly like a hung one. That
is the confusion D37 exists to prevent, arriving from the other direction --
and a caller told the first goes off diagnosing a hang that is not
happening.

**Two changes, and the second is the one that closes it.**

`read_window_text` grows `disclose: bool = False`. Windows accepts and
ignores it -- there is nothing to opt into where the OS itself refuses --
and Linux passes it to `protection.read`, which has taken exactly that
parameter since D#34b with nothing able to reach it.

But an opt-in alone does not close the bug: with `disclose=False` a withheld
field still returns `None`. So the contract also grows **`disclosure()`**,
answering `"allowed"`, `"protected"` or `"withheld"`. It reads no value --
the verdict comes from role and states alone -- so asking is safe on a field
whose contents must not be fetched.

**Rejected: let the tool layer work it out.** It already has the
`WindowNode`, and `class_name` on Linux is the accessible role, so it could
tell a withheld entry from a silent one with no contract change. Rejected
because it puts platform-specific reasoning in the platform-neutral layer,
which is what D59's boundary exists to prevent. Stated rather than left for
someone to rediscover and assume it was missed.

**Windows never answers `"withheld"`, and that is honest rather than a gap.**
It does not withhold, because it does not have to.

**`disclose` does not override `protected`.** A field the toolkit *declares*
a password is never disclosed, at any grain. That verdict is not a guess, so
there is nothing for a caller to know better about.

**And the cost that cannot be avoided is now written down.** Asking for
disclosure on the *undeclared* hidden entry returns the secret -- because the
driver genuinely cannot tell it from a plain one. Withholding by class buys
safety by default; it cannot buy safety against a caller who explicitly asks,
and pretending otherwise would be a guarantee this platform cannot keep.
`tests/test_linux_reading_wired.py` asserts exactly that, so the cost is
visible rather than discovered.

**The asking lands in the trace; the answer does not (D62), and that needed
no code.** The tool wrapper already records every call's `args` and, of the
result, only `ok` and any error. So `disclose=true` appears as the request it
was while the values it returned do not. An explicit trace call was written
first and then deleted -- it was both redundant and reaching for an attribute
that does not exist.

**A tool module hit D60's limit, and the fix moved code.** `discovery.py`
went to 428 lines. The reporting logic -- what an empty-handed read *means*
and how to say so -- is platform-neutral policy that was living in a tool, so
it moved to `ghostdriver/disclosure.py`: pure, testable without a desktop,
and the same shape from both backends (D59). The limit is a test precisely
so that this happens rather than the number growing (D60).

**Why this mattered more than it looked.** D#40e found that slice 4a cannot
verify its own writes: `read_window_text` answers `None` for an entry before
*and* after a successful write, so an action's effect is unconfirmable
through the contract and the test suite has to read the fixture's own
`changed` events, which a real caller does not have. This issue was filed as
a reading bug; it was blocking acting.

**Verified on Linux only.** `env: both` -- the signature change and the new
contract name are implemented on Windows and must be re-verified there.
`test_the_specification_exists_and_covers_the_contract` caught the new name
missing from `docs/LINUX.md`, which is the guard working.

Evidence: issue #43; D#34b; D#9; D37; D38; D59; D60; D62; D#40e.

### D#39. Three kinds of platform gate, and only one of them was honest

**Context.** CLAUDE.md's rule is "never gate a guard on the condition it
exists to detect", and it was written after two guards were found doing
exactly that. #39 asked whether the same failure existed at scale. It does:
**370 of 956 test functions sit in 41 modules gated `on_windows` at module
level.**

**The audit found three groups, not the two the issue expected.**

| group | needs | verdict |
|---|---|---|
| the subject *is* Win32 -- `WM_GETTEXT`, `EM_GETPASSWORDCHAR`, UIA, hidden desktops | Windows | gate is correct, leave it |
| the subject is neutral but the *test* drives a real window | a target on some platform | parametrise over backends once both have one; still open |
| the subject is neutral and no window is ever touched | **nothing but a session** | should never have been gated |

The third group was the surprise, and it is where the debt was.
`tests/test_tool_contracts.py` describes itself as "the contract every tool
honours" and checks two platform-neutral promises -- a released session
refuses every tool, and a session opened at a lower tier cannot call a higher
tier's tool. Both are enforced inside `authorize`, **before** a locator is
looked at or a control touched. They were gated `on_windows` for one reason:
`win32_target` was the fixture that existed.

So a neutral promise was verified on one platform only, which is the same
failure as the two guards CLAUDE.md already names, at a different scale.

**The fix is not a better fixture; it is not needing one.** The first attempt
added a neutral `live_pid` fixture spawning a windowless process. It hung.
`Toolbox.attach` enumerates the target's windows to describe what was
attached to, and on Linux that reaches AT-SPI with no bus in the test
process, where it **blocks rather than fails** -- which is precisely why
nobody had noticed: the tests had never run there.

`SessionManager.attach` touches no backend at all. It checks consent and
returns a `Session`, which is exactly and only what a gate test needs. The
tests now open a session through it, using this process's own pid, and no
fixture is involved. Neutral by construction, which is what CLAUDE.md asks
for, rather than neutral by arranging a target on every platform.

**Measured: 60 of 60 contract tests now pass on Linux, up from 24 passed and
36 skipped.** Across the suite, 589 pass where 552 did, and skips fall from
465 to 430.

**A guard, and it was wrong twice before it was right.** First attempt
searched each file for `on_windows` and produced two false positives: the
string appears in prose explaining why a gate was *removed*, and in
`test_on_windows_every_contract_name_resolves_to_something_real`, a test
whose subject really is the Windows backend. Second attempt matched any
decorator, which would have condemned `test_backends.py` for holding one
legitimately Windows-only test beside neutral ones.

What it checks now is **module-level `pytestmark` only**, by AST, against a
named list of files that must run everywhere. That is the failure mode #39
actually measured: a whole file behind one gate. A single gated test inside
an otherwise-neutral module is fine, and saying so keeps the guard from
being the kind that gets deleted for crying wolf. Verified by re-gating
`test_tool_contracts.py` on purpose and watching it fail.

**Still open.** The second group -- tests that need a real target -- stays
gated. Parametrising it needs a Linux target fixture, and every module that
wants one currently pays for its own nested display and bus, which is slow
and is why #48 proposed a shared stack. Not smuggled in here.

Evidence: issue #39; CLAUDE.md ("never gate a guard on the condition it
exists to detect"); D59; D#9.
### D#4. The capture/restore flakes traced to a leaked watch on a reused pid

**Context.** Two tests failed intermittently and undiagnosed (#4):
`test_capture_returns_a_png` and
`test_restore_is_a_no_op_when_nothing_is_minimized`. Both reduce to one
symptom -- a fresh, off-screen, never-activated target window found
*minimized* mid-test, which makes `capture` fail (a minimized window has
nothing to render) and `restore` non-trivial (it finds something to
un-minimize). #4 had ruled out test order and reproduction under load,
and instrumented the two failures to pay for themselves.

**The mechanism.** The only thing in this codebase that minimizes a
window is a `MinimizedWatch`, and the only way one touches an *unrelated*
window is a leak: a prior test's watch still running against a pid the OS
has since reused for the fresh target. Its poll enumerates
`top_level_windows(self.pid)` -- now the *new* process's windows --
finds the fresh window on screen, reads that as an escape, and minimizes
it. The watch's own locked handle is the dead process's and does nothing;
the fresh window is collateral. This is a plausible, complete explanation
of both flakes at once, and it is timing-dependent exactly as observed:
it needs a watch to outlive its test *and* the pid to be reused before
the watch's next poll.

**Why it should already be closed.** The self-stop guard added with the
tree-following watches (a watch whose locked window is gone stops rather
than keep sampling a pid the OS may reuse) removes the mechanism: a
leaked watch sees its window is gone on its next poll and exits before it
can act. Reproduced deterministically in
`tests/test_flaky_watch_leak.py` -- a watch holding a dead window's handle
with a live target on the (reused) pid stops without minimizing that
window -- so a regression of the guard fails there, not as a
one-in-hundreds flake elsewhere.

**What was added, and what stays open.** The `win32_target` fixture now
names any live watch thread, and fails loudly if a `minimized-watch-<pid>`
is alive for *its own* pid -- the smoking gun, turned from inference into
a message. Twelve rounds interleaving the watch-heavy modules with the
two tests under load produced no failure. That is consistent with the
guard having closed it, but it does not *prove* the historical flakes
were this cause -- only that this cause is now reproduced, fixed and
instrumented. Per #4's own rule, the issue stays open until a real
occurrence is caught (now diagnosed on sight) or ruled impossible; what
changed is that the next occurrence, if any, names its cause. *(issue #4)*

### D#53. Gate on the distribution's version, not the module's attribute

**Context.** The whole protocol-layer suite was skipping with a reason that
looked entirely reasonable:

```
SKIPPED tests/test_mcp_server.py:25: module 'mcp' has __version__ None,
                                    required is: '2.1'
```

mcp 2.1.1 was installed and correct. `pytest.importorskip(minversion=...)`
reads the **module's** `__version__` attribute, which mcp does not set, so a
good install was read as version `None`, judged below the minimum, and
skipped.

**A silent skip that explains itself is worse than one that does not.** This
project is built around "a green run has verified less than it looks", and
this was that trap in its most convincing form: nothing looked wrong, the
reason string named a real convention, and 19 tests plus the entire stdio
transport quietly stopped existing.

**The fix is to ask a source that always exists.** The version a package
manager installed lives in distribution metadata; `__version__` is a
convention a distribution may or may not follow. `conftest.mcp_or_skip()`
reads `importlib.metadata.version("mcp")` instead. A missing distribution
still skips, and a genuinely too-old one skips saying what it found -- both
are real answers. What no longer happens is a good install being mistaken
for either.

**One helper, not two copies.** `test_mcp_server.py` and `test_mcp_stdio.py`
each carried the same broken gate, which is the same shape as the six
modules that each held their own `ctypes.WinDLL` binding before
`conftest.user32()` consolidated them.

Evidence: issue #53; CLAUDE.md ("a green run has verified less than half the
suite"); D#39.

### D#58. A missing accessibility bus killed the process, and nothing caught it

**Context.** Fixing D#53's gate made the protocol suite run for the first
time on this machine. It **core-dumped**.

```
dbind-ERROR **: AT-SPI: Couldn't connect to accessibility bus.
Trace/breakpoint trap (core dumped)          # SIGTRAP, exit 133
```

**`Atspi.init()` reports an unreachable bus through GLib's `g_error()`, and
`g_error()` is fatal by contract.** It aborts the process. There is no Python
exception to catch, no result to return, and no traceback -- one
`list_targets` on a headless box took the server down and every open session
with it.

This is D10 -- errors are results, not exceptions -- broken in the most
extreme way the runtime permits. And the trigger is ordinary: a container, a
systemd service, an SSH session with no `DISPLAY`, a desktop where nobody
enabled accessibility.

**The fix is to ask before reaching.** `Gio` answers the same question --
`org.a11y.Bus.GetAddress` -- and raises a **catchable** `GLib.Error` where
AT-SPI aborts. `_require_accessibility_bus()` runs before `Atspi.init()`,
which is a single choke point for the whole backend. The check is bounded
(D#9): a D-Bus activation can block waiting for a service that will never
start, and a driver that hangs is barely better than one that aborts.

Autolaunch is refused explicitly in the test environment. Without that, GLib
may try to *start* a session bus with `dbus-launch`, and on a box that has it
the child would find a bus after all -- a test that proves nothing while
appearing to pass.

**There are two external services, and each machine hid the other's gap.**
The first fix guarded the accessibility bus and passed everywhere it was
tried. Run on a second box -- one that *has* a bus and no `DISPLAY` -- and it
failed again, this time with a raw `Xlib.error.DisplayNameError` reaching the
caller as an unexpected error. This backend depends on the accessibility bus
*and* the X display, a machine can be missing either independently, and
testing on one host would have shipped a half-fix that looked complete.

Both preflights raise the same exception, because to a caller it is the same
fact: the desktop this backend reads is not there. And the tests assert that
the refusal names *a* missing service and *a* remedy, rather than which one
-- pinning the order would make them pass on one box and fail on the next for
no real reason.

**`AccessibilityUnavailable` is deliberately not a CONTRACT name.** It says
the platform is supported and a service it depends on is absent, which is
different from `UnsupportedPlatform` ("this backend does not implement
that"). Nothing on Windows can raise it, and a name every backend must
implement is the wrong shape for a condition only one of them has.

**Caught once, in the tool wrapper.** Every tool that reaches the tree can
raise it, so the seam that already sees every result turns it into
`NOT_ACTIONABLE` with the remedy in the message. Per-tool handling would
have been twenty chances to forget one.

**Two tests that had been asserting the environment, not their subject.**
`test_a_tool_reached_through_dispatch_returns_its_result` and the stdio
equivalent both asserted `ok is True` -- coupling a *wiring* test to the
machine having a desktop, which is D#39's mistake in a new place. They now
assert that a well-formed result crossed the seam, and accept a refusal as
one. A refusal surviving the transport is arguably the better proof: it is a
nested structure the server built, serialised and handed back.

**And a second bug the same gate was hiding.** `StdioServerParameters`
passes **no environment through by default**, so the spawned server could not
import `ghostdriver` from a source checkout and died before speaking a word
of protocol. The client saw only "Connection closed", which names the symptom
and hides the cause.

**The pattern across #53, #58 and #39 is one pattern.** A test that does not
run, a gate that misreads, a guard that skips: none of them fail. The suite
stays green and the coverage quietly leaves. Three separate bugs -- a fatal
abort, a dead transport, and a neutral policy verified on one platform --
were all held open by something that was *not failing*.

Evidence: issue #58; issue #53; D10; D#9; D#39; `tests/test_linux_no_bus.py`.

### D#61. A rect is not proof a window can be clicked, so find says when it cannot

**The field report.** `find` on a Chrome window returned a normal on-screen
rect while the page itself reported `document.visibilityState: hidden` -- the
window was occluded, then later minimized -- and the result carried no sign of
it. Two clicks were posted blind to a window that was not visible where its
rect said.

**The gap.** A rect is where a window *would* paint, not whether a person can
see it now. Occluded, minimized-but-restoring and fully visible all report a
plausible rect, and a posted click to a covered window can land on the glass
in front. The caller had no way to tell it was guessing.

**Two honest signals, both cheap, both reads.** `find` now attaches
`obscured` to a match when its window is either:

- **minimized** (`IsIconic` via the style bit) -- definitive: the rect is not
  where it paints; or
- **covered at its centre** -- `WindowFromPoint` on the window's centre
  returns a window that is neither it, a child of it, nor part of the
  target's own process tree. That last clause matters: a dialog the
  application itself raised sits in front legitimately and is not an
  occlusion to warn about.

**What it deliberately is not.** The covered check is a *centre-point* test,
not a full-coverage scan -- the issue asked for cheap and structural, not
per-pixel, and the note on the flag says exactly that so a caller does not
over-read it. A window covered everywhere but its centre reads visible; that
is the honest limit of one point, stated rather than hidden.

**A report, not a verdict (D28); no desktop taken (D55).** `obscured` never
fails a call or refuses an action -- it is information for the caller, who may
`restore` or `foreground` first. Nothing is raised or activated to measure
it; `WindowFromPoint` and the style bit only read. And it is emitted *only*
when obscured, the way `actionable` is emitted only when False (D66): a rect
with no `obscured` is the safe case and says nothing.

**Split for the limit (D60).** The helper pushed `tools/core.py` past 400
lines, so it lives in `tools/visibility.py` as a mixin `DiscoveryTools` takes,
not shaved into core. *(issue #61)*

## Open, for whoever picks this up

> These two, and everything else outstanding, are now tracked as issues on
> `steiner385/ghostdriver-mcp` and phased on the **GhostDriver** project
> board. The list below is kept because it says *why* each gap is a gap,
> which an issue title cannot; the board says what order to take them in
> and which machine each one needs. If they disagree, this file is the
> reasoning and the board is the plan.

- **The denylist matches captions, identities (D57) and places (D72).** A
  control with none of the three -- one that scrolls inside its window --
  is what remains unexpressible. *(issue #2)*
- **Nothing gives *exact* text out of an owner-drawn region.** The model can
  read a capture, which is enough to decide what to do next, but not enough
  to verify a value (D46). The routes that would give exact text -- the
  control's own clipboard copy, an export command, a hidden accessible
  surface -- are unprobed. That is the gap worth closing, and it is a
  different gap from the one OCR was imagined to fill. *(issue #1)*

---

## Revision, 2026-09-02

### R1. Target selection is interactive and session-scoped, not configured

*R1a (D65): with an operator directory configured, a decision is kept for as long as the process it is about runs, across server runs. The session is still the unit of work; the application is the unit of consent.*

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

### R4. The region model splits into two axes

**Supersedes the single `SurfaceKind` enum, and closes the open item that
deferred this until there was a second target to decide against.**

**What was wrong.** One enum answered three different questions depending on
which value it held. `NATIVE`, `ACCESSIBLE` and `OPAQUE` said how to reach a
region. `WEB` said what a region *is*. `UNRESPONSIVE` said that nothing was
established. A caller reading one field could not know which question it had
just been answered.

**The defect that made it more than untidy.** An embedded engine keeps the
class that identifies it whether its document tree is live or dormant, while
the way in changes completely between those states. `map_digest` fingerprints
`class:kind`, so it did not move across that transition — and the digest
exists precisely so a caller can notice "the approach I am using has stopped
working". Reproduced with the numbers measured earlier on a real target: one
element while suspended, 203 once awake, same digest both times.

The live/dormant answer did exist, but only inside the prose `reason`.
Information in a sentence cannot be acted on by a caller or seen by a change
detector.

**What replaced it.**

- `kind` — what the region is: `native`, `web-document`, `owner-drawn`,
  `unknown`. Stable while the application runs.
- `access` — what reaches its content now: `window-messages`,
  `accessibility`, `pixels`, `none`. Moves as the application runs.

`map_digest` covers both, so waking an engine now registers. `access` is
about *reading*; actuation is the tier ladder's question, and an owner-drawn
region that can only be read as pixels still takes an ordinary click.

`unknown` and `owner-drawn` stay separate, as `UNRESPONSIVE` and `OPAQUE`
did: one region is known to expose nothing, the other never answered.
Merging them would send a caller to capture pixels of a window that may be
about to recover.

**Measured against a second target, which is what the deferral was for.** An
Electron application reports `kind: web-document` with `access:
accessibility` — one region, 1.27M px, the whole application, readable
through the accessibility surface with no browser protocol at all. Under the
old model it said "web-document" and nothing else, and the obvious inference
from that label is the expensive one. Two native shells classified as
entirely `window-messages` with no false positives.

**One thing this did *not* fix, contrary to first appearances.** Membership
of `regions_needing_another_mechanism` is unchanged: a live web region still
cannot be read with window messages, so it still belongs on that list. A
test asserting otherwise was wrong and was corrected. What changed is that
the list now names the mechanism for each entry rather than leaving a caller
to infer it from a conflated label.

### D42. A re-probe merges; the loader tolerates what it does not model

**Closes the known cost recorded in D3.**

**Why now.** D3 accepted the overwrite because the only curated field was a
denylist someone could retype. That stopped being true once the file carried
input-sensitivity notes: those were *measured*, and measuring one again means
tripping the target at machine speed, which is the thing the note exists to
prevent.

**What it does.** `save` writes three layers, and the order is the policy.
This document's defaults first, so a new file is still a full template — the
empty curated fields are what show an operator there is something to fill in
— and so a profile written before a field existed gains it. Then whatever is
on disk, which is how curation and keys this code does not model survive.
Then the observed fields, the only ones a probe is entitled to replace.

It refuses a file describing a different application unless forced: the path
is usually typed by hand, and that overwrite is not recoverable. It writes
through a temporary file, because an interrupted probe that truncated a
profile would leave every later session unable to attach.

**Found on the way.** `ProfileDocument.load` passed every key straight to the
constructor, so a document with one extra line could not be read at all —
including the example this project ships, which opens with a `_comment`
block. The merge would have made that latent bug live, since preserved
unmodelled keys are exactly what the loader choked on. It now ignores keys it
does not model, and `profile_id` and `matched_profile` default, because a
hand-written policy-only profile has neither.

### D43. Endpoint extraction had a precision problem, not a coverage one

**Supersedes the recorded concern that the assumption was n=1.**

**Measured** across 147 window-owning processes on one machine: 10 yielded
something, and most of those were not endpoints. Extension identifiers
(`chrome-extension://…`), a crash-reporting URL, and a policy allowlist
mangled into a single "endpoint" whose host was eleven hosts joined by
commas.

That inverts the concern. The worry was that a target naming its server some
other way would yield nothing. The real fault was yielding something wrong —
and under R1 this line is what a person reads when deciding whether to allow
automation, so a confident wrong answer costs more than a blank.

**What changed.** Only network schemes count; a URL ends at a comma or
semicolon as well as at whitespace, so list-valued switches split; hosts that
are obviously mis-parses are dropped; repeats collapse; and `describe_target`
names three and summarises the rest, because a consent prompt that runs off
the line is one nobody reads. Ten hits became seven, the false ones gone and
the genuine gateways still found.

### D44. Posted keystrokes carry a real scan code

**Decision.** `WM_CHAR`, `WM_KEYDOWN` and `WM_KEYUP` carry the scan code of
the key that would produce them, and a release carries the previous-state and
transition bits.

**Reasoning.** Measured against what Windows itself puts in the field: a real
press of `a` carries `0x001E0001` and its release `0xC01E0001`. This module
sent `0x00000001` for everything — repeat count 1, scan code **zero**, which
is not a value any keyboard produces. A free tell for any target that
inspects lParam, and a one-line fix with nothing behavioural riding on it.
Zero is still sent for a character with no key on the current layout, which
is the honest answer rather than an invented one.

**What is deliberately still missing**, with the measurement behind it:

- **The message triple.** A real keystroke is `WM_KEYDOWN`, `WM_CHAR`,
  `WM_KEYUP`. Posting all three double-types, because the target's own
  `TranslateMessage` synthesises the `WM_CHAR` from the `WM_KEYDOWN` — and
  letting it do so makes uppercase and symbols depend on a shift state that
  cannot be set from outside the target's thread. Needs a hybrid and a real
  test matrix.
- **Physical key state.** `GetAsyncKeyState` does not move for a posted
  message and cannot be made to. A target checking it can only be satisfied
  at tier 4, which needs the foreground — so for that target, unattended and
  undetected cannot both be had, and the operator has to choose.

Both stay open until there is a target that demonstrably inspects them,
because neither can be validated against anything else. That is the same
standard the cadence work was held to.

### D45. Two intermittent failures are undiagnosed, and now self-explaining

**Not a fix. A record of what was tried.**

`test_capture_returns_a_png` failed once in a full-suite run and has not
reproduced since: roughly 1,170 backend captures and 190 through the tool,
under four threads standing fixture applications up and tearing them down to
recreate the desktop-resource pressure of a full run. All fine.

`test_restore_is_a_no_op_when_nothing_is_minimized` behaves the same way. It
reproduced once in about twenty runs of its own module and not again in
twelve more, nor in 58 targeted rounds under deliberate load with the window
state printed each time — which never showed anything minimized.

Test order is *not* randomised. `pytest-randomly` is not installed, and
`-p no:randomly` silently does nothing, so an earlier belief that these were
order-dependent was wrong. They are timing-dependent, which at least rules
out "some previous test left state behind".

Since neither fault comes back on demand, the useful work is making the next
occurrence pay for itself. `GetWindowDC`, `CreateCompatibleBitmap`,
`PrintWindow`/`BitBlt` and `GetDIBits` can all fail for reasons outside this
process, and their messages said nothing about which. They now carry the
OS's own error: "could not obtain a device context" becomes error 8, out of
memory, or 1400, invalid window handle — which is most of a diagnosis. The
restore assertion prints the whole result rather than `[] == [...]`, so the
next occurrence names the window it found and the state it was in.

Recorded rather than quietly retried. A retry would make both disappear from
the output and take the evidence with them.

### D46. The model reads the pixels; OCR is not built

**Decision.** `capture` returns an image block a multimodal caller can look
at. No OCR, now or planned. Pixels are for deciding, never for verifying.

**Why not OCR.** The caller on the other end of this server reads images. It
beats OCR at the thing that actually matters here -- an owner-drawn grid
needs rows, columns and headers, and OCR returns a text blob with the
geometry thrown away. It also costs nothing to install, on a tool whose
premise is "a profile, not a driver".

**The defect found while answering the question**, which is why the answer
had to be checked rather than assumed. `capture` declared `-> dict`, so the
PNG went back as base64 *inside the JSON*: a `TextContent` block, no
`ImageContent`. The model received a string it could not see. Measured on a
real 3840x1200 window: 12.4MB of base64, roughly three million tokens of
noise. The same picture as an image block is around two thousand tokens and
legible. Every capture call was quietly spending enormous context for
nothing, and no amount of OCR reasoning would have surfaced it -- only
looking at what a client actually receives.

The dimensions still go back as structured content; the pixels are not sent
twice.

**Where neither is allowed.** Pixels must not become postconditions. The
whole actuator exists to stop an action claiming success it cannot
distinguish from a no-op, and a read of an image is probabilistic however
good it is -- `PART-0001` and `PART-0OO1` are one glyph apart. OCR would be
no better; it would be worse, and more confident. So the tool description
says plainly: read a capture to decide what to do, verify with `read` or
with an `expect` naming where the committed value appears.

**What that leaves open.** Exact text out of an owner-drawn region is still
unsolved, and it is a real gap -- it is what a caller needs to *verify* a
grid. The routes that could provide it are the control's own clipboard copy,
an export command, or an accessible surface that only appears once the
region has focus. The spec is right that those should be probed before
anything is built on pixels, and none of them has been.

### D47. What a real Profile L1 target actually looks like

Measured during iteration 4, against a sandbox instance of a real 32-bit
Delphi/VCL business client. Recorded because two of these corrected beliefs
this project had been working from, and one of them was mine.

**Classification held.** 97 windows, one per control, x86, toolkit inferred
as Delphi/VCL at medium confidence. Profile L1, on the same evidence the
fixture was built to reproduce.

**The accessibility surface is real but useless for commands.** Phase 1
reported `partial` -- 33 of 98 elements carrying patterns -- which
contradicted the recorded belief that every element is a Pane with no
patterns at all. Both readings were wrong. Broken down by class:

| what answers | pattern |
|---|---|
| five EDIT-derived classes | `Value` |
| the tab strip | `Selection` / `SelectionItem` ×19 |
| **the vendor command-button class** | **nothing; control type Pane** |

So the surface covers text fields -- which typing reaches anyway, and better
(D21, D24) -- and tab selection. It covers none of the command buttons. Tier
1 is not a real option for actuating this target, and the `partial` verdict
would mislead anyone who read it without asking *which* elements answered.

**The region model was right first time.** 73 regions: 70 native reachable
by window messages, and three owner-drawn reachable only as pixels -- the
data grid at 1,006,176px, a canvas panel, and the status bar. No false
positives and no misclassification. The grid is the case the whole surface
map exists for: a million pixels of business data with no child windows and
nothing beneath it on any accessibility surface.

**A modality bug that only a real target could show.** Its window chain is
three deep -- an off-screen application proxy owning both the main window
and a dialog -- and the detector reported the application as being held by
its own main window. Fixed; see the commit. The fixture's chain is one level
and structurally could not have surfaced it.

**Interactive elements that are not windows.** The 19 tabs are owner-drawn
inside their notebook and exist only on the accessibility surface. Locators
address windows, so nothing in this tool can currently name a tab. The
region model is not wrong here -- the notebook region does continue as a
window tree -- but the gap is real: on this class of target, some of the
safest things to actuate are the ones that cannot be addressed.

**Why phase 2 nearly did not run.** Every captioned button on the screen
reached was a write -- send, create, update, copy. Every other button
carried no caption and no accessible name, including a row of six navigator
buttons that a screenshot then confirmed to be Insert, Delete, Edit, Edit,
Filter and Grid Fields. Nothing captioned could honestly be put on a
safe-control list, and the probe is built so that it cannot choose for
itself. Looking at the pixels is what turned "unidentifiable" into
"identified": the toolbar overflow button opens a menu, which is view-only
and reversible, and became the one entry. See D48 for what running it
taught.

### D48. A postcondition is polled to a deadline, not sampled once

**Decision.** `Actuator` checks `expect_after` repeatedly, every 50ms after
the settle, until it holds or two seconds pass. A tier falls through only
after the whole window.

**What forced it.** Phase 2's first run against the real target reported the
overflow button as delivered-but-unverified. Every explanation was chased
before the right one: the expectation's class name, the enumeration, the
locator parser, a stacked modal, pacing, `WM_MOUSEMOVE`, foreground state.
Then the window's arrival was timed: the popup menu became a window
**957ms** after the click that opened it. The actuator checked once, at
250ms, saw nothing, and moved down the ladder. A working control was
declared ineffective by a fixed wait -- the false failure the settle was
meant to prevent, produced by the settle.

With polling, the same run verified on the first attempt and wrote
`TsfToolbarOtherCommandsBtn: wm_mouse_pair, verified` into the profile.

**Cost.** Falling through now takes the full window per tier, so a genuinely
ineffective rung costs two seconds instead of a quarter. That is paid only
on the failing path, and it buys never mistaking a slow effect for no
effect. The unit tests inject a clock that advances on sleep, so the
deadline logic is exercised without the wait.

**Two retractions, recorded because they were said out loud.**

- "The posted input pair does not actuate this control" was wrong. It does;
  variant A -- exactly what `click()` sends -- opened the menu every time on
  an unblocked application.
- "Pacing and mouse-move were ruled out" was unsound. Those diagnostics
  bypassed the `unblocked` precondition the tools enforce, and ran while a
  connection-lost dialog held the application. A control in a held window
  received the messages and did nothing, which is D20, and taught nothing
  about the control. The lesson is procedural: diagnostic scripts get the
  same preconditions as the tools, or their nulls are not evidence.

**Also observed, and unconfounded.** `GetGUIThreadInfo` showed the control
taking mouse capture 16ms after `WM_LBUTTONDOWN` and releasing it on UP --
the VCL pattern, processing posted messages as real input all the way
through. And the target does not pull itself to the front when actuated.

**The gate.** A view-only control on a real Profile L1 target actuated
through the full stack, expectation verified, cursor and foreground
undisturbed, profile written with everything curated left intact. Iteration
4's first half is met on one control class; the watchdog half is not yet
built.

### D#69. A posted click carries the move a person's click carries first

**Context.** The 2026-09-08 field notes, working the primary target's
windowed toolbar and the painted controls around it. A row of glow
buttons wanted "a mouse-move first"; a posted pair with no move in front
of it read as delivered and did nothing. D48 had already recorded that
"mouse-move was ruled out" was retracted as unsound -- the diagnostic that
ruled it out ran while a connection-lost dialog held the application, so
its null taught nothing. The question was left open, and this closes it.

**Decision.** `post_click` posts a `WM_MOUSEMOVE` at the point before the
button pair. Every click a person makes arrives after the pointer does,
and a toolkit sets its hot / mouse-in-control state from that arrival
before the button goes down; a control that gates its click on that state
ignores a bare pair. The move carries the same modifier flags and no
button -- the state of the mouse the instant before the press -- and, like
everything else in that module, it is posted, so it moves nothing on
screen and stays background-safe.

**Evidence.** Proven on the fixture. Its buttons now set a `hot` flag on
`WM_MOUSEMOVE` and clear it on the up, and act on the click only when the
flag was set -- exactly the gate the glow buttons appear to apply. A bare
down/up pair leaves the counter at zero; the tool's `click`, which posts
the move first, moves it to one (`test_a_pair_with_no_move_in_front_of_it_is_not_a_click`).
The fixture's own input-shape test and the button-message tests were
updated to post the move, since a bare pair no longer actuates a gated
button.

**Not yet confirmed on the primary target.** The motivating glow buttons
are on the plan editor, and a re-measurement there needs a plan open in
the sandbox client -- which is the operator's screen to arrange, not the
driver's. The mechanism is proven against a control that gates the same
way; the primary-target re-verification is a measurement for a session
that has a plan open, with `expect` naming the effect. `GetAsyncKeyState`
and the `WM_KEYDOWN`/`WM_CHAR`/`WM_KEYUP` gaps (input.py's standing "two
parts of the gap remain") are untouched: this is the mouse's move, which
is a message a control reads, not a global-state query it cannot.

### D#70. A hot-reloaded generation is whole, or it is not taken

**Context.** On 2026-09-08 a running server (operator trace
`ghostdriver-20260908-72116.jsonl`) answered its first call, then failed
every call for five hours with `AssertionError: {'disclosure'}` from the
backend contract guard. No session could be opened. The `disclosure`
contract entry had landed in the tree while the server ran, and the hot
reloader (D68) had taken a generation that did not fit it.

**The mechanism, which D68 did not cover.** `_rebuild` purged the
reloadable modules and called `build()`, which imports `ghostdriver.tools`
and constructs the toolbox -- but the *backend* is imported lazily, at
call time (`from ..backends import current`), not by `build()`. So a
rebuild was accepted whose backend had never been imported. When a stable
module also changed, the reloader then held the implementation at that
generation (the D68 hold), and the lazily imported backend read the *new*
file against the *held* contract. The import raised, was never cached, and
raised again on every call. D68's promise -- "an edit that does not import
leaves the previous generation in place" -- held, but the generation it
kept was incomplete, so the promise bought nothing.

**Decision.** A rebuild imports every module it purged before accepting
the new generation. An import that fails anywhere fails the whole rebuild,
the modules the failed generation managed to load are purged again, and
the working generation is restored intact -- reported as `error` + `kept`,
exactly as a syntax error already was. A generation is whole or it is not
taken. And a tool result that is an exception *while the implementation is
held* now re-attaches the held note, because the held event was surfaced
once on an earlier result and the call that actually fails for it would
otherwise read as a bare traceback name.

**Evidence.** `test_a_rebuild_imports_what_the_old_generation_had_loaded`
builds a package whose implementation imports its backend lazily, breaks
the backend, and asserts the rebuild is refused with the old backend still
answering -- the 10:10 failure, reproduced and now caught.
`test_a_rebuild_that_can_import_its_backend_is_taken` holds the happy path,
and `test_a_call_that_raises_while_held_says_the_implementation_is_held`
covers the note. This is a `env: any` fix: the reloader is platform-neutral
and proven on a scratch package, never by editing the repo under a running
test (D68).

**A note on the session cost.** Consent survives a restart in the operator
directory, so recovering from a lost session is one `attach` (D65, D66).
The five-hour outage was not the session loss; it was that the server
stayed up and broken, answering nothing, with a message that named the
symptom (`AssertionError`) and hid the cause. The fix is that it no longer
stays up broken: the reload is refused and the previous generation keeps
serving.

### D#71. An `expect` the tool cannot read is refused, not quietly dropped

**Context.** `expect` is the difference between a result that claims the
input was delivered and one that claims it worked (D67, D77). The field
notes recorded that the schema "tripped me once and I stopped trying" --
and the tool's own behavior rewarded stopping: `_expectation` returned "no
expectation" for any dict without a `locator` or `changed` key, so
`expect={"text": "Saved"}` verified nothing and the result read
`delivery_only`, identical to never having asked. A caller who mistyped the
one key that carries the verification was told, in effect, that they had
not asked for one.

**Decision.** `parse_expect` is the single gate every actuation runs its
`expect` through, and it refuses rather than guesses (D33). A dict is
checked before anything is sent: an unknown key is an error naming the keys
that exist (`locator`, `text`, `selected`, `changed`, `timeout_s`,
`all_windows`), and a dict with neither `locator` nor `changed` is an error
naming what a usable expectation needs. A bare string stays a locator (the
D67 affordance), and a string that is actually a serialized object -- a
client that JSON-encoded the dict before sending -- is parsed back into the
object it was, rather than being read as a locator that cannot resolve.

**Evidence.** `test_an_expect_with_no_usable_key_is_refused_by_name` and
`test_an_expect_with_an_unknown_key_is_refused_by_name` assert the refusals
and that nothing was sent; `test_an_expect_sent_as_json_text_is_read_as_the_object_it_was`
covers the serialized-dict case. The refusal travels the same path a
mistyped locator already did (`expect is unusable: ...`), so a caller sees
one consistent shape for "your expectation is malformed" whether the fault
is the key or the locator inside it. `env: any`: pure policy, proven on the
fixture.

### D#73. `timeout_s` widens the verify window for any expect, not only `changed`

**Context.** The 2026-09 field loop, ~16 tool calls per operation. One
result kept coming back wrong: a `click` whose `expect` named a dialog or
the Embed popup, reported failed while the *same result's* `disturbances`
showed the window had opened. It cost a retry call every time.

**The bug.** The actuator polls a postcondition to a deadline, not a single
sample -- `VERIFY_TIMEOUT_SECONDS = 2.0` plus the settle, ~2.4s (D48). The
`click` tool extended that deadline only when the expect was `{changed}`
(to `timeout_s`, default 6, for a palette that docks seconds later, D77). A
**locator** expect that carried `timeout_s` had it silently dropped, and
`set_value` / `type_text` / `send_keys` passed no window at all. So a caller
who saw a dialog appear slower than 2s and raised `timeout_s` to say so was
ignored, and D48's false-failure -- the very thing the deadline exists to
prevent -- returned through a parameter that looked like it should prevent
it.

**Decision.** A shared `verify_window(expect)` reads `timeout_s` from any
expect and all four actuation tools pass it to the actuator. A `{changed}`
expect keeps its 6s default; a bare locator keeps the actuator's 2s default
unless `timeout_s` is given. The postcondition is unchanged -- this only
governs how long it is *given* to become true.

**Evidence.** `test_a_caller_can_widen_the_verify_window` drives an effect
that arrives at 5s: verified under `timeout_s=8`, and the same effect shown
to fail under the 2s default, so the test proves both the fix and that it
was needed. `test_verify_window_reads_timeout_s_from_any_expect` covers the
helper's table. `env: any`: the actuator is platform-neutral and runs on an
injected clock (D48), so the deadline logic is exercised without waiting.
