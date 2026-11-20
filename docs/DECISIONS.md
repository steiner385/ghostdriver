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

**Version-dependent (D#219):** this was GTK 4.14.5. GTK 4.22.4 masks both
widgets, and GTK 3.24.52 masks a hidden entry *and* gives it the role
`password text`. The policy below stands, because a target may run the
older GTK.

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

### D#40f. Slice 5b: a claim, not a bind -- `Atspi.init()` has no second bus

**Context.** `docs/LINUX.md` proposed the nested-display mechanism and, for
`HiddenDesktop`, a shortcut Windows does not have: "no thread binding needed
-- the display is an environment variable." Slice 4a's finding that tier 4
had nowhere safe to run was blocking on this being built. It was measured
before being trusted, and the shortcut turned out to be half right.

**The half that holds: X11 has no equivalent of `CreateDesktopW`'s
per-thread bind, and does not need one.** An `Xlib.display.Display()` is a
plain object; nothing in Xlib stops a process holding two, one per
`DISPLAY`. `display.py`'s single `_DISPLAY` slot was rewritten to a cache
keyed by claimant (`desktop_claim.effective_owner()`) rather than one
global, and that alone is sufficient for a process to read the operator's
own display and a nested one in the same lifetime.

**The half that does not: AT-SPI is a process-wide singleton, and there is
no route around it.** Three things were tried against two real nested
buses (`Xvfb` + a private `dbus-daemon` + `at-spi-bus-launcher`, each pair
carrying a distinct copy of the GTK fixture so which bus answered was
unambiguous, not just which bus was reachable):

1. **Reconnect.** A second `Atspi.init()` after changing every relevant
   environment variable (`DISPLAY`, `DBUS_SESSION_BUS_ADDRESS`,
   `AT_SPI_BUS_ADDRESS`) does not reconnect. It is idempotent at the C
   library level and keeps answering from the bus the first call reached.
2. **Fork.** A forked child that changes its own environment and calls
   `Atspi.init()` still reports the parent's application, not its own --
   the live D-Bus connection is inherited across the fork regardless of the
   child's environment, because the C library's connection object, not
   Python's module state, is what got duplicated.
3. **`Atspi.exit()` then reconnect.** Documented as the deliberate reset,
   and it is not one: the next `Atspi.get_desktop(0)` raises through a GLib
   assertion (`g_hash_table_insert_internal: assertion 'hash_table !=
   NULL' failed`) rather than returning a working connection to the new
   bus. `exit()` tears the library's state down; it does not free it for
   reuse.

**So `run` does not marshal work onto a bound context the way Windows'
does, because there is nothing to marshal onto -- a process that has
reached one accessibility bus can only ever reach that one, for the rest of
its life, no matter which thread, fork, or environment asks.** The design
question this leaves is not "how does a call reach the right bus" but "how
does a process find out, before it launches a target onto a display it can
then never read from, that it has already spent its one bus on something
else." `desktop_claim.py` is that: a single claim, taken by whichever of
`display.py`'s or `tree.py`'s connection-opening code runs first, naming
`"the operator's own desktop"` by default or a `HiddenDesktop`'s own name
inside `desktop_claim.desktop(name)`. A second, different claimant is
refused immediately, with the measurement above in the refusal, rather than
being left to read a target's tree and silently get the wrong one back
(D33: refuse ambiguity rather than picking; D53: a target the strategy
cannot fit is reported as such).

**`HiddenDesktop.run` is consequently almost nothing: a context manager
around `fn()`.** Once `prepare()` has claimed the process and the nested
`DISPLAY` / `DBUS_SESSION_BUS_ADDRESS` / `AT_SPI_BUS_ADDRESS` are set, every
ordinary contract function -- `enumerate_process`, `read_window_text`, and
the rest -- reaches the nested display and bus on its own, because they are
the only ones this process can reach at all. `desktop_claim.desktop(self.
name)` exists so those calls are *recognised* as the claim already held
rather than a conflicting second one, not so they are *routed* anywhere.

**A consequence worth stating plainly: the claim never releases.**
`teardown()` stops the nested display's processes but does not, and cannot,
give the process back its ability to reach a different accessibility bus --
that ability was never something `HiddenDesktop` held to begin with, per
the measurement above. A server process that has ever launched one hidden
desktop has spent its one bus for the rest of its life; a second
`launch_isolated` call, or any ordinary session, correctly refuses rather
than silently reusing the first desktop's tree.

**Also built:** `gnome-shell --x11` under the private bus (D75's window
manager requirement, mirrored from measurement 1's nested-bus proof in
`tests/test_linux_atspi.py`), polled via a new `display.wm_present()`
(`_NET_SUPPORTING_WM_CHECK`) rather than a blind sleep; and `OperatorNotice`
as an override-redirect X window with `_NET_WM_STATE_ABOVE`, drawn with the
server's own `fixed` font rather than a toolkit, since it is the one piece
of this backend that draws instead of reading and pulling in GTK for one
window would be a large dependency for a small one.

**Not done in this slice.** `region_evidence`, `resolve_hosted_app`,
`assess_uia`, `assess_msaa` (slice 6) wait on the embedded-document
measurement (#15) and a decision about what UIA/MSAA richness becomes with
no Linux counterpart. Routing tier 4's ladders in `verbs.py` through
`HiddenDesktop` now that it exists is a follow-on, not part of this slice --
D#40e's empty tier-4 rungs are unchanged here.

Evidence: #40 slice 5b; D#8; D#9; D33; D53; D75; D#40e; issue #40.

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

### D#75. A batch tool: one call, many steps, each with its own verdict

**Context.** The 2026-09 field loop ran ~16 tool calls per operation, and
~12 of them were perfectly predictable -- click a tab, set a field, press
Ok, click a row, embed, save. Each cost a round trip. Computer use has
`computer_batch` for exactly this; ghostdriver had nothing, so the
deterministic stretch of every loop paid the latency of a network hop per
step.

**Decision.** `batch(session_id, steps, stop_on_failure=true)` runs a list
of `{tool, args}` steps in order against one session. Each step carries its
own `expect`, so its verdict is real rather than "sent"; the first step
that does not verify stops the batch (a loop's steps depend on each other),
and the result reports how far it got with every step's verdict.
`stop_on_failure=false` runs them all, for a batch of independent reads.

**It is only a dispatcher, and that is the whole safety argument.** A step
calls the same `Toolbox` method a standalone call calls, through the same
`authorize`, denylist and tier checks -- the batch adds no path around any
of them and grants nothing a step could not already do. So the batchable
set is an allowlist of the session-scoped read-and-act tools, and never the
lifecycle or consent tools (`attach`, `release`, `grant_*`,
`launch_isolated`) or the two that interrupt a person (`foreground`,
`await_human`): a batch drives an already-approved target, it does not
change what is approved or wait on a human. Placed at the `read_only` tier
for the same reason -- a read-only session's batch runs its reads and its
act steps are refused per step, exactly as the standalone calls would be.

**Evidence.** `tests/test_batch.py`: the happy path with per-step verdicts,
a step without an expect claiming only delivery, stop-on-failure and its
inverse, the allowlist refusing each lifecycle/consent tool before anything
runs, a step forbidden from carrying its own session_id, malformed steps
refused by shape, a bad-argument step failing as a step rather than
crashing the batch, and a read-only session's act step refused inside a
batch. `env: any`: the dispatcher is platform-neutral; the fixture supplies
the target the steps act on.

### D#76. A pace primitive, named as the stopgap it is

**Context.** `wait_idle` refuses without a profile `busy_indicator` (D69),
and rightly -- it has nothing to wait on. But a hybrid loop against a target
with no indicator declared yet still needs to let the screen catch up, and
what it reached for was `wait_for` against a locator built never to match,
run as an N-second timer. That is a wasted call and, worse, a lie about
what is being waited for.

**Decision.** Add `pace(session_id, seconds)`: a bounded dwell, clamped to
120s, that returns and in its own result names the better tool -- a declared
`busy_indicator` with `wait_idle`, or `wait_for` on a control that will
appear. Both wait on the target; `pace` waits on the clock, and says so.

**Recorded as a deliberate exception.** This server's stance is against
arbitrary sleeps (D45), and `wait_idle`'s refusal is part of that stance.
`pace` is a considered exception, not a drift past the rule: it exists for
the gap *before* an indicator is declared, it points every caller at the
measurement that would replace it, and it is capped so it cannot become a
place to park a run. The profile `busy_indicator` remains the right answer
where a target has an indicator -- VendorApp's status strip is one, pending the
capture pair that measures it. Chosen by the project owner over keeping the
`wait_for`-as-timer workaround, with the tradeoff recorded here on purpose.

**Evidence.** `tests/test_batch.py` covers the dwell timing, the clamp (with
`PACE_MAX_S` shortened so the test does not wait the cap), the pointer to
`wait_idle`/`wait_for` in the note, and the refusals of a non-positive or
non-numeric dwell. `read_only` tier: a fixed wait changes nothing. `env:
any`.

### D#79. The session argument is `session_ref`, because `session_id` collides with the protocol

**Context.** A session driving ghostdriver reported that every tool taking a
`session_id` failed at once with `session_id Field required [type=missing]`,
even when it was passed -- while `list_targets`, `attach` and `grant_targets`
(no `session_id`) worked. In a failing `find`, `locator` and `all_windows`
arrived and only `session_id` was gone: stripped in transit, not forgotten.

**Diagnosis, from the code and the server's own dispatch.** The server was
correct on every count. The tool schema published `session_id` in both
`properties` and `required`; `call_tool("modals", {"session_id": "x"})`
reached the handler while `call_tool("modals", {})` reproduced the exact
error; and the SDK does not strip tool arguments by name -- proven by the
first of those two calls. What the SDK *does* have is a connection-level
property named exactly `session_id` on its request Context
(`ctx.connection.session_id`, `None` on stdio). So a client that manages the
protocol's own `session_id` conflates it with a tool argument of the same
name and drops it before sending. The bug was never in this repo; the tool
argument's *name* collided with an MCP protocol field.

**Decision.** Rename the exposed session parameter across every session tool
from `session_id` to `session_ref` -- a name that cannot collide. MCP clients
are schema-driven, so a compliant client reads the new name and sends it; no
client that honors the schema breaks. The change is confined to the tool
wrappers in `mcp_server.py`: the `Toolbox` methods keep `session_id`
internally, and `attach`'s result still returns `session_id` (an output, and
outputs are not stripped), so the value a caller reads from `attach` is
passed straight back as `session_ref`. The `SessionId` field description
states the mapping.

**Evidence.** `test_no_tool_exposes_a_parameter_named_session_id` fails if any
tool ever publishes a `session_id` argument again; the existing schema and
round-trip tests were moved to `session_ref`; and the batch step guard now
refuses either name in a step's args. `env: any`: the rename and its guard
are platform-neutral, proven through the server's dispatch and over real
stdio. Root cause is client-side, but the fix that removes the collision
lives here, so it lives here.

### D#83. One execution core, shared by `batch` and the macro runner

**Context.** `batch` (D#75) carried the loop that makes a list of tool calls
safe to run as one: the allowlist, the refusal of a step that carries its own
session, the per-step dispatch, the bad-argument-is-a-step-failure rule, the
per-step verdict, and stop-on-first-failure. The macro runner (#81, #87) needs
exactly that loop. Two copies of a safety model is one copy too many -- the
day they drift, one of them is wrong and nobody notices (the pattern D#39
named).

**Decision.** The loop lives in `stepper.run_steps(toolbox, session_id, steps,
*, stop_on_failure, context)`, and `batch` is a thin caller: it authorizes
*itself* as the `batch` tool, then hands the run to the core. The macro runner
will authorize itself as `macro_replay` and hand its resolved body to the same
core. The core authorizes nothing -- each step's own tool method authorizes
the session again, which is the whole point: the core adds sequencing, never a
path around a tool's own checks. `context` ("batch", "macro") only names the
caller in the wording of a refusal.

**A pure refactor, and held to it.** `batch`'s public result is unchanged
byte-for-byte, proven by `tests/test_batch.py` passing untouched against the
fixture. The allowlist moved verbatim (renamed `BATCHABLE` -> `RUNNABLE_TOOLS`,
no external caller referenced the old name) and now has a guard test naming
what it must and must not contain. The core is pure with respect to the
desktop -- it calls methods on a toolbox handed in -- so it is proven with a
fake toolbox in `tests/test_stepper.py` and needs no fixture (`env: any`),
the same split the workflow runner already uses.

**Not changed.** The tier model is unchanged: the core does not check tier,
because each step's tool method does, per step, which is what lets a
read-only session's batch run its reads and refuse its act steps (D#75). This
is the foundation the rest of v1 (#84-#88) builds on.

### D#84. The workflow format becomes the macro format, and refuses what it cannot read

**Context.** Macro v1 (#81) needs a file format, and `workflow.py` already
had most of one -- steps, dotted-path assertions, a runner, a report. Rather
than a second format that drifts from the first, the macro format *is* the
workflow format, extended. This slice is the data model and its validation
only; binding params and evaluating branches is #85.

**Decision.** Four additions, each earning its place:

- **`params` and `provenance`** on the workflow. A macro that embeds a
  specific id is a screenshot; one that declares `${plan_id}` and binds it at
  replay is a tool. Provenance records `recorded_against` (a profile id) so
  replay can be honest that a macro recorded on one target class means nothing
  on another.
- **`verified` and `delivery_only`** on a step. The honesty rule made
  structural: a recorded step says whether it carried a postcondition that
  held, and an offset click on a painted region is flagged as the least
  replayable thing a macro can hold (D66) rather than passed off as a control.
- **A `when` branch node.** `steps` is now a tree of leaves and branches
  (`Node = Step | Branch`), one v1 control-flow form; loops and handlers are
  v2/v3 (docs/MACROS.md). Conditions are `Guard`s in the locator/`expect`
  vocabulary -- never embedded code, so the whole macro stays inspectable and
  denylist-checkable.

**The loader refuses what it cannot read.** Unknown keys on a step, branch,
guard, param or provenance are errors naming the allowed set (D33), the way
`expect` refuses one (D#71) -- a typo that silently drops an assertion is the
footgun the format exists to close. Nesting is bounded (`MAX_NEST_DEPTH`), the
same instinct as `pace`'s cap: a macro too deep to read at a glance is
refused. Every existing workflow still loads unchanged, with empty params and
provenance.

**Held to model-only.** The linear `run_workflow` does not execute a branch;
it fails clean with a pointer to #85 rather than crash, so a branch reaching
it is a plain error, not a traceback. `env: any`: the model and its refusals
are proven with `Workflow.from_dict` in `tests/test_workflow.py`, no fixture.

### D#85. Macro control flow: params bound or refused, a branch read not guessed

**Context.** #84 gave the format params and a `when` branch; this makes them
run. The behaviors are small but the principle they must not break is the
whole project's: a macro adds sequencing and choice, never a way around a
tool's own checks, and it refuses ambiguity rather than picks (D33, D35).

**Decision.** `run_macro_body` walks the node tree against one session:

- **Params are bound or the run is refused.** `${name}` is substituted into a
  step's args (and a guard's locator), preserving type -- a value that is
  exactly `${x}` keeps its binding's type, so `at: {x: ${x}}` binds a number.
  A required param with no binding, or an unresolved `${name}`, refuses the
  whole run naming what is missing. A macro never guesses a value.
- **A branch is read from the target, never guessed.** A `when` condition is
  evaluated by `find`: presence, or `absent`, with `text`/`selected`/`pressed`
  refining a present match. A condition that cannot be evaluated -- an unbound
  locator param, a failed read, or a `pressed` state the control does not
  expose yet (#77) -- refuses the run rather than silently branch false. That
  last case is the honest one: a funnel whose pressed state is unreadable must
  say so, not take the else arm by accident.
- **The safety model carries through.** Each leaf goes through the shared gate
  factored out of `batch` (`stepper.step_refusal` + `call_tool`, D#83): the
  same allowlist, the same refusal of a step carrying its own session, the
  same tier enforced per step by the tool method itself. A withheld tool
  refuses the whole macro. A leaf's dotted-path assertions are the workflow
  `check()` it already had; a failing assertion stops the run (or not, under
  `stop_on_failure`).

A refusal (`refused` set) is a macro-authoring or binding error and aborts;
a leaf assertion failure is an ordinary stop. The two are kept distinct in
the result so a caller can tell "this macro is wrong" from "the screen was
not what it expected". Tree paths ("1.then.0") place a failure exactly.

**Held to evaluation-only.** `run_macro_body` is pure with respect to the
desktop -- toolbox handed in -- and proven with a fake in
`tests/test_macro_runner.py` (`env: any`). Attach, the interference watch and
the report are `macro_replay`'s (#87), which wraps this core. The `batch`
extraction is behavior-preserving, proven by `test_batch.py` and
`test_stepper.py` staying green.

### D#86. Macros are workflow files, and their lifecycle is operator bookkeeping

**Context.** Macro v1 needs somewhere to keep a macro and the verbs to manage
one. A macro is a workflow file (D#84), and the operator directory already had
a `workflows/` folder with a loader. So macros do not get a second store or a
second format: they *are* workflows, and `macro_save/list/show/delete` operate
on the same files.

**Decision.** Four tools, and they are session-free -- like `list_targets` and
`grant_targets`, they touch the operator directory, not a target, and take no
`session_ref`. Placed at the `read_only` tier so the tool surface and the tier
table still name the same set (the contract that a tool no tier permits cannot
exist), even though, being session-free, none runs the per-session tier check.

- **`macro_save`** validates through `Workflow.from_dict` before it writes, so
  a malformed macro is refused at save, not discovered at replay. It reports
  `replaced` when it overwrites, so a save that modifies is never silent
  (modify is re-save; a structured-edit tool would be a worse editor than a
  text editor).
- **`macro_show`** surfaces the provenance and each step's `verified` /
  `delivery_only` flags -- the honesty a reader needs before replaying, so a
  macro full of blind offset clicks cannot hide as a clean sequence.
- **`macro_delete`** archives rather than destroys: the macro leaves the
  listing but stays recoverable under `workflows/.archive/`. Deleting operator
  data the tool did not create is a thing to be able to undo (the look-before
  rule); a `glob("*.json")` listing does not descend into the dot-folder, so
  the archive stays out of the way.
- Every verb without an operator directory says so plainly (D10), rather than
  writing into a virtualized path the operator's shell cannot see (the trap
  D65 was built around).

**Held to bookkeeping.** No tool here attaches, actuates, or reads a target.
Replaying a macro is `macro_replay` (#87), which wraps `run_macro_body`
(D#85) with attach, the watch and the report; recording one from a live
session is `macro_record` (#88). `env: any`: the tools are proven against a
temp operator directory in `tests/test_macro_tools.py`, no fixture.

### D#87. macro_replay: the operator's attach is the consent, and a dry run is always safe

**Context.** The macro runner (D#85) evaluates a body; the CRUD tools (D#86)
keep one. `macro_replay` joins them into the verb that makes the feature
usable: run a saved macro against a live target, verified, watched, reported.

**Decision.** `macro_replay(session_ref, name, params, dry_run)` runs against
an **already-attached session** rather than attaching itself. The operator
approved the target and chose its tier by attaching; replay inherits that
consent and runs the body through the shared core (D#85) -- every step the
same checks a standalone call gets -- under the interference watch a workflow
run uses, so a foreground the target takes mid-run fails the run whatever the
steps said. It is a `read_only`-tier tool like `batch`: each step re-checks
its own tier, and the macro's *declared* tier is checked against the session's
up front, so a macro that needs `interactive` on a `read_only` session fails
fast with the reason instead of midway.

Three judgment calls, each in the project's grain:

- **A dry run inspects, and is never gated.** `dry_run` resolves params and
  returns the plan without acting -- and is allowed below the macro's tier and
  with params still unbound (they are *marked*, not refused). Looking at what
  a macro would do must be safe from any session; the refusals are for the run,
  not the look. A branch in the plan shows *both* arms, because its condition
  is read from the screen the previous step leaves -- a plan cannot resolve it
  without acting, and says so (docs/MACROS.md open questions).
- **A real run binds or refuses (D33).** A missing required param stops the
  run naming what is missing; a macro never guesses a value.
- **A profile mismatch warns, not refuses.** `provenance.recorded_against` is
  compared to the session's `profile_id` (now carried on `Profile`); a
  mismatch is a warning that a locator from one target class may mean nothing
  on another -- the run proceeds and the steps are watched, because only a
  locator that actually fails to resolve is grounds to stop.

Replays from the start and reports where it stopped; a report lands in the
operator directory. Resume is deferred.

**Evidence.** The logic -- binding, the dry-run plan, the tier gate, the
profile warning, the error paths -- is proven against a backend-free session
(`SessionManager.attach`, no target) in `tests/test_macro_replay.py`, so it
runs on any platform; the one end-to-end run against the fixture is the single
Windows-only test there. `env: any` for all but that.

### D#88. Recording captures the doing, only when it succeeds, and flags what it could not confirm

**Context.** The last of macro v1 (#81): turn what an agent just did into a
macro, without a person hand-writing JSON. The hard part is capturing *intent*
honestly on a target where a click can be verified or blind and the durable
unit is a locator, not a coordinate.

**Decision.** `record_start` opens a buffer for a session; every actuation on
that session is captured as a macro step as it happens; `record_save` writes
the buffer as a macro (with provenance) and `record_discard` throws it away.
Three rules make the capture honest rather than a keystroke log:

- **Only the doing.** The recorded set is the actuations and the two waits --
  not the reads (`find`, `read`, `describe`, ...) the agent used to *decide*.
  A recording is the macro, not the exploration around it, so it replays
  clean. A successful wait is captured as verified: the condition it named
  actually held.
- **Only what succeeded.** A call that did not return `ok` is never buffered.
  This is where the secret boundary lives for free: typing characters into a
  protected field is already refused, so it never returns ok, so a typed
  credential is never recorded -- and the credential path stays `await_human`,
  which never carries the value.
- **Flag what could not be confirmed.** Each step records `verified` (its
  `expect` held) or `delivery_only` (an offset click on a painted region, or
  an actuation with no postcondition). An offset click is `delivery_only`
  whatever its verdict, because a coordinate can never be re-confirmed by
  locator (D66). Nothing is dropped -- losing an action would produce a macro
  that replays wrong -- but `record_save` reports how many steps are
  `delivery_only`, so a recording is never sold as more certain than it is.
  "Verified steps only" is satisfied by construction: every recordable ok
  step is either verified or flagged, and both are kept.

**The seam.** Capture rides on the one wrapper every tool result already
passes through (the trace/watchdog seam), so no tool has to know it is being
recorded; the cost when nothing is recording is a single dict lookup. The
buffer lives on the toolbox (carried across a dev reload) and a refused save
puts it back rather than losing it.

**Evidence.** `capture_step`'s rule (what records, how it is flagged) and the
`record_start`/`save`/`discard` lifecycle are proven against a backend-free
session in `tests/test_macro_record.py` (`env: any`); one Windows-only test
records a real click against the fixture, confirms the read beside it was not
recorded, and reads the macro back. This closes macro v1: record, replay,
modify (edit the file), delete -- of parameterized linear-and-branch macros
(#83-#88). Loops and reactive handlers are v2/v3 (docs/MACROS.md).

### D#97. Macro loops: bounded, checked, and honest about not finishing

**Context.** Macro v2 (#81). A linear-plus-branch macro cannot express the two
shapes the real work is full of: page a grid until a value appears, and do the
same thing to every row. Loops add them, and the risk they add is the one the
project is most careful about -- a run that never ends.

**Decision.** Two loop nodes, evaluated by `run_macro_body` through the same
core every step already goes through, so a loop's body is not a way around a
tool's checks.

- **`repeat_until`** runs its `do` *while the condition does not hold*, checked
  **before** each iteration -- so an already-satisfied condition runs the body
  zero times, which is what "page until the value is visible" wants. `max` is
  **required and capped** (`MAX_ITERATIONS`): a macro cannot spin, the same
  instinct as `pace`'s cap (D#76). Reaching `max` without the condition holding
  is a **failure**, not a silent stop -- the loop did not achieve what it
  named, and says so.
- **`for_each`** runs its `do` once per item in a list, binding the loop
  variable (referenced as `${var}` in the arm), the list either inline or a
  `${param}` that resolves at run time. An `in` that resolves to something
  other than a list, or a list past the ceiling, is refused (D33) rather than
  guessed or run away with.

Loops nest under the existing depth bound, and a condition that cannot be read
refuses the loop exactly as a branch's does (D#85) -- honesty over a guess. The
linear `run_workflow` fails clean on a loop it cannot execute, as it does on a
branch.

**Not recorded.** `macro_record` still captures only linear actuations (D#88);
a loop is authored, not recorded, in v2. Reactive `on_disturbance` handlers
remain v3.

**Evidence.** Parsing and its refusals in `tests/test_workflow.py`; evaluation
-- the zero-iteration case, stopping when the condition holds, the max-reached
failure, per-item binding, a non-list `in`, an unreadable condition, and a body
failure stopping the loop -- in `tests/test_macro_runner.py`, all with a fake
toolbox (`env: any`).

### D#106. Reactive handlers: named, bounded, and unable to do what a step could not

**Context.** Macro v3, the last phase and the one the spec held back on
purpose: a macro that reacts to the UI. The value is real -- dismiss the
connection-lost dialog that froze the app in D20/D48 and carry on -- and so is
the danger: a thing that acts on its own reading of the screen is the opposite
of "a measurement never overrules the person" (D28, D35). So the design is
small, and every part of it exists to keep a reaction inside what the operator
already authorized.

**Decision.** A macro may declare `handlers`, active for the whole run:

```json
{"on_disturbance": {"window": "class=TConnLostDlg"},
 "handle": [ ... ], "then": "retry", "max": 3}
```

- **Named, never a wildcard.** A handler fires only for the window class the
  operator wrote. `*` (or `class=*`) is refused at parse. A handler reacts to a
  case a person named, not to anything that appears.
- **Its actions are ordinary steps.** `handle` runs through the same core every
  leaf does (`step_refusal` + `call_tool`, D#83): the allowlist, the per-step
  tier, the denylist enforced in the tool. A handler can click nothing a live
  call could not, and cannot take the foreground (not on the allowlist).
- **Bounded.** Each handler has a capped `max` firings; past it the run stops
  with the reason rather than dismiss-and-retry forever. `then: retry` re-runs
  the interrupted step (the connection-lost case: dismiss, then retry the click
  the dialog blocked); `then: continue` (default) proceeds. A handler's own
  steps do not re-trigger handlers, so a reaction cannot recurse.
- **Visible.** Every firing is a step in the result (`on_disturbance[i]`,
  then the `handle` steps, then a `retry[n]` of the interrupted step), so a
  reaction is never silent.
- **Checked after an actuation only** -- a dialog appears in response to an
  action, not a read -- and by an ordinary `find` for the named window, which
  is itself a safe read.

**A structural choice the spec left open.** The spec sketched `on_disturbance`
inline among the control-flow shapes; it is instead a **top-level `handlers`
list**, because a handler is a property of the whole run, not a point in the
step sequence, and inline registration would be order-dependent and confusing.
Recording does not capture handlers (D#88); they are authored, like the loops.

**The test the design has to pass** (docs/MACROS.md): a reactive macro can do
nothing an operator watching the screen could not have authorized in advance by
naming the case. Named windows, allowlisted actions, bounded firings, visible
reactions -- each is one clause of that promise.

**Evidence.** Parsing and its refusals (no on_disturbance, a wildcard window,
no handle, a bad `then`/`max`, over the ceiling) in `tests/test_workflow.py`;
evaluation -- a handler firing and retrying, not firing when absent,
`continue` vs `retry`, the max-firings bound stopping a persistent
disturbance, and a handler step held to the allowlist -- in
`tests/test_macro_runner.py`, all with a fake toolbox (`env: any`). This
completes the macro roadmap (#81): v1 record/replay/delete, v2 loops, v3
reactive handlers.

### D#108. A None on the wire is "not given", and a fake that never sends one proves nothing about it

**Context.** The first live shakedown of the macro recorder, against the VendorApp
sandbox. Two tab switches, each verified `effect`, were recorded
`verified: true` **and** `delivery_only: true` -- a contradiction -- and their
args carried every default the wire sent (`at: null`, `modifiers: null`, ...).

**What was wrong.** The MCP layer calls each tool passing every parameter
explicitly, defaults included, so `at=None` reaches the wrapper's bound args
as a *present* key. `capture_step` tested `"at" in args` -- presence -- and
so flagged a verified click as an offset click. Every fake-toolbox test built
its `bound` dict by hand and never included `at=None`; the real path always
does. The tests were faithful to a shape the wire never has -- the same class
of gap D#39 named: a check that cannot run where the failure happens.

**Decision.** Capturing drops None-valued args (a None is "not given"; the
macro records what was asked, not the defaults the wire carried) and tests
`at` by value, not by key. The regression test is built from wire-shaped
bound args, so it fails the way the sandbox did.

**Also seen, and correct.** The replay's interference watch reported ~55
`cursor_moved` events -- the operator's own mouse during the run -- and no
`foreground_taken`. Reported, not judged (D28); the run passed. The rest of
the shakedown held: record, save, `dry_run`, and a real replay that re-ran and
re-verified both switches against the live target, with a report written.

### D#112. A macro result says what held *now*; a recording keeps only what was asked

**Context.** Two readability findings from the live shakedowns against the VendorApp
sandbox, both about the same thing: a recorded or replayed macro should show a
reader what matters and nothing that obscures it.

- A hand-authored `for_each` replayed with every step `ok` and no failures --
  its `expect` held on the live target -- yet each step read `verified: false`.
  Correct by the format's definition (`verified` means *held when recorded*,
  D#84/D#88; an authored step is never recorded) and still misleading: a reader
  scanning for "did it verify?" sees `false`.
- After the #108 fix a recorded click's args were correct but still carried the
  wire's non-null defaults (`all_windows: false`, `button: "left"`, `count: 1`,
  `frame: "logical"`, `require_active: false`) beside the two args actually
  asked for. A None-strip cannot tell `button: "left"` from a deliberate choice.

**Decision, in two parts.**

- **`held`, the runtime verdict, as its own field.** Each replayed step now
  carries `held: true` when its own postcondition held on *this* run (the
  tool's `effect`/`committed`/`display` verdict; a wait that returned ok held by
  construction; a read has no postcondition and never claims to), beside the
  unchanged static `verified` and `delivery_only`. A result answers both
  questions -- "confirmed when recorded?" and "confirmed just now?" -- without
  conflating them. `dry_run` shows only the static flags, since nothing ran.
  The verdict logic is one function, `held_on_this_run`, shared by the
  recorder (where it sets `verified`) and the runner (where it sets `held`), so
  the two cannot drift.
- **A recording drops an arg equal to the tool's own default.** The wrapper
  already holds each tool's signature; its defaults are handed to the capture,
  which keeps exactly what was asked. Replay is unaffected -- an omitted arg
  takes the same default at run time -- so this is purely the readability a
  macro exists for. A non-default value is always kept, and a real `at` is
  kept and still flags `delivery_only`. Callers that pass no defaults get the
  #108 behaviour unchanged.

**Evidence.** `tests/test_macro_record.py`: only `locator` and `expect`
survive a wire-shaped click; a non-default value is kept; a real offset is kept
and flagged; no-defaults callers unchanged. `tests/test_macro_runner.py`: an
authored step is `held` but not `verified`; a delivered-only step did not hold;
a successful wait held; a read never claims to. `env: any`, fakes.

## Iteration 4 — the first real Linux target: Bambu Studio (wxGTK3, Flatpak)

*Measured on linux-host-a against Bambu Studio 02.08.02.61 (`com.bambulab.BambuStudio`,
wxWidgets-on-GTK3), on the operator's own X11 GNOME session on `:0`. These are
measurement decisions, in the tradition of D#8–D#14: they precede the
implementation they unblock, and they exist to be contradicted by the next
target. Every corner of the Linux fixture work so far was measured against
GTK **4**; this is the first measurement against a **different toolkit on the
same platform**, and it contradicts the GTK4 findings in three load-bearing
places.*

### D#101. A Flatpak target lives in three identifier spaces, and none of them is the pid a caller holds

**Context.** The task is to drive the operator's *running* Studio. Step one is
that `list-targets` shows it. It does not, and the reason is that a sandboxed
GTK application is not one process wearing one identity but three, and the
backend's two pid-consuming paths reach for different ones.

**The Flatpak a11y finding, confirmed.** `flatpak info --show-permissions
com.bambulab.BambuStudio` prints no `--talk-name=org.a11y.Bus`, yet
`Atspi.get_desktop(0)` lists it. The mechanism is not a permission at all: the
runtime injects `GTK_MODULES=gail:atk-bridge` and
`AT_SPI_BUS_ADDRESS=unix:path=/run/flatpak/at-spi-bus` into the sandbox, and an
`xdg-dbus-proxy` (the process pair `bwrap … xdg-dbus-proxy` shows) brokers the
a11y bus into it. So the accessibility route is open by default for a GTK
Flatpak, and `docs/LINUX.md`'s "Sandboxed applications" paragraph -- which
modelled this as a target the strategy cannot fit (D53) -- is wrong for the
commonest case. Corrected there.

**Three spaces, measured for two coexisting instances.**

| | operator Studio | scratch Studio |
|---|---|---|
| X window (`_NET_CLIENT_LIST`) | `0x680010b` | `0x7c0010b` |
| pid the X server attributes it to (XRes `LocalClientPIDMask`) = `psutil` real pid | **1461891** | **93102** |
| pid AT-SPI reports for the application node (`get_process_id`) | **1461887** | **93095** |

The a11y pid is the **proxy's**, one process off the real one, and it differs
per instance -- so instances are still told apart by `get_process_id`, exactly
as the earlier probe found, but that pid is *not* the one `psutil` or the X
server knows the application by.

**Two consequences the backend has to absorb.**

*Windows carry no `_NET_WM_PID`.* Every Studio top-level answers "not found" for
it. `display.windows_of(pid)` filters `_NET_CLIENT_LIST` by `_NET_WM_PID`, so it
returns nothing for Studio -- which silently empties `top_level_state`,
`snapshot`, the capture-by-frame path and the interference watch. The pid a
window belongs to has to come from the **XRes** extension
(`res.query_client_ids`, `LocalClientPIDMask`), which answered 1461891 and 93102
correctly, or from title+`WM_CLASS` correlation. `python-xlib` already ships
(D#40c) and carries `Xlib.ext.res`, so this is a wiring change, not a new
dependency.

*The correlation between the X window and the a11y tree is by title and size,
not pid.* The a11y frame's name equals `_NET_WM_NAME` and its
`get_extents(SCREEN)` size equals the X geometry (D#40d measured exactly this on
GTK4, and it holds here). So the two spaces are bridged the way `_xid_of`
already bridges them, and the real pid is never needed to *drive* the target --
only to *list* it and to key consent.

**What this leaves open, deliberately.** Which pid *is* the target, for
`attach` and for consent, is a policy decision that touches the shared session
model (consent is a process-tree fact, R5/D71, and the proxy and the app are
siblings under one `bwrap`, not parent and child). It is filed as its own fork
rather than decided in a measurement entry. Evidence: issue #101; `docs/LINUX.md`
sandboxed-app paragraph; D#40c; D#40d; D71.

### D#101a. The capture path is the one D#101 named and did not rewire

**Context.** D#101 listed four paths the absent `_NET_WM_PID` silently
empties: `top_level_state`, `snapshot`, the capture-by-frame path, and the
interference watch. Three were moved onto `display.windows_of` and the XRes
bridge. The fourth was not, and nothing went red, because every test that
captures anything runs against the GTK fixture -- which *does* set
`_NET_WM_PID`, being an ordinary unsandboxed process. The suite could not
see the hole because the hole only opens on a target the suite never uses.

**What was still there.** `reading._toplevel_xid` walked up to the frame,
took the pid AT-SPI reported for it, then forked `xwininfo -root -children`
and `xprop _NET_WM_PID` per candidate looking for a match. Against a Flatpak
target that is wrong in three separate ways, any one of which is fatal on its
own:

- no Studio top-level carries `_NET_WM_PID`, so every candidate compared
  `None` and nothing ever matched;
- the pid it compares against is the `xdg-dbus-proxy`'s, so even with the
  property present the two spaces would not have met;
- a pid cannot separate two windows of one process, so it returned the first
  -- and a control inside a modal photographed the window behind it.
  `tests/linux_xid_probe.py` wrote this one down in 2026 and it was never
  acted on.

So `capture` raised **"no X window behind this handle"** for a window that
was on screen, fully enumerated and already correlated. That message names
the one cause it was written for -- a control is an accessible with no
drawable of its own (D#8) -- so the failure reads as the caller asking for
the wrong thing rather than as the backend being unable to find a window it
had already found. A wrong answer wearing a right answer's error message is
worse than a crash, which is why this is an entry and not a patch.

**The decision: one bridge, and the tree owns it.** `tree._correlate_frame`
already resolves every frame to an xid at enumeration time, by accessible
name against `_NET_WM_NAME` and by size where the name alone is ambiguous
(D#40d), and it already tells `display` what it learned -- that call is what
fills the XRes aliases D#101 needs. It was exposed as `tree.frame_xid_of`
and left **with no callers at all**: the bridge was built, wired into
`display`, and never asked. `_toplevel_xid` now asks it, and the pid match
and both forks are deleted.

**Keying on the frame's path is what makes the modal case answerable.** Two
windows of one process are indistinguishable by pid *by construction* -- no
amount of care with the property would have fixed the third failure above.
They are trivially distinguishable by which frame node the handle descends
from, which is what `frame_xid_of` reads. The route that could answer the
question was chosen over the route that could not, rather than the broken
one being made more careful.

**A frame the tree declined to correlate stays declined.** `_correlate_frame`
resolves nothing when two windows share a name *and* a size, because from
here they are genuinely the same (D33). The capture then reports "no X
window", which is what it already said for a handle with no drawable -- the
two causes still share one message. That is a real loss of precision and it
is accepted for now: both answers are "this cannot be captured", and neither
invites a caller to act on a guess. Splitting them means a second error the
Windows backend has no counterpart for.

**Left open, deliberately.** `modality._xid_of` is still a *second*
correlation, re-derived live against `display.windows_of` rather than read
from the tree. It is correct -- it is the route this one was built from --
but two bridges can disagree, and the honest fix is to make modality read
the tree's answer too. That is a change to the modality contract with its
own measurement, and folding it into a capture fix would be smuggling it in.
Named here so the next implementer finds it rather than rediscovers it.

**Cost.** A capture no longer runs two processes to find its window; it reads
a dict. Evidence: issue #101; `tests/linux_xid_probe.py` (lines 16-21, which
named the pid-match defect before it was fixed);
`tests/test_linux_capture_bridge.py`; D#101; D#110; D#40c; D#40d; D33; D#8.

### D#102. On wxGTK3 the commit is a real Enter, and `grab_focus` both works and steals the foreground

**Context.** The whole safety model of driving a live target rests on D#11
(no tier 3 on GTK/X11) and D#13 (the operator's foreground never moves because
the target lives on a nested display). Studio breaks the second premise: it
*must* run on the operator's own display, because the point is to watch the
setting change in the Studio he is using. So the two questions that decide the
ladder had to be re-measured against wxGTK3, on `:0`, on a scratch instance.

**The commit is a real Enter, not a tier-1 write. Measured, deterministic.**
A scratch instance launched with `--datadir` into a temp copy, Prepare › Quality,
the Layer-height field resolved by screen position and its shown value, each
trial reset to a committed `0.12` by real keystrokes first:

| path | trials | Studio's own state changed (the preset gains its `*`) |
|---|---|---|
| `grab_focus` + `EditableText.set_text_contents` (tier 1) | 5 | **0** |
| `set_text_contents` alone (tier 1) | 3 | **0** |
| tier-1 write, then a real `Return` (tier 4) | 3 | **3** |

The tier-1 write changes only the *displayed* text; the readback reads back the
value it wrote, which is exactly why the earlier one-shot probe (task brief,
fact 6) read it as a commit -- a stale display mistaken for committed state. The
commit to Studio's own model fires on wx's Enter/kill-focus handler, which an
AT-SPI write does not travel through. **So on wxGTK3 there is no tier-1 commit,
and the value only reaches Studio through a real keystroke -- tier 4, on the
operator's own display.** That is the rung D9 excludes by default, and whether
to allow it is a consent decision (issue #103), not something to smuggle in.

**This inverts D#10 for this toolkit.** D#10 measured tier 1 on GTK4 as
*stronger* than Windows: `set_text_contents` went through `GtkEditable`, the
binding heard it, no D21 split. On wxGTK3 the binding does *not* hear it, so the
same call that committed on GTK4 does not commit here. D#10's "slice 4 should
use it as the tier-1 write path" holds only where the toolkit routes
`set_text_contents` through its own change handling, and wx does not. The
toolkit, not the platform, decides.

**`grab_focus` works here and steals the X foreground.** D#10 measured
`Atspi.Component.grab_focus` *raising* on a GTK4 `Gtk.Entry`. On wxGTK3 it
returns True -- and it moves `_NET_ACTIVE_WINDOW` to Studio: with a throwaway
window holding the foreground, a `grab_focus` on a Studio field pulled the
foreground to Studio (`0x880000a` → `0x7c0010b`). So it is not the harmless
in-process focus set D#11's tier-4 note assumed focus would have to be; it is a
focus steal. That is inside D#13 as *stated* -- the guarantee is that no window
*this tool launched* becomes the foreground, and the operator's own Studio is
his -- but it means the live-actuation path must not call `grab_focus` unless
the target is *already* the foreground, and must re-check before it does, or it
will yank a window the operator has tabbed away from back to the front.

**Why this is one decision and not two.** The commit needs the value in the
right widget and an Enter delivered to it; directing the Enter needs the widget
focused; focusing it is the foreground-stealing `grab_focus`. The three facts
are one mechanism, and the safety model for the live path (issue #103) has to
hold all three at once. Evidence: issue #102; `/tmp` measurement logs reproduced
on the scratch instance; D#10; D#11; D#13; D9; D21.

### D#110. A Flatpak target's canonical identity is its a11y application pid

**Context.** D#101 measured that a Flatpak lives in three identifier spaces
and that `list-targets` therefore could not show Studio. This decides which
pid a caller holds, because everything above the backend keys on one: consent
(R5, D71), `attach`, the session.

**The pid that reaches the tree wins.** `enumerate_process` filters the
accessibility bus by `get_process_id`, so the *only* pid that produces a tree
is the a11y application pid -- the proxy's, `1461887` for the operator's
Studio. The real process (`1461891`, what `psutil` and the X server know) can
be listed but cannot be driven, because no accessible carries it. So the
canonical identity is the a11y pid, and `list-targets` surfaces it: it walks
`psutil`, and for each window-owning process asks the bus what it calls
itself (`application_name`). The `xdg-dbus-proxy` process, which owns Studio's
a11y tree, is listed as **`bambu-studio`**, with its process name kept beside
it so a reader still sees what it really is.

**Consent still covers the process tree, and had to be taught the sibling.**
The proxy and the real process are *siblings* under one `bwrap`, not parent
and child, so `descendants(a11y_pid)` -- which the interference watch and the
consent walk both read -- would miss the real process the X server attributes
Studio's windows to. `descendants` now unions in `display.aliases(pid)`: the
real pids learned from the correlated windows (via XRes). Without it, the
watch would see Studio's own window take the foreground and not recognise it
as the target's -- a false alarm on the very guarantee the tool exists for.

**The window<->pid bridge is XRes, not `_NET_WM_PID`.** Every Studio
top-level answers "not found" for `_NET_WM_PID` (D#101), so `window_pid`
falls back to the X-Resource extension (`res.query_client_ids`,
`LocalClientPIDMask`), which returned the real pid where the property had
nothing. `python-xlib` already ships (D#40c) and carries `Xlib.ext.res`, so
this added no dependency.

**Rejected: canonicalise on the real pid and bridge to the a11y pid at every
call.** It reads more naturally -- the real pid is what a person sees in
`top` -- but it puts the correlation on the hot path of every tree read
rather than once at enumeration, and it still cannot drive a target the bus
does not answer for. The a11y pid is the one that works, so it is the one the
contract holds. Evidence: issue #101; issue #110; D#101; D#40c; D#40d; D71.

### D#111. Operator-present live actuation: tier 4, on the operator's own display, gated

**Context.** D#102 measured that on wxGTK3 a value reaches the application
only through a real Enter -- tier 4, which D9 excludes by default -- and that
`grab_focus` (needed to aim the Enter) raises the window to the foreground.
Driving Studio in the session the operator is watching needs all three, and
the safety model has to hold them at once. This decides the consent class the
task brief left open (issue #103, folded here).

**The decision: a per-session "live actuation" grant, resolved at attach.**
`attach(live=true)` is allowed only when a window of the target is *already*
`_NET_ACTIVE_WINDOW` -- the window the operator is looking at -- and records
its xid as the session's `live_window`. A live window that is not the
foreground now is a refusal, not a session that quietly cannot commit: the
result says to bring the window to the front and attach again. Live needs
tier `interactive` or higher, because a `read_only` session never actuates
and a live grant on one would authorise nothing.

**What the grant buys, and the guard that bounds it.** With it, `set_value`
offers a single **tier-4** rung: write the value through `EditableText` (no
input, no commit), `grab_focus` the field, press a real `Return` through
XTest. Every step is bracketed by a check that `_NET_ACTIVE_WINDOW` is still
the consented window and the pointer has not moved; any change **aborts** and
is reported as a disturbance (D28), never falling back to a display-only
write. An `InterferenceWatch` is armed around the whole action, so a move the
synchronous guard misses between its checks is still seen. `grab_focus`
raising the window is inside D#13 as stated -- the guarantee is that no window
*this tool launched* takes the foreground, and the operator's own Studio is
his -- but only because the window was his foreground to begin with, which is
exactly what `live_window` records.

**Why the write path is one tier-4 rung and not a tier-1 write that falls
through.** On wxGTK3 the tier-1 write never commits (D#102), so offering it
would report a display-only success and stop before the Enter. The rung that
reaches the application is the Enter, so the whole operation reports as tier 4
-- honest about what took the keyboard. The `shows()` postcondition asks
`confirms_value` (a yes/no, D#105), not a display read, because the field is
withheld (D#34b) and a display read would call every successful commit a
failure.

**What it deliberately is not.** It is not a hidden desktop (the target is on
the operator's own screen, by design), not a default (off unless asked, and
refused unless the operator has arranged the foreground), and not silent (the
session summary names the grant, and an abort says the desktop moved). It is
the narrowest thing that lets a value reach a toolkit that accepts it no other
way, and it takes the real keyboard for exactly one keystroke, only while the
operator is demonstrably present at the window they named. Evidence: issue
#102; issue #103; issue #111; D#102; D#13; D#34b; D#105; D9; D28.

### D#104. Slice: elements are a view of the enumeration, not a second walk

**Context.** `walk_elements_awake`, `is_selected` and `_current_value` are the
contract's element view -- the accessibility surface as UIA-shaped nodes. On
Windows they are a separate UIA walk; here the window tree *is* the
accessibility tree, so a second walk over the bus would re-fetch what
enumeration already read, 2,300 nodes on Studio.

**So the tree keeps a registry, and the element view reads it.** Each handle
carries an `_Entry` with the node's role, name, states and interfaces, fetched
once during enumeration. `walk_elements_awake` builds `AccessibleElement`s
from the `WindowNode` tree the caller already holds (its rects) plus those
entries -- no extra bus calls. An element's handle *is* the accessible's
handle, because a control here is its own window; `verbs.click_element(e)`
drives it directly through its Action interface, with no host window to post
to and no coordinate to convert.

**Identity is position plus value, so an element carries both.** Studio's
setting fields are unnamed `text` nodes told apart only by where they are and
what they show (D#101). So `AccessibleElement` carries screen extents, and a
field's `value` is left `None`: the resolver confirms it by comparison
(D#105), because reading it would disclose what D#34b withholds. `patterns`
are synthesised from interfaces -- `EditableText` becomes the neutral `Value`
so `set_value` finds it -- and `SelectionItem` from the selectable roles and
the `SELECTED`/`CHECKED` states, since AT-SPI carries selection as state, not
a pattern. `is_selected` re-reads the live state, because the state that
proves a click worked is the one after it; `_current_value` withholds an
editable field for the same reason `read` does.

**No wake step.** The embedded-document case (L8, #15) is unmeasured on Linux,
so there is no dormant engine to nudge; the name keeps the contract's shape
for when one is measured, as on Windows. Evidence: issue #104; D#101; D#34b;
D#105; D56.

### D#105. A place-plus-value locator, and a contract name that confirms without disclosing

**Context.** A control with no caption and no identity can be denied by place
(D72); it also has to be *addressable* by place, and on a target whose fields
are unnamed and whose values are withheld, a place alone is not enough -- two
fields at similar offsets need what they show to tell them apart. But reading
what they show is the disclosure D#34b withholds. This resolves the tension.

**The locator grows `region` and `value`.** `region=left,top,right,bottom`, in
the coordinates of the top-level window the match lives in, matches a control
whose centre lies inside it. `value="0.16"` matches a control that currently
shows that string. The value is checked by *comparison*, never by disclosure:
resolution is handed a `confirm(node, expected) -> bool | None` callback, and
the contents never reach the resolver, a result, a trace or a model's context.
A `value` locator with no confirmer is refused rather than matched loosely --
the whole point is to make a wrong-field write impossible rather than
unlikely, and silently dropping the value half would make it merely unlikely.

**The confirmer is a new contract name, `confirms_value`.** It reads the
control and returns only whether it equals the expected string. On Linux it is
`protection.confirms`, which reads under the deadline (D#9) and answers a
withheld or protected field as a yes/no (or `None`, did not answer) without
returning the value. On Windows it is a plain `read == expected`, because the
platform never withholds; a password field reads as not-answering
cross-process, so it confirms nothing, which is the safe direction. `env:
both`: the name is added to the shared contract and implemented on both, and
the Windows side needs re-verification on a Windows host.

**`set_value`'s own check moved onto it.** The tool used to compare the
display read to the wanted value; on a withheld field that read is `None`, so
every successful write reported as a failure. It now asks `confirms_value`,
which is true where the display read is blind -- the fix that lets the live
commit (D#111) verify itself on Studio at all. Evidence: issue #105; D72;
D#34b; D#9; D#111.

### D#117. A step line names what changed around it

**The field report.** Typing into a memo inside a dialog dismissed the
dialog, twice. The result said `2 other change(s) happened around this
action -- see disturbances` and nothing else: neither the window that
vanished nor the blocked-to-unblocked transition was named, so the caller
could not tell "the dialog closed" from "a validation popup appeared and
closed".

**What was wrong.** A standalone actuation result does carry the list --
each entry a kind (`window_disappeared`, `unblocked`, ...) and a caption,
D28 -- but a `batch` or macro step line keeps only `_STEP_FIELDS`
(`tools/stepper.py`), and `disturbances` was not among them. The count in
the error message survived; the names did not.

**Decision.** `disturbances` and set_value's `live_aborted` note are kept
on every step line. A disturbance is information for the caller (D28); a
line that says there were two and withholds which is not that.

**Evidence.** `tests/test_stepper.py`: a step line carries the list by
kind and caption, and no empty key when there is nothing. `env: any`.

### D#118. `absent: true` is a postcondition, and it must have something to be absent

**Context.** Waiting for a dialog to close after a click had to be written
as `expect: {changed: true}`, a surface-shape guess. `await_human`'s
`until` already takes `absent`, and `wait_for` has `condition: absent`, so
the vocabulary existed everywhere except on `expect`.

**Decision.** `expect: {locator, absent: true}` holds once the locator no
longer resolves in the expect's window scope. It takes a locator and
nothing about it: a control that is not there has no text or state to
match, so `text`, `selected` and `changed` alongside it are refused by
name (D#71).

**The guard.** The locator must resolve *before* the action. An absence is
trivially true of something that was never there, and a postcondition
that cannot fail is the false green D#71 exists to refuse: `verified:
effect` on a dialog that never opened. So a locator that does not resolve
beforehand is refused with a message saying what to name instead, rather
than quietly satisfied. The check is the resolver and nothing else, which
is also why it is proven without a backend.

**Evidence.** `tests/test_expect_absent.py`: the parse rules; the condition
turning true when the resolver stops finding the thing, in the expect's
scope; the refusal when it was never there; a bad locator an error, not a
condition. `env: any`.

### D#119. `pace` rides in a batch

**Context.** Click, settle, capture was three round trips, because `pace`
was withheld from the batch allowlist. D#75 withholds the lifecycle and
consent tools and the two that interrupt a person; `pace` is none of those.
It changes nothing on the target and names the guess it is (D#76).

**Decision.** `pace` joins `RUNNABLE_TOOLS`; a batch and a macro both gain
it. A per-step `settle_ms` was suggested and would be sugar over the same
thing; the allowlist is the smaller change and keeps the dwell visible as
its own step, with its own line in the result.

**Evidence.** `tests/test_stepper.py::test_the_allowlist_is_the_documented_set`
now asserts `pace` is in and the D#75 set is still out. `env: any`.

### D#120. An unknown argument is refused by name, and `capture` takes a `scale`

**The field report.** `capture` inside a batch rejected `scale`; standalone
it "accepted" it. Neither was true: `scale` was not a parameter at either
layer.

**What was measured.** The MCP library's argument model ignores an unknown
key (pydantic's default), so the standalone call returned the full-size
picture as if the request had been honored. Inside a batch the same call
reaches the Python signature and fails. An ignored parameter reads exactly
like an honored one -- the D#71 defect, at the wire.

**Decision, in two parts.**

- **Every tool refuses an unknown argument by name.** `build_server`
  switches each tool's argument model to `extra="forbid"` and re-derives
  its published schema, so `additionalProperties: false` is visible to a
  client too. The library offers no switch, so this reaches into its tool
  manager, guarded to degrade to the old behaviour rather than fail to
  start if that is renamed.
- **`capture` takes `scale` (above 0, at most 1).** Downscaled in GDI with
  `StretchBlt` in HALFTONE mode *before* the pixels are read: the per-pixel
  loop then runs over scale-squared as many pixels, so a half-scale capture
  is a quarter of the work and a quarter of the PNG a caller holds in
  context. The result says `scale` and that a pixel at (x, y) is at (x /
  scale, y / scale) in the full-size rects everything else reports. The
  Linux backend accepts the argument and refuses a value below 1 plainly
  (`env: linux` work), rather than returning the wrong size.

**Where `capture` lives now.** Adding it pushed `tools/discovery.py` past
the 400-line guard; a picture is a screen matter, so `capture` moved to
`tools/screen.py` beside `foreground`. The guard's fix is to move code, not
to loosen it (D60).

**Evidence.** `tests/test_mcp_server.py`: an unknown argument is refused
naming it; every schema forbids additional properties. `tests/test_capture_scale.py`:
out-of-range and non-numeric scales refused by name before any backend is
touched (`env: any`). `tests/test_windows_capture.py`: a half-scale capture
is the picture at half each dimension, agreed by the PNG's own header, and
smaller; scale 1 is byte-identical to no scale (`env: windows`).

### D#122. A profile can pin a control class to the posted click

**The field report.** A click on a `TsfCommandButton` took 5 to 10 seconds,
with `tiers_attempted` showing the pattern rung and then the posted one.

**What was measured.** For a plain HWND control the ladder is Invoke first,
posted second (`verbs.click`): a target that publishes an Invoke pattern
should be driven through it. This toolkit answers Invoke slowly or not at
all, so the rung costs its wait, and when nothing verifiable changes the
ladder escalates to the posted message -- which then works. Two costs: the
seconds, and on a control where Invoke *did* land but its effect was slow,
a second delivery of the same click.

**Decision.** A profile document may list `posted_click_only`: fnmatch
patterns against a control's window class. A class that matches gets the
posted message and nothing else, and the click result says so
(`route_pinned`). A declared route beats a learned one (D35), and this is
declared: the operator lists a class after seeing `tiers_attempted: [1, 3]`
and a slow click, not before. The pin is in the profile and not on the
call, because it is a fact about the target's toolkit, the same kind of
fact as its cadence (D26), and it should not have to be rediscovered by
every session.

**Not done.** The ladder still escalates on a verification timeout for
every other class. That is deliberate (D9, a tier the target ignores looks
exactly like this); the pin is the narrow, declared exception. A longer
`timeout_s` on the expect avoids the escalation on any class today.

**Evidence.** `tests/test_profile_posted_click_only.py`: the key is read as
patterns, matched by class, absent means nothing pinned, and anything but
a list of class patterns is an error rather than a default (`env: any`).
`tests/test_actuation_tools.py`: a pinned class attempts only tier 3 and
says `route_pinned`; an unpinned one still tries the pattern rung first
(`env: windows`). `docs/PROFILE.md` documents the key; `check-profile`
knows it.

### D#123. `await_human` can wait for a change to settle, and for a control alongside it

**The field report.** `await_human` returned after 41 s on `until_change`
while the operator's logout and login were still under way: the splash
screen was the change.

**What was wrong.** `until_change` returned on the first movement of the
surface digest, and `until` and `until_change` were exclusive, so there
was no way to say "the surface moved *and* the login window is there".

**Decision, in two parts.**

- **`settle_s`.** With `until_change`, a changed surface must hold still
  that long before the change counts. "Still" is measured from the last
  movement, not from the baseline, and a surface that moves and returns
  to its starting shape still moved -- a dialog that opened and closed is
  a change that happened. `settle_s` without `until_change` is refused by
  name, since it would mean nothing.
- **`until` alongside `until_change`.** Both must hold: the surface has
  moved (and settled, if asked) and the named control is present, reads
  the text, or is gone with `absent`. Every check is read on every poll,
  the surface first, so the settle clock runs while the control is being
  looked for. The result's `expected` names both halves.

The settle alone does not solve the field case -- a splash can hold still
longer than any sensible settle -- which is why the second part exists: the
right wait names the login window.

**Evidence.** `tests/test_await_human_settle.py`: the settle clock on its own
(first movement counts with no settle; a second movement restarts the
clock; a flicker back still moved), and through the tool with the digest
and the resolver stood in for: first movement, settle held, both halves
needed, `absent` alongside, and the refusals. `env: any`.

### D#124. A real click, on request, under the live grant

**The field report.** The Toggle Block Edit bar (`THtLeftPanel`) ignores
posted clicks: single and double, `delivered_to` names the right window,
nothing happens -- reproduced twice, and the caret placement on an empty
block row is the same. It was the only thing in the VendorApp client workflow
still forcing a fall-back to a tool that takes the desktop.

**What was measured.** Every click this backend sends is a posted message
triple (D#69); nothing in the tree calls `SendInput`. A control that
hit-tests the *real* cursor -- `GetCursorPos` rather than the message's
coordinates -- never sees a posted click, however correctly delivered. The
only click it answers is a person's, and that is what tier 4 is: the
pointer moved, a real button pressed, the window frontmost. D9 excludes it
by default because that is the exact interference this project exists to
avoid.

**Decision.** `click(real_input=true)` sends a person's click, and only
under the consent D#111 already defined:

- **Once per session, not per click.** The operator's approval is the live
  grant: `attach(live=true)` is allowed only when a window of the target is
  the foreground right now -- the one they are watching -- and records it.
  The wire now exposes `live` (it was implemented for Linux and never
  registered on the MCP layer). `real_input` on a session without the grant
  is refused by policy, before anything is resolved, with the message
  saying how to get one. The per-call flag is the agent choosing the
  route; it is never a rung the ladder escalates to on its own.
- **Only into the consented window.** The control's top-level window must
  be the live window, or the action aborts; a live grant on the main window
  does not license a real click on a dialog that appeared since.
- **The guard, twice, and the watch around it.** The foreground and the
  pointer are re-checked before the pointer is placed and again before the
  button goes down; any change aborts and is reported, never smoothed into
  a posted click. An `InterferenceWatch` is armed around the whole action
  so a move between checks is still seen (D28). The pointer is put back
  afterwards: the click was the tool's, the pointer is the person's.
- **Plain clicks only.** No modifiers on the real keyboard; refused by
  name.

**A rung that raised now says why.** A guard's abort used to read as "no
tier could act on this element" -- the ladder swallowed the exception. An
`ActionResult` carries `declined`, by route, and the error message repeats
it; the click result adds `live_aborted` so a status-skimmer sees that
nothing was forced.

**Also fixed on the way.** After an elicited consent, the re-attach
dropped `isolation` and `clipboard`; it now attaches with exactly what was
asked.

**What it deliberately is not.** Not a default, not a ladder rung, not
available without the operator arranging the foreground and saying so, and
not silent: the session summary names the grant and every abort names its
reason. `input.py` keeps its promise that nothing there moves the cursor or
touches the foreground; everything that does is in `backends/windows/live.py`,
beside its Linux counterpart.

**Not verified live.** The guard is proven with injected samplers; the
fixture cannot be the foreground in a test run (the focus guard forbids
it, by design). The first real click on `THtLeftPanel` is the operator's
shakedown, and its result carries `tier_used: 4, route: real_input`.

**Evidence.** `tests/test_windows_live_click.py`: placed, pressed, put back;
a foreground change aborts before the pointer is touched; a pointer move
after placement aborts before the press; no live window, a control outside
it, and an unknown button are refused with nothing sent (`env: windows`).
`tests/test_real_input_gate.py`: refused by policy without the grant,
refused with modifiers (`env: any`). `tests/test_actuate.py`: a declining
rung's reason is kept and named. Issue #124; D#111; D9; D28; D#69.

### D#128. A presence expect that already holds before the action is refused

**The field report.** Verifying the 2026-09-14 build on the dev-box VendorApp
client: a click on the Toggle Block Edit bar reported `verified: effect`
against `expect: {locator: "class=TsfDataPagesNoteBook"}`. The bottom tab
strip is one of those. It was there before the click, and the click had
done nothing.

**What was wrong.** A presence postcondition was checked only after the
action. One that already held before it cannot fail, so it proves nothing
about the action -- the false green D#71 exists to refuse. D#118 had just
made `absent` refuse a locator that does *not* resolve before the action;
presence had the mirror-image hole.

**Decision.** The presence condition is evaluated once before the action,
and if it already holds -- the locator resolves with its `text` or
`selected` constraint satisfied, or the D#60 foreground corroboration is
already true -- the expect is refused by name, with the message saying what
to name instead: a control that will appear, a `text` or `selected` it
will change to, `absent: true` for one that will go, or `changed: true`
for the surface moving. A refused expect is an error result before
anything is sent, so nothing is delivered on the strength of a
postcondition that could not have failed.

**Cost.** One extra resolve per actuation that carries a presence expect,
the same as `absent` pays. A replay whose target is already in the state
the expect names now fails that step rather than reporting it verified;
that is the honest reading, and `changed`/`absent` are there for a step
that means "make sure".

**Evidence.** `tests/test_expect_presence_guard.py`: already-resolving
refused; the refusal names the alternatives; a locator that does not yet
resolve is the postcondition and turns true when it does (`env: any`, the
resolver stood in for; `index=0` keeps the D#60 path out of it).
`tests/test_expect_foreground_corroboration.py`: the D#60 test now makes
the dialog foreground *after* the click, which is the case D#60 described.
Issue #128; D#118; D#71; D#60.

### D#130. The real click: its own frame, its own reasons, and the cheaper route first

**The field report.** Round-3 verification on the dev-box VendorApp client: the
real-input rung (D#124) fired in none of five attempts from the verifier's
session and once from the dev session. The five attempts were the
evidence: a correct D#111 refusal; a correct abort on the operator's own
mouse; a decline because typing the go-ahead in chat had moved the
foreground; a 17 s `live_aborted` with no reason; and a 46 ms "pointer
moved while acting" with an empty disturbance list.

**What was measured.**

- *The frame.* The point handed to `SetCursorPos` had been converted to
  physical pixels. This server process is not DPI-aware, so `SetCursorPos`
  and `GetCursorPos` are in its virtualized, logical frame -- the frame
  every rect it reports is in. At 125% every real click landed 1.25x off;
  one near the right edge was clamped by Windows, the read-back differed
  from the placed point, and the guard blamed the operator. The dev
  session's click succeeded only because the bar is a tall gutter.
- *The abort note.* `live_aborted` was set whenever the click was not
  `ok`, including a delivered click whose postcondition simply did not
  hold. A 17 s wait with no reason is not an abort.
- *The go-ahead.* The operator cannot type "hands off" without the chat
  window taking the foreground, which invalidated the live binding at
  click time.

**Decision.**

- **The click point stays in the frame the process sees.** No
  conversion. The placement is read back; a read-back farther than two
  pixels from the point is reported as "could not be placed" with both
  positions, never as the operator moving.
- **Every stop names its reason, and `live_aborted` means an abort.** The
  note is set only when a rung declined, and it repeats the declined
  reasons; a delivered click whose postcondition did not hold is a
  postcondition failure, as for any click.
- **The consented window is brought back, not refused.** For the real
  button press, a live window that lost the foreground is raised (it is
  the window the operator named) and re-checked; if it cannot be raised,
  that is the reason given.
- **Two routes under tier 4, cheapest first.** `cursor_posted` places the
  pointer and posts the ordinary message pair to the control's own hwnd:
  enough for a `GetCursorPos` hit-test, no button event through the input
  queue, no foreground needed. `real_input` presses a real button and
  runs only when the first did not verify. Both are tier 4 -- both move
  the operator's pointer (D9) -- and both need the live grant.
- **Said as the exception it is.** The refusal and the tool text say
  plainly that `real_input` leaves the posted-message contract for this one
  click and that the operator must be away from the mouse and keyboard. A
  profile may confine it: `real_input_only_for` lists the classes a real
  click may be asked for, and any other class is refused by name. On the
  VendorApp client that is two controls.

**Evidence.** `tests/test_windows_live_click.py`: the input route places,
presses and puts back; its own placement is not a pointer move; a
clamped placement is named; a window that lost the foreground is raised,
and one that cannot be is refused; a pointer move after placement aborts
before the press; the posted route needs no foreground; no grant, wrong
window, unknown button or route send nothing (`env: windows`, samplers
injected). `tests/test_real_input_gate.py`: a postcondition miss is not an
abort, a declined rung is, the click point is unconverted (`env: any`).
`tests/test_profile_posted_click_only.py` and `tests/test_actuation_tools.py`:
the profile confinement, refused before any input. Issue #130; D#124;
D#111; D9.

### D#133. `real_input` is removed; a control gated on hover state is told the mouse is over it

**The operator's ruling.** "If the user moving the mouse interrupts our
ghostdriver activities, that is a failure. Period." The premise is that
this tool drives a target without conflicting with what the person is
doing in parallel. A real click (D#124, D#130) uses the one physical
pointer: it either fights the operator or waits for them to stop, and
both are the failure the project exists to prevent. The last run made it
plain -- the click warped the operator's pointer while they were working
on another monitor, and the guards, working as designed, could only
report that. The rung is removed: the Windows `live.py`, the `real_input`
argument, the tier-4 click routes, the `real_input_only_for` key. D#124
and D#130 stand as the record of what was tried and why it cannot fit.
What stays from them: a rung that raised says why (`declined`), now on
every actuation result, and the post-consent re-attach keeping its
options.

**What the bar needs instead, and why a posted click could not give it.**
The Toggle Block Edit bar (`THtLeftPanel`) answered `delivered_to` right
and did nothing, in both directions, on every posted click. The likely
gate is not a cursor hit-test in the click handler but the control's
*hover state*: in Delphi's VCL, whether a control believes the mouse is
over it is set by the application on idle from the real cursor position
and handed to the control as a private notification, `CM_MOUSEENTER`
(`CM_BASE + 19`, `0xB013`). Mouse messages never set it. A control that
acts on a click only while in that state can never be satisfied by the
posted pair alone -- and it can be told, with one more posted message.

**Decision.** A posted click may be preceded by `CM_MOUSEENTER`, posted
to the same window before the move-down-up sequence. It is asked for two
ways: the profile key `hover_before_click` (fnmatch class patterns, the
declared form, D35) and a per-call `hover: true` on `click`, for trying
it on a control before listing its class. The click result says `hover`
and why, and the route is named `posted+hover`. Never automatic: the
value is in the `WM_APP` range and another toolkit could mean something
else by it. Still entirely a posted route -- no pointer, no foreground,
nothing the operator notices. Toolkit knowledge, not target knowledge,
so it lives in the repo.

**Not yet verified on the bar.** The message order is proven at the
posting layer, and the route is proven end to end on the fixture, whose
button needs no hover and is unaffected. Whether the bar's gate is the
VCL hover state is the hypothesis this exists to test; the first click
with `hover: true` after a restart is that test. If it does not answer,
the next question is whether the toggle has a keyboard or menu route.

**Evidence.** `tests/test_windows_input_hover.py`: the notification goes
out first, with no flags, and only when asked; the value is the VCL's.
`tests/test_profile_posted_click_only.py`: the key is read, matched, and
refused when malformed. `tests/test_actuation_tools.py`: a click asked
for with hover names the route and still verifies; the profile decides
when the call does not; nothing is added otherwise. `tests/test_actuate.py`:
a declining rung's reason is kept. Issue #133; D#124; D#130; D9; D35.

**Outcome (2026-09-14, later that day).** Tried on the bar with `hover:
true`, window inactive and then active: ignored both times. Hover was not
the gate. The fallback question was the right one: a right-click on the
bar opens a context menu reading *Start block edit -- Enter* and *End
block edit -- Esc*. `send_keys ["escape"]` and `send_keys ["enter"]` to
the hypertext edit box end and start block edit; the palette docks on
the latter. The bar is a mouse affordance for two keys the editor already
binds, and posted keystrokes reach it inside the contract. The hover
route stays -- cheap, general, and harmless where not needed -- with no
class listed for it yet. The operator's profile carries the note (D#137).

### D#135. A popup-menu item is chosen the way the menu chooses it

**The field report.** `click type=MenuItem index=2` on an owner-drawn
`#32768` item closed the menu, and on re-opening it the item's effect
had not happened. `find` reads these menus perfectly; acting on them did
not.

**What was measured.** The fixture's plain Win32 popup answers the
posted pair at an item's rectangle. The target's menu loop does not: a
menu's modal loop hit-tests the *real* pointer position rather than the
message's coordinates, so on a menu that is not under the pointer the
posted click lands outside the menu and ends it with nothing chosen.
Posting the pair to a menu that is not under the pointer is therefore
the one thing guaranteed not to work, and it destroys the state the
caller wanted to act on.

**Decision.** For an item of a `#32768` window, the first rung is the
menu's own keyboard route: highlight the item by position
(`MN_SELECTITEM`, undocumented but answered for decades) and post Return
to the menu window. The menu then does exactly what it does for a person
-- ends, and hands the command to its owner the way the application set
it up, `WM_COMMAND` or a return value alike -- so nothing here needs to
know how the application listens. The route is named `menu_keys`. A
greyed item is refused by name, not pressed; a submenu is declined so the
posted pair, second on the ladder, can open it. Tier 3 throughout: no
pointer, no foreground.

**Not chosen.** Posting `WM_COMMAND` with the item's id to the menu's
owner would fire the handler on a VCL `TPopupMenu` and on nothing that
uses `TPM_RETURNCMD`; it presumes how the application listens. The
keyboard route presumes only that the menu is a menu.

**Evidence.** `tests/test_windows_menus.py`: a captioned item and an
owner-drawn item are chosen through `menu_keys`, `tiers_attempted [3]`,
the owner's handler runs (`env: windows`, the fixture's real popup).
Issue #135; D65; D66.

### D#136. `capture region` renders the window a person sees at the rect

**The field report.** A `region` capture over an open context menu
rendered the form beneath it, black where the menu was; the same menu
captured by locator rendered fine.

**What was wrong.** The picker chose by overlap area, then by the smaller
window. A menu and the form under it overlap a region inside the menu
equally, and the all-windows list is sorted by size, so z-order had been
lost before the choice was made; which one won was an accident of the
enumeration.

**Decision.** The top-level window under the region's centre in the
desktop's current z-order wins when it is one of the candidates, because
that is what a person sees there. A backend that cannot answer the
question, or an answer that is not a candidate, falls back to the old
rule. A read of the z-order; nothing moves. The helpers moved from
`tools/core.py` to `tools/geometry.py` on the way, since the change put
`core.py` over the 400-line guard and the fix is to move code (D60).

**Evidence.** `tests/test_capture_region_pick.py`: the window under the
point wins; one that does not overlap the region is ignored; no answer
and no query both fall back (`env: any`, the desktop's answer stood in
for). Issue #136; D73.

### D#137. A profile carries the operator's notes per control class

**Context.** Having learned that the Toggle Block Edit bar is only a
mouse affordance for keys the editor binds, the operator wanted the next
session to read that before spending another hour clicking it. The
tool has no place for such a thing: everything in a profile is a policy
or a measurement.

**Decision.** `notes`: `{class pattern: text}`, declared (D35). A `find`
match and a `click` result for a matching class carry `note`. The
mechanism is generic and lives in the repo; what the notes say about a
target stays in the operator's profile (D60's boundary, and the rule
that no target knowledge enters any repository).

**Evidence.** `tests/test_profile_posted_click_only.py`: notes matched by
pattern, malformed notes an error (`env: any`).
`tests/test_actuation_tools.py`: the note rides on `find` and on `click`
for the fixture's class, and no key appears without one. Issue #137.

### D#1. The three unprobed routes, run against a real owner-drawn grid: all three come back negative

**The target.** Windows' own Character Map (`charmap.exe`), on a real
Windows 11 Home box (build 26200), not the fixture. Chosen because it is a
textbook owner-drawn grid -- `CharGridWClass` paints every glyph cell
itself -- and because it ships with Windows: no license, no customer data,
no install footprint, reachable by anyone with a Windows box, which matters
for a repository that otherwise never names a real target (`docs/VALIDATION.md`'s
convention is to withhold product names; this one is Microsoft's own OS
component, so naming it costs nothing and buys reproducibility).

**Session.** Driven headlessly through the account documented in
[[ghostdriver-windows-host-win-host]] (`gdrunner`, an interactive autologon
session with nobody at the console at the time), rather than a person's own
session -- consistent with the project's premise of not taking the desktop
from whoever is using it. This was a narrower session than issue #3's six
gates; it answers #1's question only. #3 remains open.

**What was measured.**

The grid enumerates as one control with real content and no children:

```
class=CharGridWClass text='Character Grid' rect=(46, 145, 469, 398)
```

Calling the shipped tool first, the way an operator would:

```
probe_grid(session, "class=CharGridWClass")
-> not_actionable: "'class=CharGridWClass' already answers with text
   ('Character Grid'); it is not a painted region. Use `read`"
```

It refuses before trying anything. `node.text` is genuinely non-empty --
`WM_GETTEXT` really does return `"Character Grid"` -- so the guard that
exists to stop a probe from spending a side effect on a control `read`
already answers (D46's own reasoning, exercised for the fixture in
`tests/test_windows_grid.py::test_the_tool_refuses_a_region_that_read_already_answers`)
fires here too. The difference: for this control, that text is a static
accessible label the class sets once, not its content -- `read` on the same
locator returns the identical `"Character Grid"` regardless of which glyphs
are on screen or selected. A caller who follows the tool's own advice gets
back a plausible, wrong answer with no way to tell it is wrong. Filed as
**issue #141** rather than fixed here: it is its own measurement question
(what distinguishes a decorative label from real content), the fixture
cannot reproduce it (its buttons all answer with their real caption, D46's
case), and this session's job was the three routes, not this guard.

Bypassing the guard to run the two routes it would have tried:

```
grid_strategy: unknown
accessible_on_focus: tried=true worked=false (0 accessible elements before WM_SETFOCUS, 0 after)
clipboard_copy:      tried=true worked=false ("the control did not change the clipboard")
```

The clipboard route was tried twice: once against the grid's default state,
and once after a posted `click(at=(15, 15))` meant to select a glyph first --
the "Selected Character" status line read the same value before and after,
so the posted click did not move the selection (a further data point for
whoever measures #133-style posted-click gaps against this class; not
pursued further here, out of scope for this issue). Neither attempt moved
the clipboard sequence number.

The third route, an export command, has nothing to probe: the dialog's full
control set (`&Select`, `&Copy`, `Ad&vanced view`, `&Help`, `Sea&rch`, plus
combo boxes and edits for font/search/group) has no export or save
affordance at all. Absence, not failure -- recorded because the issue asks
for it either way.

**Decision.** `grid_strategy` for this target is `unknown`, and nothing is
wired: `probe_grid` already is the seam D46 asked for, and an `unknown`
verdict changes no code, per `_unknown_meaning`'s own reasoning. All three
routes come back negative against a real target for the first time, which is
the condition the issue named for reopening the OCR question deferred to
issue #20 -- stated here as evidence for whoever picks #20 up, not decided
by this session. The scorecard entry this issue names moves from "unprobed"
to "probed, none work (this target)"; a second real target would strengthen
that from one data point to a pattern.

**Evidence.** Commands and output above, run interactively against
`charmap.exe`'s live `CharGridWClass`; `docs/DECISIONS.md`'s own D46; issue
#1; issue #20; issue #141 (the refusal-guard defect this session found).

### D#141. The guard that refused a real grid stays; the person waives it, per class

*Placed here rather than at the tail because it is the second half of D#1:
the defect that session found, answered.*

**The defect.** `probe_grid` refused `charmap.exe`'s `CharGridWClass`
before trying a route, because `node.text` was non-empty:

```
not_actionable: "'class=CharGridWClass' already answers with text
   ('Character Grid'); it is not a painted region. Use `read`"
```

Both halves of that sentence are false for this control. It *is* a painted
region -- it paints every glyph cell itself -- and `read` does not answer
it: the string is a static accessible name the class sets once, returned
identically whichever glyphs are on screen or selected. A caller who took
the tool's advice got a plausible, content-free answer with nothing in it
to say so (issue #141).

**What was considered.** The guard itself is right and is not removed. It
exists because probing a control `read` already reads spends a side effect
-- the target's own Copy, on the person's shared clipboard -- for nothing
(D46), and for a button, whose caption *is* its content, the inference
holds exactly. The fixture's `GhostFixtureCommandButton` case is that, and
it still passes.

The tempting fix is to detect the difference: compare the text against the
class name, against a caption convention, against the rect. Every version
of that is the tool **picking** between "this text is content" and "this
text is a label" from a signal that does not carry the answer -- two
controls, identical in every respect a window exposes, differing only in
what the application meant. D33 refuses ambiguity rather than picking, and
a wrong guess here is worse than the refusal was: it would spend the
clipboard on a caption, or keep refusing a grid while looking as though it
had decided.

**Decision.** The guard stays, and the person waives it per control class,
in the profile:

```json
"text_is_label": ["CharGridWClass"]
```

`fnmatch` patterns against the window class. A listed class is probed
despite its text, and the report carries `text_is_label` saying which
pattern let it run -- a probe that ran because of a declaration should read
as one, not look like a measurement. This is the third field of exactly
this shape, after `posted_click_only` (D#122) and `hover_before_click`
(D#133), and for the same reason each time: the knowledge is a property of
a control class, it is held by the operator who curated the profile, and a
declared fact beats a measured one (D35).

A per-call `expect_text: false` was considered and declined. The caller at
the moment of the refusal is precisely the party who cannot tell -- D#1's
session followed `read`'s advice and could not see that the answer was
empty -- so a flag flipped in the moment records a guess, while a profile
entry records something someone established and the next session inherits.

`grid_seek` carried the same guard, verbatim, and now shares the same code:
waiving it for `probe_grid` alone would have left the class reachable by
the probe and not by the tool the probe exists to enable.

**The refusal, for the case that is still refused,** no longer asserts what
it cannot know. It says the region answered a text query, which is what was
measured; it no longer says the region is not painted, which was inferred
and was wrong; and it names the class to list and the key to list it under,
so a caller who disagrees can act rather than re-run it.

**Evidence.** D#1's measurement, above; issue #141. The regression runs on
Windows against a new fixture control, `GhostFixtureLabelledGrid`
(`--labelled-grid`): the same owner-drawn grid that answers `WM_GETTEXT`
with a fixed label, because no existing fixture control could reproduce the
defect -- every one of them answers with its real caption, which is why the
refusal looked correct everywhere it could be tested. The guard's own
decision is checked platform-neutrally in `tests/test_grid_label_guard.py`,
at `text_guard`, the seam that needs no backend: the promise is neutral
even though the control that broke it was Win32 (D#39).

### D#159. The stop stays; what it says changes

**Context.** `conftest.mcp_or_skip()` was called at module level by
`test_mcp_server.py` and `test_mcp_stdio.py`. On a missing or too-old
protocol layer it called `pytest.skip(...)` there -- and a skip outside a test
is a collection error. pytest reported it by explaining its own API:

```
Using pytest.skip outside of a test will skip the entire module. If that's
your intention, pass `allow_module_level=True`.
...
!!!! Interrupted: 2 errors during collection !!!!
```

No test in the repository ran, and nothing printed named `mcp`, named the
version required, or named the remedy.

**The outcome was already right.** The instinct is to reach for
`allow_module_level=True` and restore the skip. That is the wrong repair. The
protocol layer is an optional extra, but a suite that cannot exercise it has
*lost that coverage*, and this project exists on the premise that lost
coverage must be loud rather than subtracted quietly from a green run. D#39,
D#53 and D#58 are three versions of the same lesson. Turning this into a
clean skip would have made it a fourth.

**So the stop stays, and stops saying the wrong thing.**

```
ERROR: mcp 1.28.0 is installed; this suite needs 2.1 or newer (1.x renamed
FastMCP to MCPServer, so 1.x imports and then fails on an inner path).
Upgrade with: pip install -e '.[server]'
```

Three changes produce that. The check moved to **session start**, because the
condition is a fact about the environment and not about either module -- one
message before collection instead of two collection errors. It raises
**`pytest.UsageError`**, which pytest prints as a plain line with no traceback
and exits `4`. And the message carries both numbers and the fix, because the
reader's next question is always which of the two is wrong.

**D#53 fixed what the gate measures; this fixes what it reports.** D#53 moved
the gate from the module's `__version__` to distribution metadata, and was
right to. It left the reporting alone, and the reporting became the part that
misled -- the same entry's own warning, that the danger is a gate which
*explains itself* wrongly, turned out to apply to its own successor.

**The decision is a pure function, on purpose.**
`protocol_layer_refusal(installed, minimum)` is handed a version and returns
the reason or `None`. It does not look anything up. A test for "an absent mcp
is refused" that had to uninstall mcp could only run where the bug cannot
happen, which is exactly the shape #39 catalogued. Fed values instead, the
cases run everywhere, on every platform, with nothing staged. The end-to-end
promise -- that a refusal stops a run *before any test body executes* -- is
proved by a subprocess pytest whose conftest refuses on purpose, and asserted
on a file the inner test would have written, because an exit code alone
cannot tell a refusal from a collection error.

**How it was found is worth keeping.** `CLAUDE.md` documents the command as
`PYTHONPATH=src python3 -m pytest`, which uses whichever `python3` is on
PATH. The repo `.venv` holds mcp 2.1.1 and is correct; this machine's system
interpreter holds 1.28.0. Running the documented command without activating
the venv reproduces it in full, and the report gives the reader no way to
discover that the interpreter is the problem. The defect is real independent
of that mistake -- but it took making the mistake to see it.

**Disagreeing with this** means arguing the extra is optional enough that its
absence should not stop anything. That case can be made; it is the ordinary
meaning of "optional extra". It has to answer what the suite is claiming when
it reports green with the protocol binding untested.

**Evidence.** Issue #159; the before/after above, both produced on this
machine's system interpreter at mcp 1.28.0; `tests/test_mcp_dependency.py`;
`tests/conftest.py`; D#39; D#53; D#58.

### D#16. A browser driver stays out; the fixed surface already reaches the web

**Context.** Issue #16 is one of the five spec §12 rows (#16-#20) that
`docs/product/features/deferred-scope-tracking.md` exists to keep visible
without scheduling. It was dispatched for implementation anyway. Its body
does not ask for code -- its "Before picking this up" section asks a
question, whether a first-class browser driver belongs in this repository
at all -- and that question has never been answered in writing here.

**The record the feature doc points at is missing.** That doc's non-goals
say re-deciding a deferred item is out of scope because "that call is
already recorded in `docs/DECISIONS.md` and spec §12". For #16 it is not.
§12 has a one-line reason, and the only browser sentence in this log is
D58's closing paragraph, about a *browser protocol for an engine that
cannot be woken* -- which is the other thing, and the thing #16's body
opens by saying it is not. An item whose only written reason is "deferred"
reads to the next triage run as unscheduled work. That reading is what
produced this session, so the answer is written out rather than assumed.

**The spec's stated reason is the weaker half.** "Solved problem" decides
nothing on its own. Most of what this repository does is solved elsewhere,
and was built here anyway, because the solutions elsewhere assume a desktop
nobody is sitting at.

**The load-bearing half is measured, and it is already in this log.** D58
drove a real Chromium engine through the *existing* tool surface: it woke a
dormant document tree, resolved the page's buttons, tabs and inputs with
B1's ordinary element locators, clicked them with the posted button pair,
replaced a value and saw the page commit it on tab-out, took tier 1 under a
commit expectation, and refused a password field by the same rule that
protects a native one. No tool was added and no protocol was spoken. So the
browser is not an unreached target that a driver would reach. It is a
reached one, and a driver would be a second way to do what the surface
already does.

**That is what makes D1 bind here rather than merely apply.** The
fixed-surface constraint says onboarding an application must not grow the
surface. A browser driver would do worse than grow it -- it would fork it.
The same page button would be addressable by two unrelated locator
vocabularies, with different resolution rules and different failure modes,
and D33's refusal to pick between ambiguous matches has nothing to say
about ambiguity between *surfaces*: a caller holding a locator would first
have to know which of the two worlds it came from.

**And the hazard this codebase exists for does not reach a browser.** The
focus guard, the tier ladder, the disturbance report, session consent, the
cadence -- every one is bought against a single hazard, an automation and a
person contending for one desktop. A browser driver has its own process and
its own profile and contends for nothing. Housed here it would pay for
guarantees it cannot use, and every later change to those guarantees would
have to be reasoned about against a target that cannot experience them.

**Decision.** A browser driver is out of this repository. If it is ever
wanted it is a sibling sharing the orchestration layer -- §12's own "Test
orchestration and assertion DSL" row, issue #18 -- and not a backend under
`backends/`. That directory is the *platform* seam (D59): `load()` picks by
`sys.platform`, and a browser is not a platform. An entry there would make
the registry answer two different questions depending on which entry was
read, which is the defect R4 split the region model to remove.

**Nothing new is added to enforce it, because something already does.**
`tests/test_mcp_server.py` and `tests/test_mcp_stdio.py` assert set
*equality* against `EXPECTED_TOOLS`, not containment, so a driver that
reached the protocol layer fails them by name. A dependency blocklist was
considered and rejected: it names the wrong condition, passing a
hand-rolled CDP client and failing a browser package installed for
something else. What a guard that names the wrong condition costs is
already recorded twice here (D#53, D#159).

**Disagreeing with this** has a real case, and it is D58's own last
paragraph. That measurement reached the page through a Win32 *host window*
-- posted clicks and characters to an HWND. A target that is a browser and
nothing else, or the same embedded engine on the Linux backend that does
not exist yet (D59), is not covered by it. The argument for a browser
driver should be made from that gap, with a measurement in it.

**What would reopen it, and what would not.** D58 already states the
condition for the *embedded* case -- a host that answers neither posted
clicks nor characters -- and that reopens the browser protocol, which is a
different question: answering it yes would not answer this one. This issue,
a browser as a first-class target driven by its own vocabulary, reopens on
a target this project would otherwise accept under one of §2's profiles,
whose web content cannot be reached through the accessible surface *and*
for which the pattern route on the ladder also fails. "A browser would be
easier" is not that condition, in the same way #19 and #20 are explicit
that the awkwardness of the current strategy is not theirs.

**Evidence.** Issue #16; spec §12 and §2.3 (profile W1);
`docs/product/features/deferred-scope-tracking.md`; D1; D33; D58; D59; R4;
`tests/test_mcp_server.py::EXPECTED_TOOLS`.

### D#115. Linux backend scope: EditableText writes only, owner-drawn controls are screenshot-only

**Context.** Driving Bambu Studio 02.08 (wxGTK3) on GNOME/X11 over the a11y bus
(`gi` `Atspi 2.0`; no `pyatspi`) on 2026-09-11 measured what the bus reaches
and what it does not. Text fields read with `Atspi.Text.get_text` and write
through `Atspi.EditableText.set_text_contents` followed by a real `Return`,
which Studio's modified marker confirms -- and this works even while the
window is minimized (`showing=False`). Real widgets (toggle/radio/check
buttons, GTK dialogs) expose an `Action` with `click`, and two instances of
one app are told apart by `get_process_id()` (the bus may report a sibling
pid a few off the launch pid). Owner-drawn controls -- Bambu's toolbar
Slice/Print buttons, sidebar parameter labels, custom dialog buttons -- are
not reachable at all: they report empty names and `INT_MIN` extents, so they
cannot be located or identified through the bus by any means. D#10 already
measured this same negative on the GTK4 fixture; this session confirms it
holds on wxGTK3 too. The only way to drive one is screenshot plus coordinate
click, and only while the window is actually mapped on screen -- scripted
un-minimizing or raising is not a fallback, because mutter refuses
non-interactive activation (a zero-timestamp `_NET_ACTIVE_WINDOW` logs as a
buggy client); D#13's nested-display foreground guarantee is the only robust
answer to that.

**The decision: reading is in scope now; writing is in scope only for
`EditableText`, located by place plus value, never by label.** Slices 1-2 of
#40 landed reading. Writing goes no further than fields that implement
`EditableText`, and -- because Studio's fields carry no exposed label -- a
target is located by screen position and its current displayed value (the
D#105 place-plus-value locator), never by name. Everything owner-drawn stays
out of scope for the bus entirely; if it is ever exposed at all, it is as an
explicit screenshot-and-click tier gated on a mapped-window precondition, not
folded into the `EditableText` path. `src/ghostdriver/backends/linux/verbs.py`
already matches this: `set_text` offers only the `EditableText` tier-1 rung
(or the consented tier-4 live-commit rung), and `click` only drives a control
through its `Action` interface -- there is no rung anywhere that reaches an
owner-drawn control, so no code changes followed from this decision, only the
record of it.

**This backend is a research track, not the production tuning path.** For
Bambu Studio specifically, tuning goes through `x2d-pro/bambu-studio/tune.py`
(edit the project file directly) and `verify.py` (gate on the sliced gcode),
then open the result in Studio -- this backend does not grow
Studio-specific tuning of its own. See `docs/linux-backend-scope.md` for the
full reachable/not-reachable table this decision is drawn from. Evidence:
issue #115; issue #40; D#10; D#13; D#101; D#105.
### D#157. The test bed's autologon is removed, and Session 0 is refused as its replacement

**Context.** The Windows test bed signed `gdrunner` into the physical console
at every boot -- `AutoAdminLogon = 1`, `DefaultUserName = gdrunner`. The
operator then signed in on top of it and found the runner account already
holding session 1. A tool whose whole premise is that it does not take the
desktop from the person using it was, at rest, taking the desktop from that
person before they had logged in.

**The password was not absent, only somewhere else.** There was no
`DefaultPassword` value in the registry, which reads as reassuring and is
not: `netplwiz` and `Autologon.exe` store it as an **LSA private secret**,
readable only by SYSTEM. Clearing `AutoAdminLogon` alone leaves that secret
live, so the autologon re-arms with a working credential for anyone who sets
the flag back to `1`, and nothing on the surface says it was ever there. It
was cleared with `LsaStorePrivateData(..., NULL)`, which reported `cleared` --
so the secret was real, and a registry-only fix would have missed it.

**Both runner accounts are hidden from the sign-in screen**, via
`Winlogon\SpecialAccounts\UserList`. This is tidiness and nothing more: they
remain in `net user`, in `C:\Users`, and usable by scheduled tasks and
`runas`. Recorded because the opposite is easy to assume -- an account you
cannot see looks like an account that cannot be used, and these can.

**The consequence is that `gd-pytest` has nowhere to run.** It is
`Interactive only`, running as `gdrunner`, and the autologon was what kept a
session waiting for it. The obvious repair is to run the suite as a service in
Session 0. That repair is refused.

Measured with the runner's own probe, unchanged, in both contexts:

| | interactive | Session 0 (SYSTEM) |
|---|---|---|
| `winsta` | `WinSta0` | `Service-0x0-3e7$` |
| `input_desktop_reachable` | `True` | `False` |
| `foreground` | `65796` | `0` |

**`GetForegroundWindow` returns NULL in Session 0, and `ForegroundWatch`
polls exactly that value.** `watch.taken` could never be populated, so
`test_zz_focus_guard` -- the test this project calls the promise the whole
tool is built on -- would pass because its subject cannot occur, not because
nothing took the foreground. That is D#39's lesson arriving from the other
direction: not a guard that skips, but a guard that runs where its failure is
impossible. The rule is the same either way -- put the test where the failure
is *possible*.

A session-less run would not weaken the focus guard. It would retire it while
leaving it in the report, green.

**The host closes the usual alternative.** `win-host` is Windows 11 Home: no
RDP host (`fDenyTSConnections = 1`, `TermService` stopped, and Home ships no
server to enable), no Windows Sandbox, one interactive session at a time. The
CI convention of parking a disconnected RDP session and running the suite
inside it is not available here, so the choice is narrower than it would be
on Pro.

**What is left is deliberate, not automatic.** The platform-neutral majority
of the suite needs no desktop and can run anywhere; the Win32 remainder needs
a session someone chose to create. How to split it, and whether a VM that
keeps its autologon off the host desktop earns its weight, is not decided
here: it needs a Windows box, and this was reached from Linux over SSH.

**Disagreeing with this** means arguing that the focus guard is worth keeping
in a context where it cannot fail. That argument is available -- the rest of
the suite still exercises real behaviour in Session 0 -- but it has to be
made out loud, because the price is a green run that has stopped checking the
one thing the project exists to check.

**Evidence.** Issue #157; the two probe lines above, from
`C:\gd-run\out\pytest.log` and a SYSTEM-scheduled run of the same
`where.py`; `tests/focusguard.py`; `tests/test_zz_focus_guard.py`; D#39.
### D#39a. The third group had more members than the one file D#39 fixed

**Context.** D#39 found three groups inside the 41 modules then gated
`on_windows` at module level, fixed the one file that turned out to be
entirely group three (`test_tool_contracts.py`), and left the rest of the
audit undone: "the audit is not" per-platform, the original issue said, and
D#39 covered one file of it. #39 stayed open. Five more `on_windows` modules
had been added since (41 → 46), so the remaining audit was not just old
debt -- it was still accruing.

**Read every non-`test_windows_*` gated module, function by function, not by
file.** The earlier fix moved a whole file; this pass found group three
hiding as *individual tests* inside otherwise-correctly-gated files -- a
shape D#39 didn't check for. The tell was the same in every case: no
fixture that drives a real window in the signature, and a body that either
calls a pure function on literals or feeds a class synthetic collaborators.

**Six instances, two shapes.**

| test | file | what it actually needs |
|---|---|---|
| `test_an_unquoted_regex_with_spaces_is_told_how_to_quote` | `test_field_feedback.py` | `Locator.parse` on a string |
| `test_an_unquoted_regex_with_spaces_is_one_token` | `test_field_feedback_3.py` | same |
| `test_the_focus_note_names_a_tool_that_activates_windows` | `test_field_feedback_6.py` | a string constant |
| `test_verify_window_reads_timeout_s_from_any_expect` | `test_actuation_tools.py` | a pure function on dict literals |
| `test_a_helper_taking_the_foreground_is_the_target_taking_it`, `test_moving_between_family_members_is_not_a_new_taking`, `test_a_failing_family_snapshot_falls_back_to_the_target_alone` | `test_family_watch.py` | `InterferenceWatch` fed fake callables |

The first four needed nothing platform-specific at all and were moved to
where their subject already has neutral tests: the two `Locator` cases into
`test_model.py` beside `test_locator_parse_class_and_text` and its
neighbours, the guidance-string case into a new `test_guidance.py`, and the
`expect`-window case into `test_expect_absent.py`, which already carries
the sibling `parse_expect` cases and says so in its own docstring
("Backend-free ... on any platform").

**The `InterferenceWatch` three are the same failure D#39 fixed for
`test_tool_contracts.py`, at import time instead of collection time.**
`InterferenceWatch` was lifted to `ghostdriver.interference` and made
"platform-neutral by construction" in D#111 specifically so it could be fed
synthetic collaborators and tested anywhere. These three tests already do
exactly that -- every argument is a lambda, no real window is ever touched
-- but they imported the class from `ghostdriver.backends.windows.interference`
instead, which binds `ctypes.WinDLL` through `winapi` at *module* import,
raising `AttributeError` on Linux before the neutral test body ever runs.
Importing the same class from `ghostdriver.interference` fixes it with no
change to the test bodies. They stay in `test_family_watch.py`, next to the
two tests that do drive a real fixture window and correctly keep
`@on_windows` -- the file no longer carries a module-level gate, the same
shape as `test_backends.py` (one Windows-only test beside neutral ones).

**A seventh test was not a group-three fix but a duplicate.**
`test_tools.py::test_every_tool_refuses_an_unknown_session` hand-checked
nine tools against an unknown session id. `test_tool_contracts.py`'s
`test_every_session_tool_refuses_an_unknown_session`, D#39's own fix,
already parametrises this over *every* session tool by enumeration, all
nine included. The hand-picked list added no coverage the enumeration
didn't already have on every platform, so it was deleted rather than moved.

**Two more were group three but not duplicates: `grant_targets()` called
with nothing to record, and `attach` on a pid `psutil.Process` cannot find.**
Neither reaches a backend -- `Toolbox.attach` calls `psutil.Process(pid)`
before it ever gets to `self._trees(...)`, the same window-enumeration call
D#39 named as the actual platform touch. `test_tool_contracts.py` was the
wrong home (its own docstring scopes it to three specific tool-surface
promises); these went to a new `test_lifecycle_policy.py`, added to
`MUST_RUN_EVERYWHERE` alongside `test_family_watch.py`.

**Not done here.** Group two -- tests that are neutral logic but whose
*test* drives a real window (the `app`/`win32_target`/`held_app`/`desktop`
fixtures, or a spawned `tests.fixtureapp`) -- is still correctly gated and
stays that way; parametrising it over backends still needs a Linux target,
which D#39 already deferred and this session did not revisit. The 22
`test_windows_*.py` files were skimmed, not read function by function: a
few no-argument "classify this MSAA/UIA verdict" tests were noticed and
left unaudited, because their subject (MSAA, UIA) is Windows by name and
digging further was not this session's evidence to gather. Whoever picks
that up should read this entry's method (fixture-signature first, body
second) rather than re-deriving it.

**Measured**, full suite minus the five hanging probe-pipe modules
`ghostdriver-linux-suite-hangs` already names plus the nested-Xvfb Linux
suites (resource contention on this host, not a defect in this change):
**752 passed, 2 failed, 425 skipped**, collected 1179. The 2 failures are
`test_mypy_finds_nothing[linux]` and `[windows]`, both the pre-existing
`OrderedDict` mismatch at `tools/__init__.py:86` on this venv's mypy
version, reproducible on `origin/main` before this change. All nine
relocated/fixed tests verified individually passing (not skipped) on
Linux; the trimmed modules still collect cleanly.

**Evidence.** Issue #39; D#39; D#111 (`InterferenceWatch` lifted neutral);
`tests/test_structure.py`'s `MUST_RUN_EVERYWHERE`; `tests/test_tool_contracts.py`;
`tests/test_family_watch.py`; `tests/test_lifecycle_policy.py`.

### D#163. The Linux flake was fixed sleeps racing undeclared fixture timers, and the timers are now declared

**Context.** Across three full-suite runs on one Linux box, one session, one
interpreter, the failing set was different every time: `restore`×1 /
`restore`×1+`slice3`×4+`tier1`×1+`watch`×2 / `restore`×1+`watch`×4, over an
identical 1309 collected. Run duration for identical work varied 387s-681s.
The four modules run *alone* gave a fourth distinct set, `3 failed, 17
passed`, which said the preceding ~1300 tests were changing the outcome.

D45 is the standing rule: an intermittent failure gets instrumented, never
retried, because a retry takes the evidence with it. The sample assertion in
#163 is what that rule was asking for and not getting:

```
>       assert watched["any_capture"] is True, watched["events"]
E       AssertionError: []
```

It reports *that* nothing arrived and not *why* -- no window id, no timings,
no indication whether the watch was even running when the target moved.

**What it was.** Not four flakes; one mistake made in four places. Every
nested-display probe bounded its steps with a fixed `sleep`, and two
different guesses hide under that word.

*A dwell after an action.* `xdotool windowactivate` then `sleep 2`, then read
`_NET_ACTIVE_WINDOW`. Under load GNOME Shell has not finished, so the probe
photographs the previous state and the assertion reports a window manager
that did not activate. This is `test_restoring_a_window_necessarily_focuses_it`
-- the one constant failure, and constant because a full suite is reliably
slower than a lone module. `linux_l7_probe.sh` already contained the right
shape one function above the bug: `focus()` polls until `_NET_ACTIVE_WINDOW`
agrees, and never flaked.

Worth being exact about what was reproduced: the manufactured load below
bites one step earlier, on the `sleep 2.5` after `windowminimize`, and
aborts the control rather than failing the measurement. Same script, same
mistake, different sleep -- which is the argument for fixing the pattern
rather than the one line #163 happened to name.

*A budget before a timer.* `tests/fixtureapp_gtk.py` arms its disruptions with
`GLib.timeout_add(options.modal_after, ...)` -- absolute, from the app's own
start. A probe sampling the calm state *before* the disruption is racing that
timer with its own setup work, and nothing in the probes said so. Slice 3 had
9s to do three contract calls and a full `enumerate_process` AT-SPI tree walk;
when the walk overran, the modal was already up, and the four tests that read
`before` failed on "a modal before one was raised". They were right. There
was one. That `slice3`×4 is exactly the four tests reading `before` is what
identified the mechanism.

**Decision.** `tests/linux_probe_support.py`, and four probes rewritten
against it.

1. **Where a condition exists, wait for it and record the wait.** `settle()`
   polls, stops the moment the condition holds, and returns a record: `ok`,
   `seconds`, `timeout`, `polls`, last error. Not a retry under D45 -- the
   condition is the window manager finishing the action just requested, and
   the measurement is still taken exactly once, afterwards. What the fixed
   sleep threw away was the number, and the number is the diagnosis.

2. **Where no condition exists, say so.** A negative claim -- "a bare map does
   *not* un-hide the window", "an owner-drawn control emits *no* event" --
   cannot be polled for. Waiting is the only way to ask and the length of the
   wait is part of what the answer means. Those stay fixed and are recorded as
   `dwell`, so a reader can see which two steps are still guessing on purpose.

3. **A budget that is raced is declared, and its margin reported.** `Budget`
   names the fixture timer a probe runs against and reports what the setup
   spent against it. A negative margin means the harness lost the race, and
   the fixtures **skip** on it rather than failing -- the precedent
   `test_linux_restore.py` already sets, where the L7 harness skips if it
   could not hide a focused window, "so nothing it says about restoring one
   means anything". A probe that never reached the state a test is about has
   measured nothing, and nothing is not a defect. Skipped *loudly*, with the
   margin in the message, because the way this goes wrong is a budget that
   quietly stops being met and takes the coverage with it.

**The distinction in point 3 is the reusable part.** "The harness could not
set the scenario up" and "the scenario ran and the promise broke" are
different findings, and a suite that renders both as the same red line
teaches people to stop reading it -- the same argument #161 makes about a
permanently-red mypy pair, arriving from the other direction.

**Two harness faults found while building this, both of them the same
failure of instrumentation one level up.**

*The report was all-or-nothing.* Every timing was assembled into one JSON
line printed at the end, so a probe that stalled produced nothing and the
fixture could say only "the probe produced no report" -- which is the
uninformative failure #163 is about, reached from the other side. Measured
here: a probe whose fixture application had already exited sat for over 200s
and emitted not one usable fact. Records are now streamed as `TIMING <json>`
the moment they are taken, so whatever the probe does next, the steps it
finished are already out.

*The fixture's read deadline could not fire.* `line, deadline = None,
time.monotonic() + 240` then `for out in probe.stdout:` with the clock
checked *inside* the loop -- so the deadline only expires when a line
arrives. It bounded a slow probe and not a silent one, which is the wrong
half, and a silent probe blocked the run indefinitely. `collect()` reads on a
thread against a real deadline and keeps the streamed trace. **The same
pattern is still in `test_linux_slice4.py` and `test_linux_reading_wired.py`,
which are outside this issue's failing set and are left for their own** --
noted here rather than fixed quietly, because two modules that can hang a
local run are worth an issue of their own.

*Stale fixed paths.* `linux_l7_probe.sh` wrote `/tmp/gd-l7.json`. Once the
announce wait became a condition on file *contents* rather than a sleep, a
previous run's leftovers satisfied it instantly and handed the measurement
two window ids that no longer existed -- observed aborting a control that had
nothing wrong with it. It uses `mktemp -d` now. Separately, the announce line
is printed on a 120ms timer, well before GNOME Shell has adopted the window,
so the probe also waits for the id to appear in `_NET_CLIENT_LIST` before
asking the window manager to activate it. The old `sleep 5` had been covering
both by accident.

**Measured**, on linux-host-a, GNOME Shell 46.0, the four modules in one run,
`origin/main` at 5402b23 in a detached worktree against this branch:

| box | `origin/main` | this branch |
|---|---|---|
| quiet-ish (load avg 4-6) | 20 passed | 20 passed |
| 24 busy loops on 16 cores (load avg 20-31) | **7 skipped**, 13 passed | **20 passed** |

The load had to be manufactured. #163's three runs were a full suite and its
own failing sets did not reproduce on demand today at natural load, which is
the property that made the bug expensive in the first place; 24 spinning
processes stand in for the ~1300 tests that used to precede these four.

Under that load `origin/main` does not *fail*. It stops measuring, and says
almost nothing about it:

```
SKIPPED tests/test_linux_restore.py:105: the L7 harness could not hide a
  focused window, so nothing it says about restoring one means anything:
CONTROL focus A ok active=0xa00004
ABORT A did not hide
SKIPPED tests/test_linux_watch.py:103: the watch probe produced no report
```

`ABORT A did not hide` is the `sleep 2.5` after `windowminimize`, named
exactly. "The watch probe produced no report" is the other four, and carries
nothing whatsoever -- which is #163's complaint arriving in its purest form.
Seven of twenty measurements gone, and a run that reads as green.

Runtime, same modules alone: `test_linux_restore.py` 20.70s → **5.48s**,
`test_linux_tier1.py` → 5.84s. The fall is the same fact read forwards: a
fixed sleep pays its full cost on every run including the fast ones, and
these `slow`-marked modules are themselves part of the load that made the
others flake.

**What the instrumentation has already ruled out**, which is the point of
having it. The watch's setup budget was the obvious suspect for `watch`×2 and
`watch`×4, and the measurement says it is not the one:

```
TIMING {"what": "window_mapped", "ok": true, "polls": 1, "seconds": 0.03, ...}
TIMING {"what": "watch_ready", "ok": true, "budget": 29.88, "spent": 0.12, "margin": 29.76}
TIMING {"what": "escape_seen", "ok": true, "polls": 121, "seconds": 30.01, "timeout": 60, ...}
TIMING {"what": "put_back", "ok": true, "polls": 1, "seconds": 0.0, ...}
```

The watch is in place having spent 0.12s of a 29.88s budget, and the escape
lands at 30.01s against a grab due at 30.00s. So the original 12s was never
close on this box, and if `events` comes back empty again the answer is *not*
"the watch was late" -- it is a real question about the escape path, and the
report says which. The budgets were raised anyway (slice 3's modal 9s → 30s,
the watch's grab 12s → 30s), but a larger number alone is only a better
guess. The recorded margin is what makes the next overrun name itself.

**Not claimed.** The full suite was run, minus the two modules named above
that still hold the unbounded pipe read -- three of the five that used to
hang a local run are fixed here by `collect()`, as a side effect of needing
the trace. But it was not run against the *original* conditions of #163,
because those three runs are not reproducible on demand; they are the
evidence for the mechanism, not something re-measured after the change. A future run where every step settled in a fraction of its
limit and the assertion still failed is a real change in behaviour rather
than a busy box; that distinction did not exist before and is the point.

**Evidence.** Issue #163; D45 (instrument, never retry); D#13/D#14 (hidden,
and no quiet un-hide); `tests/linux_probe_support.py`;
`tests/linux_l7_probe.sh`; `tests/linux_slice3_probe.py`;
`tests/linux_watch_probe.py`; `tests/linux_tier1_probe.py`;
`src/ghostdriver/backends/linux/isolate.py`'s `SETTLE_S`, whose comment
records this same lesson already learned once inside the backend --
"code written from the Windows shape reads the state back too early".

### D#15. An embedded document: WebKitGTK's two GTK bindings gave opposite answers, and neither needed a wake

**Context.** L8, last in the Linux measurement chain (#6, #7-#14, #21 all
closed before this one started) and the same question D58 answered for
Chromium on Windows: does an embedded document's accessibility tree wake
on the first ask, and can a click and a write reach the page through it.
No Chromium engine exists on Linux; WebKitGTK stood in, on the current
development host (linux-host-a), with a new fixture (`tests/fixtureapp_web_gtk.py`)
loading the same `tests/fixturepage.html` D58 used on Windows.

**The two GTK bindings disagreed, and the disagreement is the finding.**
WebKitGTK's GTK4 binding (`WebKit` 6.0, `gir1.2-webkit-6.0`) never
published a document over AT-SPI at all: not once, across a dozen runs and
sixty-second waits, with the page's own `load-changed` signal confirming
`WEBKIT_LOAD_FINISHED` every time. Neither `WEBKIT_DISABLE_SANDBOX=1` nor
setting `org.a11y.Status.IsEnabled=true` on the bus before launch changed
this. WebKitGTK's GTK3 binding (`webkit2gtk-4.1`), reached through
`Gtk` 3.0 rather than 4.0, published the whole document tree over AT-SPI
**the first time anything asked, every time** -- no dormancy, no retry, no
delay worth measuring (children present at t+0 in every run). This is the
opposite of D58's Chromium, where the first walk had to *ask* before the
tree existed at all.

**So `walk_elements_awake` needed no wake step, and that absence is now
measured rather than assumed.** The function was already a plain walk
before this session (the docstring said so, honestly, as "unmeasured");
it stays a plain walk, because nothing observed here was ever dormant on
the engine that worked, and no amount of waking would have helped the
engine that never published at all. Adding a poll loop with no dormancy
to justify it would have been modelling, the thing this whole document
exists to avoid. What did change: `"document web"` -- the AT-SPI role the
working engine's document publishes under -- joined `WEB_HOST_CLASSES`
in `surface.py`, which is the one line `modality.py::surface_of`'s own
docstring already said would be the whole fix once this was measured.

**D75 does not hold across hosts, and should not have been read as if it
did.** It recorded "GTK 3 is not available from PyGObject" as a fact
about the machine that measured it, in support of `fixtureapp_gtk.py`'s
GTK4-only shape. `gi.require_version("Gtk", "3.0")` succeeds on linux-host-a.
The native fixture stays GTK4 (nothing forced a change there); the new web
fixture uses GTK3 because that is the binding that measurably works, which
this session would not have found by trusting D75 as a platform constant
rather than a point-in-time reading.

**Click needed no web-specific code.** `verbs.click_element` already
routes through `linux_input.act_via_action`, which calls
`do_action(node, 0)` regardless of the action's name (D#10's reasoning for
using the index rather than a lookup). A web button's action is named
`press`, not `click` as a native `Gtk.Button`'s is -- and it did not
matter, because nothing reads the name. `do_action` returned `True` and
the page's own status text changed, confirming the click reached the
script rather than just returning success.

**Typing does not have a tier-1 route, and this is the one real gap.** A
web `<input>` carries `Accessible`, `Action`, `Collection`, `Component`,
`Hyperlink`, `Text` -- and neither `EditableText` nor `Value`, unlike a
native GTK entry, which carries `EditableText` and commits with no split
(D#10). `linux_input.set_text_via_editable` already wraps its call in
`contextlib.suppress(Exception)`, so the missing interface produces a
clean `False` rather than a traceback -- the existing ladder needed no
change to handle it correctly. What it means: there is no way to write a
web field on this backend below tier 4 (XTest under the live-actuation
gate, D#111), which this session measured the absence of but did not
build a route through -- `type_text_element`/`send_keys_element` stay
empty ladders, as they already were.

**Password detection and tab selection needed no web-specific code
either.** `is_password = entry.role == "password text"` (`elements.py`)
matched a web password field's role exactly as it matches a native one's,
so the disclosure policy (D#34b) withholds it with no new code. A web
ARIA tab carried `SELECTED` before and after a click the same way a
native `page tab` does, confirming `is_selected`'s role-based state read
(D#104) generalises to the web case unchanged.

**Measured** with `tests/test_linux_l8.py` and its probe,
`tests/linux_l8_probe.py`, following the L7/tier1 shape: `Xvfb`,
`at-spi-bus-launcher --launch-immediately` under `dbus-run-session`, the
new fixture launched inside it, one JSON report line. Five tests, all
passing on linux-host-a: the wake, the click, the write's absence, password
detection, tab selection.

**What this does not cover.** Whether WebKitGTK's GTK4 binding will ever
publish a document over AT-SPI is not answered here -- it is recorded as
not fitting this strategy on this build, the D53 shape, not worked
around. A caller reaching WebKitGTK through the GTK4 binding on Linux gets
the same honest gap a Store-activated app gets on Windows. `region_evidence`,
`resolve_hosted_app`, `assess_uia` and `assess_msaa` remain unwired for
Linux -- `backends/linux/__init__.py` no longer calls the embedded
document unmeasured, but building an AT-SPI-shaped assessment against it
is a follow-on, not part of this measurement.

**Evidence.** Issue #15, issue #6 (the chain this closes); D58 (the
Windows counterpart); D#10 (native entry commits with no split); D#104
(role-based `SelectionItem`); D53 (an unfitted target is reported, not
worked around); D75 (GTK 3 availability, host-specific, corrected here);
`tests/fixtureapp_web_gtk.py`; `tests/linux_l8_probe.py`;
`tests/test_linux_l8.py`; `docs/LINUX.md`'s L8 entry and its
`walk_elements_awake` contract row.

### D#105a. The clipboard is a choice of tool by session, not a fallback chain

**Context.** D#40e's slice 4a deferred `NAMED_KEYS`, `EDIT_ACTIONS`,
`button_pair`, `copy_route`, `focus_route`, `ink_fraction`, `deepest_child_at`
and "the clipboard" to a later slice. PR #113 built all of them together with
the place-plus-value locator (D#105), but `docs/LINUX.md`'s own spec row
always named two clipboard mechanisms -- `wl-paste` / `xclip -o` -- and only
`xclip` shipped. Issue #105's own text still names both. Nothing in
`clipboard.py`, `input.py` or `reading.py` had a dedicated test before this;
the only exercise any of it got was through `tests/test_linux_studio_scratch.py`,
which is opt-in and needs a real Bambu Studio Flatpak installed.

**Decision.** `read_clipboard_text`, `snapshot_clipboard` and
`restore_clipboard` now dispatch on `WAYLAND_DISPLAY`: set, they run
`wl-paste`/`wl-copy`; unset, `xclip`. This is a choice, not a fallback --
`xclip` reaches an X11 selection, which under a Wayland session is not the
compositor's own clipboard (D70: the clipboard is the person's), so a
missing `wl-paste` on a Wayland session reads nothing rather than quietly
answering from the wrong clipboard. `DISPLAY` was rejected as the signal
because XWayland sets it too, so its presence alone would pick `xclip` on a
pure Wayland session.

**Not measured against a real Wayland compositor.** Both Linux hosts this
project has access to (`linux-host-b`, `linux-host-a`) run an X11 session --
`loginctl show-session -p Type` answers `x11` on linux-host-a, where this was
written, and neither `wl-paste` nor `wl-copy` is installed on it. The X11
branch is unchanged behaviour, exercised as it always was; the Wayland
branch is new code exercised only with `subprocess.run` faked
(`tests/test_linux_clipboard.py`), the same honesty D#105 already applied
to its own Windows half. It needs re-verification on a Wayland host before
this half of the tension is fully closed, the same way D#105 flagged its
`confirms_value` Windows implementation.

**Also added:** dedicated tests for `button_pair` and `deepest_child_at`
(`tests/test_linux_input.py`), which is D#40e's refusal ladder and D#40d's
no-op respectively -- both pure logic needing no bus, and both previously
asserted only by prose in D#40e, never by a test.

**Evidence.** Issue #105; D#40e; D#40d; D#105; D70; `docs/LINUX.md`'s
clipboard rows; `tests/test_linux_clipboard.py`; `tests/test_linux_input.py`.

### D#27. The actuation half runs against a real target, and does not always land

**Context.** D76 closed the read-only half of real-target validation and
left the other half explicitly open: "no workflow has driven a control end
to end against the real application under the interference watch. That
remains the operator's." This is that session -- an operator session on
`win-host` (a real Windows 11 Home desktop, not a fixture), driving the
runner (D57) against whatever real applications the box actually has, under
the interference watch (D62), through `run-workflow` exactly as any
operator would.

**The desktop was not manufactured for this.** No autologon rig, no
dedicated test account: the workflows ran as scheduled tasks with an
`Interactive` principal bound to the account already holding the console
(`schtasks`'s "run only when logged on"), which lands a process in the
same session as an already-open desktop rather than creating one. The
account's own prior session -- a real Windows Terminal window, a real
browser, Steam, 1Password -- stayed open and untouched throughout. One
finding came directly from that: launching Windows 11's own Notepad with
no file argument silently restored the account's actual previous document
(a PuTTY `README.txt`, not a blank buffer) rather than starting empty --
measured, not assumed, and the run was aborted and the process killed
before anything was typed into it. A driving script cannot treat "just
launched" as "blank canvas" on a real desktop; it must check title or
content first.

**Proven: a standard control, end to end.** Character Map's "Characters to
copy" box (`class=RICHEDIT50W`, a real Win32 rich-edit control, not this
project's fixture) was found, written to, and read back --
`find` → `set_value` → `read`, all three steps passing. The write landed
at tier 3 (`WINDOW_MESSAGE`, route `typed`); `verified` came back
`"display"`, not `"committed"`, because no `expect` was given -- the tool
told the truth about what it had and had not checked, exactly as D77 and
`set_value`'s own docstring describe. `find` additionally reported the
control `obscured: covered by CASCADIA_HOSTING_WINDOW_CLASS` (a real,
concurrently open Windows Terminal overlapping it on screen) -- reported,
not acted on, and the write succeeded anyway, because a window-message
write does not require being on top. A disturbance stayed information, not
a verdict (D28), on a desktop that was actually busy rather than the
fixture's controlled idle. `interference` and `watchdog_events` were both
empty for every workflow run this session -- nothing took the foreground
across the whole exercise.

**Contradicted: a pattern-less standard control did not respond to a
posted click.** Resource Monitor's own tab strip (`class=SysTabControl32`
-- a common control, not a vendor one) reports `0 accessible elements` and
`no child windows` from `surfaces`, an emptier reading than D76's vendor
`Pane` controls got. D76's model says a pattern-less real HWND is driven
by a posted click at a point (D53's ladder, tier `WINDOW_MESSAGE`); three
calibrated attempts to switch it from "Overview" to "CPU" -- the first
guessing an even five-way split of the control's full width, the second
correcting that guess but subtracting the wrong frame's origin (screen
`left` instead of the capture image's own left), the third using
`capture`'s own screenshot, cropped and measured directly, landing
correctly on the tab's centre -- never switched the tab. A follow-up
`capture` after the "correct" click confirmed the same "Overview"
highlight was still showing on screen: the click was not merely unproven,
it did nothing. The tool never claimed otherwise. Two honest shapes
appeared across the attempts, on the identical target and point: "every
tier delivered but none produced the expected result... verified is
'delivery_only', expected 'effect'" (the `{"changed": true}` postcondition
correctly found nothing moved), and, on a later attempt with no `expect`
at all, "no tier could act on this element (tried [3])" (delivery itself
declined, with no exception recorded). Which of the two a given attempt
gets is not explained by anything this session controlled, and is left
open rather than guessed at (D33). What is not open to doubt: this
control, real and standard-classed, does not take a posted click the way
D76's vendor Pane controls did, on this real target. D53's rule held --
the ladder reported the mismatch rather than papering over it with a
`disturbances`-adjacent guess -- and this is the numbered exception to
D76's generalization the way D76 itself was to the model that came before
it.

**A related, structural finding, not fixed here.** Classic Control Panel
applets (`main.cpl`, `inetcpl.cpl`, ...), launched the only way Windows
launches them (`rundll32.exe shell32.dll,Control_RunDLL <name>.cpl`), are
unconditionally refused by `modals`' own ambiguity guard --
`BLOCKED: 'Mouse Properties' is holding '<untitled RunDLL>'` -- because
`rundll32` creates a hidden owner window that the visible dialog is
structurally held by. This is not a bug to route around (D33, D53): it
means a whole common class of real Windows targets is unreachable for
actuation by construction, worth knowing before reaching for one as a
real-target stand-in.

**A second, separate gap: modern Notepad's text box is visible but
unreachable.** `describe --all` shows Windows 11 Notepad's edit surface
(`RichEditD2DPT`, nested under a `Microsoft.UI.Content.DesktopChildSiteBridge`
XAML-island host) plainly. `find` and `read`, with or without
`all_windows`, return zero matches for the identical locator against the
identical process. The read-only tree walk and the resolve path `find`
shares with every actuation tool disagree about what exists -- a real gap
between the two, worth its own issue rather than a guess folded into this
one.

**What this moves.** The real-target scorecard row D60 opened and D76 kept
open for "the operator's" half now has a real answer: actuation has run
against a real application, under the interference watch, and both an
honest success and an honest, reproducible non-success are on the record
with their traces. The row closes as "run: one proven, one contradicted,
both reported honestly" rather than "unrun". What stays open: why the
Resource Monitor tab strip declines a posted click that a Delphi/VCL
vendor Pane control accepted (D76) is not diagnosed here, and the Notepad
resolve gap is not fixed here -- each is worth its own issue and its own
measurement, not a guess spent from this one's budget.

**Evidence.** Issue #27 (successor to #3); D76 (the read half, and the
model this session found the exception to); D77 (`expect={"changed":
true}`, `verified` states); D53 (an unfitted target is reported, not
worked around); D33 (refuse ambiguity rather than picking); D28 (a
disturbance is reported, never a verdict); D48, D69 (deadline-polled
postconditions -- exercised by every `expect` in this session, over the
full window each time); D57 (the operator directory and runner); D62
(every tool call traced). Operator session on `win-host`, workflows
`issue27-charmap-edit` and `issue27-real-target-actuation` under
`C:\gd-operator`, reports timestamped 2026-09-19 08:48-08:58 UTC.

### D#30. Gate 4's ideal case, run: the same caption realized on two stacked pages

**Context.** D76's Gate 4 passed, but not by the route `docs/VALIDATION.md`
describes as the discriminating test: "the same caption on two *tab
pages*". Only one page was loaded in that session, so ancestor scoping was
proven on a repeated toolbar caption instead — a real test, but not the
one D31 was written for, where a wrong answer is plausible rather than
obviously wrong because the two matches sit at the same offset on two
different pages.

**What was run.** Windows' own File Explorer Options dialog (`explorer.exe
shell:::{6DFD7C5C-2451-11d3-A299-00C04F8EF6AF}`), on win-host's real desktop
— the same box and account D#27 drove, on a later session. This route
stays in-process in `explorer.exe` rather than going through
`rundll32.exe shell32.dll,Control_RunDLL`, so it sidesteps D#27's own
finding that the CPL route's hidden owner window trips `modals`' guard.
`modals` still reports the dialog *holding* an internal stub window
(`MSGlobalFolderOptionsStub`, the property sheet's own housekeeping
window) — a normal ownership relation, not the same block.

**The caption.** The General and Search pages both carry a button whose
window text is `&Restore Defaults`, character for character. The View
page's equivalent button is `Restore &Defaults` — the accelerator sits
before a different word, so it is not the same string and would not
satisfy an exact-text locator against either of the other two. Worth
recording because it is exactly the kind of near-miss D31 exists to
guard against: two captions that read the same to a person and are not
the same string a locator matches.

**Realizing both pages at once.** A property sheet page is created the
first time it is shown and, once created, is only hidden on tab switch,
never destroyed — so visiting General, then View, then Search left all
three pages' controls in the tree at once, one visible and two hidden.
Getting there needed a real posted click on the tab item, not a
programmatic selection: `TCM_SETCURSEL` (and UI Automation's
`SelectionItem.Select`, per the existing note in
`backends/windows/verbs.py::click_element`) marks a tab selected without
sending `TCN_SELCHANGE`, so the dialog's own page-switch handler — the
thing that actually creates the new page — never runs.

**The result.**

```
within=(class=#32770 text='General'): ['0x2014a']
within=(class=#32770 text='Search'): ['0x20174']
within=(class=#32770 text='View') [View has no such caption]: []
unscoped: ['0x20174', '0x2014a']
```

Unscoped, the caption is ambiguous, exactly as D33 says it must be. Scoped
to either page's own `#32770` container, `within=` returns exactly one
handle, and the two handles differ — the case D31 was written for,
confirmed on a real target rather than the fixture. Scoped to the page
that does not carry the caption, it returns nothing rather than the
nearest wrong answer, which is D33's refusal again, now exercised against
a real dialog's frame rather than a fixture built to exercise it.

**A hazard worth recording for the next Gate 4 session.** `VALIDATION.md`
points a tester at the Python API directly for this test, and getting a
tab's on-screen rectangle to post a click at (there being no `find`
route to a `SysTabControl32` item — the CLI's `find`/`describe` walk the
window tree only, and none of the accessible-element resolution the
`type=` locator field expects is wired into them) means sending
`TCM_GETITEMRECT` across processes. `SendMessage` with a bare local
pointer for a message like this is not automatically marshaled: it
crashed `Explorer.EXE` outright on the first attempt (access violation in
`comctl32.dll`, Windows' self-healing `userinit.exe` restarted the shell
within about a second — win-host was confirmed idle first, and the
restart's only visible cost was any Explorer windows the account had
open). The fix is `VirtualAllocEx`/`ReadProcessMemory` against the target
process, the usual cross-process marshaling pattern, checking the send
and the read both succeeded, and refusing to click on an implausible or
out-of-bounds rectangle before posting anything. None of this touches
ghostdriver's own code — the crash was in ad hoc exploration tooling
standing in for the human hand `VALIDATION.md`'s Gate 4 recipe assumes —
but a future session reaching for the same Python-shell recipe will want
the same guard.

**What this moves.** D76's Gate 4 caveat — "the runbook's ideal test...
was not available" — no longer holds against any target: it has now run,
on a real one, without a fixture built for it. The real-target scorecard
row's read-only half (D76: discovery, classification, scale, locator and
ancestor scoping, text reading, non-interference) gains its one missing
case; actuation end to end remains the state D#27 left it in.

**Evidence.** Issue #30; D76 (Gate 4); D#27 (the same win-host session
family, and the CPL/rundll32 modal-guard finding this reuses rather than
repeats); D31 (`within=` exists because this exact case needs it); D33
(refuse ambiguity, both directions); `docs/VALIDATION.md` Gate 4;
`backends/windows/verbs.py::click_element`'s note on `SelectionItem`
selection not notifying the application.

### D#62. The approval prompt states the lifetime it actually has

**The report, and what a second measurement did to it.** Issue #62 came
out of a session driving a Chrome pid and named two problems: the
approval happened as chat text rather than a dialog, and the same pid had
to be approved again after a Claude restart. Both read as defects. A
week later #125 re-measured the second one on a different target and
found the opposite: a Chrome grant recorded on 9/7 was still in force on
9/14, because that run had an operator directory and D65's store had kept
it. The 9/7 run did not. So the persistence worked, and had worked all
along.

**What was actually wrong is that nothing said which case it was in.**
Two sentences asserted a lifetime this server does not always have:

- the elicitation prompt -- *"This lasts for this session only"* -- which
  is the last thing a person reads before approving, and
- `SERVER_INSTRUCTIONS` -- *"Approvals last for this server run"* -- which
  is what the agent plans and relays from.

Both predate R1a. With a store configured they are wrong; without one
they fail to say *why* the person is being asked about an application
they approved this morning. That is one defect with two faces, and it is
why #62 was filed as a persistence bug: the behaviour was right and
unobservable, so the only thing left to infer from was a sentence that
was wrong.

**The rule.** *A lifetime that is knowable at the moment of asking is
reported at the moment of asking.* `SessionManager.consent_lifetime()`
composes the true sentence from the store that is actually in force; the
elicitation prompt uses it, a `needs_consent` result carries it as
`lifetime` so an agent relaying the question in chat relays the same
sentence the dialog would have shown, and the instructions no longer name
a lifetime at all -- they tell the agent to quote that field instead. The
no-store sentence names `GHOSTDRIVER_OPERATOR_DIR`, because "you will be
asked again" is a complaint and "set this and you will not be" is an
answer.

**The first half of the report, answered but not as asked.** #62 wanted
the approval rendered "as a real prompt, the way computer-use's
`request_access` does". It already is, where the client can carry it:
`attach` calls `ctx.elicit` first and falls back only on failure. There
is nothing this server can do to make a client that does not implement
MCP elicitation show a dialog -- and the fallback message said *"this
client cannot be asked directly"*, which the field read as this server
declining to ask. It now names whose limitation it is, and gives the
exact `grant_targets(allow=[pid])` call. What we did not do: keep a
capability flag and branch on it ahead of time. Trying and failing is one
round trip and is correct against a client that advertises the capability
and then refuses it; a flag would be a second source of truth about
something the attempt already answers.

**What this deliberately did not change.** The store, which was not
broken. `grant_targets` stays the record-the-answer path for clients that
cannot prompt (R1), and `elicited` and `operator_tool` stay distinct
sources, because the difference between a signature and an assertion is
still real.

**Evidence.** Issues #62 (field report, 9/7) and #125 (the 9/14
re-measurement that corrected it); R1, R1a, D65. Checked by
`tests/test_consent_lifetime.py`, which runs on both platforms because
its seam is `SessionManager`, not the `attach` tool (D#39).

### D#125. A standing approval per executable: yes, declared by hand, and it answers last

**The question.** D65 made an approval last exactly as long as the
process it was about -- *"that application, running"* -- so a target that
restarts is asked about again. In the field that is correct roughly
always and wrong for one case: an operator who has already decided, for
this machine, that this line-of-business client may be driven, and who is
now being asked a question they consider settled. #125 asked whether to
allow a standing approval per executable path, at the cost of that
promise. D35 -- a declared note beats a learned one -- was cited for it.

**The answer is yes, under two constraints, and the constraints are the
decision.** The feature on its own is three lines; what took the thinking
is what keeps it from dissolving R1.

**One: no tool writes the file.** `<operator dir>/standing-consent.json`
is read by this server and never created, amended or touched by it, and a
test asserts the bytes are unchanged across a `grant_targets` call. This
is not tidiness. R1 replaced a configured allowlist with elicitation to
buy one property -- consent that *the agent cannot fabricate* -- and a
standing approval an agent can write is a way to launder its own say-so
into the operator's. The file being hand-edited is the signature. The
server instructions now tell the agent it may propose the contents and
must not offer to write them.

**Two: it answers last.** `SessionManager.grant_for` resolves in order of
specificity: the pid's own decision, then its nearest decided ancestor's,
then the declaration. D35 reads at first like an argument for the
opposite -- put the declared thing first -- but D35 is about a person
against a *measurement*, and here both sides are the person. The pid
decision is their later and more specific answer, about the process in
front of them, so a file edited last week must not overturn "leave that
one alone" said a minute ago. That ordering is checked in both
directions, because the dangerous one is only half of it: a declaration
must not un-restrict, and an operator must also be able to allow a single
process of an executable they declared off-limits without editing a file
mid-task.

**The cost, stated where it is spent.** A standing approval really does
give up D65's promise: a restarted target is driven without anyone being
asked. So the grant carries `standing_for`, and `describe()` says *"[standing
declaration for <path>]; nobody was asked about this process"* wherever
the decision is shown. A result that presented this as an ordinary
approval would hide the single fact that distinguishes it.

**The second cost, accepted and not mitigated.** Matching is on the
executable path and nothing else, so a declaration for a browser approves
every instance of it, including the one pointed at production -- and
endpoints are precisely what R1's `list_targets` shows a person so they
can *see* what they are approving. Narrowing a declaration by command
line is a real follow-on; it is not smuggled in here, because a
half-specified match is worse than an honest whole-executable one. What
this does instead is make the declaration easy to write correctly: a
`needs_consent` result now carries `target.exe`, the image path spelled
the way the process reports it, which is not always the one an operator
would have guessed.

**Smaller choices.** `restrict` is accepted alongside `allow`, and wins
where an executable appears in both -- a declaration that contradicts
itself is a mistake and the safe reading of a mistake is the refusal. A
file that cannot be parsed approves nothing *and says so* in the next
`needs_consent`, because an operator with a typo would otherwise get the
behaviour of having declared nothing with no way to tell that from having
declared nothing. An entry of the wrong shape invalidates the whole file
rather than being skipped: three quarters of a consent policy is not a
consent policy. A declared decision is never copied into D65's per-pid
store, which would outlive the declaration -- deleting a line would leave
the approval standing in a folder nobody thinks to look in. Comparison is
through `os.path.normcase`, so a hand-typed path matches on Windows and
two paths differing in case stay two files on Linux; symlinks are not
resolved on either side, since `exe()` is already the resolved target and
resolving the declared side too would silently widen a declaration to
every name pointing at that file. A process whose image cannot be read is
asked about: not knowing what a target is, is not evidence it was
declared. And the file is re-read when it changes rather than at start
-- withdrawing a standing approval must not need a redeploy, because a
revocation that waits for one is a revocation the operator believes has
taken effect when it has not, which is D#62's defect wearing different
clothes. It costs one `stat`, on the path already known, only where
nobody has decided about the target.

**Evidence.** Issue #125 (and the 9/7 report in #62 it re-measured); R1,
R1a, D65 (the promise this spends), D35 (the rule that does not apply,
and why). `tests/test_standing_consent.py`, platform-neutral by
construction -- the executable lookup is injected, so nothing there
starts a process or reaches a backend (D#39).

### D#2. A place entry with no region denies the whole of `within`

**Context.** D72's own "what it does not do" named the gap: a place is a
rectangle in one window's frame, and a control that scrolls inside that
window breaks the anchor -- the same control sits at a different place
depending on scroll offset, so a fixed region either misses it after a
scroll or, worse, silently denies whatever else scrolled into that
rectangle instead. Issue #2 weighed three answers: anchor to
neighbouring content, anchor to the scroll container plus an offset
within its content, or deny the container wholesale.

**Why the container, not content or an offset.** The first two both
need *exact* text out of the region to anchor on -- and D#1, probing
that question against a real target (`charmap.exe`'s owner-drawn grid),
came back negative on all three routes it had to offer: no accessible
surface, no clipboard copy, no export command. Building a content
anchor or a scroll-offset anchor on a route that does not yet work
would be code with nothing under it. The container answer needs none of
that: a window is already a locator the denylist can resolve, and its
extent is already computable (`GetClientRect`) without reading anything
painted inside it.

**What changed.** A denylist place entry's `region` is now optional:
`{"within": <locator>, "note"?}` with no `region` denies any actuation
aimed anywhere inside `within`'s whole client area, computed fresh per
actuation the same way a region's rectangle already was (`deny.py`'s
`_denied_region`, `winapi.client_size` added alongside the existing
`client_centre`/`client_to_screen`). A malformed entry -- `region`
present but incomplete, or `within` missing outright, with or without a
`region` -- still fails the profile load (D72's own rule, unchanged).
Proven on the fixture's paging grid (`tests/test_deny_regions.py`,
`--grid-pages`): a click at a fixed point is refused before any paging,
posting `pagedown` to the grid succeeds, and a click at that same fixed
point is refused again afterward -- the denial does not consult, and so
cannot be defeated by, the scroll offset.

**What this does not do.** It is coarser, on purpose: everything in the
window is denied, not just the control that scrolls, which can matter
on a window that hosts more than one thing. That is the trade the issue
named going in ("coarse and available today as a workaround") and
exactly what D5's fail-closed spirit asks for when a target cannot be
named more precisely -- refuse more than necessary rather than leave a
control effectively unreachable by the denylist. Content-anchored and scroll-offset anchoring remain open, gated on a
future measurement reopening the exact-text question D#1 closed
negative -- issue #20 (OCR) is exactly the issue that measurement would
feed, per D#1's own evidence trail.

**Evidence.** Issue #2; D72 (the gap this closes); D#1 (why the other
two options are not built yet); D5 (failing closed, three times over).
`tests/test_deny_regions.py`:
`test_an_entry_with_no_region_denies_the_whole_of_within`,
`test_a_whole_window_denial_holds_across_scroll_positions`,
`test_an_entry_with_no_within_fails_the_profile_load_even_without_a_region`.

### D#17. An API oracle stays out of the driver; it belongs to orchestration

**Context.** Issue #17 is one of the five spec §12 rows
(`docs/product/features/deferred-scope-tracking.md`) kept visible without
being scheduled. Unlike #16, its body does not leave the question open --
it already argues its own conclusion ("Why it stays out of the driver")
citing D59 and D46. What it lacks is the same thing #16 lacked: an entry
in this log for the feature doc's non-goals to point at. Without one, the
row reads to the next triage run as unscheduled work rather than decided
-- which is exactly the gap the feature doc's Notes section named for #17
and #18 after D#16 closed #16 alone, and exactly why this session was
dispatched against #17 rather than left to keep re-raising the same
question.

**The idea, and why it is real.** An HTTP/API client that checks, out of
band, whether an action driven through the UI took effect in the system
behind it -- a test oracle independent of the surface being driven. It is
the clean answer to the read gap D46 leaves open: if the API can confirm a
value, the driver does not need exact text out of an owner-drawn grid's
pixels at all. That gap is real (D46's own "what that leaves open"), which
is why this is recorded as declined rather than dismissed.

**Why it does not belong here regardless.** D59 drew the line above
`backends/` on purpose: everything above it reads `WindowNode`s and
`AccessibleElement`s, one model for both platforms. An API client reaches
past that model entirely, into whatever system the target happens to be
backed by -- a database, a message queue, a REST service, one target's
and no other's. Housing it behind this tool surface would answer, from
inside the driver, a question the driver's contract was never written to
answer: not "what does the surface show", but "what did the system record".
D1 sharpens the same point from the other direction -- the fixed-surface
constraint holds because every capability added here is a capability of
*the tool*, usable against any onboarded application. An API oracle is the
opposite: it cannot be general, because every target's API is its own.
Onboarding a second target would mean adding a second, unrelated oracle
behind the same tool name, which is the fork D#16 already declined for a
browser driver, for a different reason arriving at the same place.

**Decision.** An API/HTTP oracle is out of this repository. If it is ever
built, it sits on the orchestration layer this driver is deliberately
underneath -- issue #18's row, the same sibling layer D#16 named for a
browser driver -- reading the driver's own postconditions and tracing
(D62) alongside its own system-specific check, not folded into a tool
here.

**What would reopen it, and what would not.** Nothing here narrows D46's
open question -- exact text out of an owner-drawn region is still
unsolved, and issue #20's clipboard/export probe is still the gate on it.
An oracle proves useful *there* is not a reason to build it *here*: it
reopens only if a future spec places verification-against-the-backing-system
inside the driver's own contract, which would have to overturn D59, not
merely cite the gap D46 left.

**Evidence.** Issue #17; spec §12; `docs/product/features/deferred-scope-tracking.md`;
D59; D46; D1; D#16 (the sibling decision this one parallels).

### D#63. The pixel-judged flag rides on `capture`, where classifying a control is free

**Context.** #51/D#51 made `enabled` honest in prose: `find`/`describe` and
the `WindowNode`/`AccessibleElement` docstrings now say it is the
`WS_DISABLED` bit (or UIA's `IsEnabled`), not proof a control will act, and
an owner-drawn control can report it while painting its own greyed,
do-nothing state. What #51 explicitly left out was a *per-control* verdict,
because that needs the `surfaces` classification -- reading
`RegionEvidence` off the live target thread -- which `find` deliberately
does not run per element: a listing would turn into a per-node round trip
for an answer that is usually "native, ignore this."

**The question was where a per-element verdict could be free.** #63 asked
for a cheap proxy: only when a control already resolved through the
pixels/owner-drawn path, or is being captured. `capture`, given a `locator`,
already resolves exactly one node to render it -- that resolution is the
whole cost `find` avoids paying per row. Classifying that one node is one
region's worth of evidence, not a walk, so `capture` is where the flag
lives, not `find`, `describe`, or a new tool.

**What changed.** `surface_map`'s per-node classification was factored out
into `classify_node(node, gather)` (`surface.py`) -- unchanged behaviour,
same "gather only when undecided" rule, just callable on one resolved node
instead of a walked tree. `capture`, given a `locator` that resolved to a
`WindowNode` (not an `AccessibleElement` -- those already carry UIA's own,
more honest `enabled`, per D#51's docstring), classifies it and adds a
`surface` field to the result: `kind`, `access`, `reason`, and a `note`
pointing back at D#51. On any other backend classification -- native, web,
unknown -- the field is absent, the `actionable`-only-when-False rule (D66)
applied a second time: every other verdict is not the case `enabled` gets
wrong, and stamping it on every capture would be noise nobody reads.

**Absent, not erroring, off Windows.** `region_evidence` is not wired up on
the Linux backend yet (`backends/linux/__init__.py`, D#15's own note).
`capture` already works on both backends; this flag being Windows-only
must not make it work on neither. `current().region_evidence` raising
`UnsupportedPlatform` is caught, and the field is simply left off --
consistent with "the flag appears where it is free and is simply absent
otherwise," the option #63 asked to weigh.

**No target knowledge added.** `classify_node` uses the same structural
evidence `classify_region` always has -- child windows, text, the
accessibility element count and budget -- and the caller-visible field
carries no class list, matching the constraint #51 and #63 both hold to.

**Verification.** `classify_node` is tested platform-neutral in
`test_surface.py`, against fakes, the same way the rest of `surface.py`
always has been: it agrees with `surface_map` on the same node, gathers
only when undecided, and degrades the same way without a `gather`. The
`capture`-level wiring (`_judge_by_pixels`) is tested the same way in
`test_capture_pixel_judged.py`, including the `UnsupportedPlatform`
degradation no Windows box is needed to exercise. `test_windows_grid.py`
adds the one measurement that does need Win32: capturing the fixture's
painted grid (no children, no text, nothing beneath it on the
accessibility surface) carries `surface.kind == "owner-drawn"`; capturing a
real button next to it carries no `surface` field at all.

**Evidence.** Issue #63 (follow-up to #51/#52, D#51); `src/ghostdriver/
surface.py` (`classify_node`); `src/ghostdriver/tools/screen.py`
(`_judge_by_pixels`, `capture`); `tests/test_surface.py`;
`tests/test_capture_pixel_judged.py`; `tests/test_windows_grid.py`.
### D#19. The `vm` trigger has not fired, and it now says where a firing gets written

**Context.** Issue #19 is the fourth of the five spec §12 rows
(`docs/product/features/deferred-scope-tracking.md`), and the first of the
*conditional* kind to be dispatched. It is not declined on architecture the
way #16 and #17 were; it is held against a named trigger -- "after
`hidden_desktop` proves insufficient" -- and it is labelled `env: windows`.
The feature doc predicted that a row of this kind needs no record in this
log, because "a conditional item survives triage on its trigger: the row
says what has to happen first, and a run that checks finds nothing fired."

**That prediction is now measured, and it is false.** #19 was dispatched for
implementation on 2026-09-20 -- the third of the five deferred rows to be,
after #16 and #17 -- and it was dispatched to a *Linux* session against an
`env: windows` label. So neither label gates anything: the `deferred` label
routes triage to the feature doc (which is what it was for) and the `env:`
label tells a human which box to be on, but the only thing a dispatcher
reads is whether the issue is open. The distinction the feature doc drew
between architectural and conditional rows describes the *reasons*
correctly and the *mechanism* not at all. An open issue is a dispatchable
issue, whatever is written inside it.

**The trigger, restated, because this record now holds it.** Not every
limit of `hidden_desktop` counts. It is launch-only, because desktop
assignment is fixed at process creation (D51, D53); it fits classic Win32
and not Store-activated targets (D53); a target it cannot fit is *reported
as such, not worked around* (D53). None of those are the trigger. The
trigger is different in kind: **a target that `hidden_desktop` accepts and
then fails to isolate** -- focus escaping the hidden desktop, or a target
that detects it and behaves differently. The Linux counterpart, the nested
display, carries the same trigger.

**The check, and what a check can honestly be from the wrong platform.** A
Linux session cannot put a Win32 target on a hidden desktop, and did not
try. But the check that matters was never a machine check. A firing is a
measurement, and a measurement that is not written here did not happen for
any purpose this project has -- which is the premise the whole log rests
on. So: does anything on record show `hidden_desktop` accepting a target
and then failing to isolate it? It does not.

- D51 measured the guarantee as *structural*, and contrasted it with
  `minimized` on exactly this axis: `minimized` is observational, watches
  for an escape and puts the target back, and has a watchdog because one
  quiet trial proves nothing. On a hidden desktop there is nowhere to
  escape to.
- D53 measured real applications, which is the measurement that could have
  fired this. `charmap.exe` and `winver.exe` were accepted, described,
  driven and captured with their windows never on the operator's screen.
  `notepad.exe` was *not accepted* -- Store activation ignored the
  `lpDesktop` and the session saw no windows at all. That is the unfitted
  case D53 settled, which #19's own body names as not the trigger.
- The Linux side is built and makes the same structural claim
  (`src/ghostdriver/backends/linux/hidden_desktop.py`, D#8, D75).

Nothing between D51 and today records an acceptance that then failed.

**What the check also found: half the trigger is close to unreachable.** Of
the two forms the issue names, focus escaping the hidden desktop is not
something the strategy can do quietly the way `minimized` can. A window's
desktop is fixed when the window is created (D51, D53), so a window on the
hidden desktop has no foreground to escape to and no way to move to one --
which is why the failure that *did* show up in practice was the Store-app
one, where the target never lands on the hidden desktop at all. The live
half is the other: a target that detects the desktop and behaves
differently. That is also the half a VM genuinely answers, because a
hidden desktop is detectable and a machine is not. This is not grounds to
build anything. It narrows what to watch for, because "proves insufficient"
read as though the two halves were equally likely and they are not.

**Decision.** Issue #19 closes with no code. The contingency does not close
with it -- it moves from the tracker into this log, which is where the
things that have to survive are already kept. Concretely:

- The trigger stands exactly as restated above. Nothing here narrows what
  would justify a `vm` strategy; only where the justification is recorded.
- **A firing is recorded here, as the `D#<issue>` of the issue opened for
  it, citing this entry.** That is the thing #19 never said, and the reason
  a session told to "confirm the trigger actually fired" had nowhere to
  look. It is not a gate run: `docs/VALIDATION.md` names no isolation
  strategy in any of its six gates, so Gate 6's non-interference check
  would not distinguish a hidden desktop that held from one that was never
  used.
- Spec §12's row is marked answered and points here, and
  `test_structure.py::test_an_answered_deferred_row_points_at_a_decision_that_exists`
  fails if that pointer names a decision nobody wrote. A promise that lives
  only in a decision record gets broken once and then found later (D60);
  this one is checked on every run.

**What would reopen it, and what would not.** A recorded measurement of
`hidden_desktop`, or of the Linux nested display, accepting a target and
then failing to isolate it. Not "the current strategy is awkward". Not a
target it refuses to fit: a second Store-activated case is more evidence
for D53, not evidence for a VM. Reopening means a new issue whose decision
cites this one, not a reversal of it -- this entry does not decide against
the `vm` strategy, it decides that an unfired contingency belongs in the
log rather than in an open row that keeps being handed to implementers.

**Evidence.** Issue #19; spec §12;
`docs/product/features/deferred-scope-tracking.md`; D51; D52; D53; D55;
D60; `src/ghostdriver/backends/linux/hidden_desktop.py`;
`docs/VALIDATION.md` (six gates, no isolation strategy named in any);
D#16 and D#17 (the sibling closures -- declined, where this one is unfired).

### D#18. The assertion DSL was not deferred; it was built under another name

**Context.** Issue #18 is the last of the five spec §12 rows
(`docs/product/features/deferred-scope-tracking.md`) to be dispatched, and
the last of the *architectural* kind. Its row reads "Separate spec, built on
this one". The issue body argues the hazard well: the driver already has
assertion primitives (D57's workflow runner, D31/D32/D48's expectations,
D62's tracing), a DSL is a language on top of them, and a language on top of
a runner is the classic shape of the creep D60 caught once already -- "it
starts as a thin wrapper over the runner and accretes driver logic until the
boundary is gone." It closes by asking that, if picked up, the boundary get a
guard the way the module-size promise got one.

**The row is false, and has been since D#84.** This entry was expected to be
a third declination in the shape of D#16 and D#17. It is not, because the
first thing a dispatched session does is look at the code, and the code says
the DSL is built. `src/ghostdriver/workflow.py`, measured on this branch:

| Commit | Lines | What it added |
|---|---|---|
| `20cc197` (D57) | 297 | steps, dotted-path assertions, report |
| `7061eaa` (D#84) | 504 | `params`, `provenance`, `verified`, `delivery_only`, `when` |
| `19ab915` (D#85) | 682 | param binding, branch evaluation |
| `32e182b` (D#97) | 817 | `repeat_until`, `for_each`, bounded |
| `f0ff298` (D#106) | 939 | `on_disturbance` handlers, bounded and named |
| `ffcc9d5` (D#112) | 948 | replay reports what held *now* |

Variables, conditionals, bounded loops, event handlers, assertions, and a
provenance record: that is a declarative test-orchestration and assertion
language, with a closed vocabulary (`STEP_KEYS`, `BRANCH_KEYS`, `GUARD_KEYS`,
`REPEAT_KEYS`, `FOREACH_KEYS`, `HANDLER_KEYS`) that refuses an unknown key
rather than ignoring it (D#84, D33). Three times the size it was when the
row was written, and none of the five commits mentions #18.

**Why nobody noticed, which is the part worth keeping.** The row says "DSL".
The work shipped as **macros**. `docs/MACROS.md` opens by saying the
reframe that made the work tractable -- "a macro is `workflow.py` and `batch`
joined and given a lifecycle... not a new subsystem" -- and that reframe is
both correct and exactly what hid it: each of #84, #85, #97, #106 and #112
is visibly smaller than "an orchestration and assertion DSL", so each author
was right that they were not building the deferred thing, and the five of
them together were. A deferred row is not consulted by someone extending an
existing file; it is consulted by someone proposing a new subsystem. The row
was therefore guarding an entrance nobody used.

**The phrase "the orchestration layer" was doing two jobs.** D#16 and D#17
both decline a thing by pointing at "the orchestration layer this driver is
deliberately underneath -- issue #18's row". Those pointers are not wrong,
but they mean a different layer than the row does, and the collision is what
let the row survive being implemented:

- *Sequencing this driver's own calls, with assertions* -- the macro format.
  Everything it touches is a result this driver produced, so it stays inside
  the D59 model and reads `WindowNode`s and `AccessibleElement`s like every
  other thing above `backends/`. **Built, here.**
- *A harness coordinating this driver with tools that are not desktop
  drivers at all* -- a browser protocol (D#16), an HTTP oracle against one
  target's own backing system (D#17). That reaches outside the D59 model
  entirely, which is the reason both were declined. **Not built, not here,
  and this entry does not change that.**

Read with that split, D#16 and D#17 stand unamended; their "sibling layer"
is the second sense. What is corrected is the row, which names the first.

**The hazard the issue named was real, and it held.** Worth stating plainly,
because the row's warning being *accurate* and *too late* are separable
claims and only the second is true. Measured on this branch:

- `workflow.py` imports nothing platform-specific and nothing that drives:
  stdlib at module level, and three modules from inside the package --
  `tools.stepper` (D#83's shared step gate), `tools.recording` (D#112), and
  `policy` (recording the run as the operator's consent, D57). It reaches
  the target through the toolbox handed to it and through nothing else, so
  it is still tested with fakes.
- Every leaf is an ordinary tool call that re-authorizes. `RUNNABLE_TOOLS`
  in `tools/stepper.py` is an allowlist, not a denylist, so a new tool is
  unreachable from a macro until someone names it there; the lifecycle,
  consent and foreground tools are not in it (D#83, `tests/test_stepper.py`).
- The control-flow forms are bounded by construction -- nesting depth
  (D#84), loop iterations (D#97), handler firings (D#106) -- and a handler
  cannot recurse into itself.
- A guard's condition is in the locator/`expect` vocabulary and never
  embedded code (D#84), so a macro stays inspectable and denylist-checkable.

So the DSL did not accrete driver logic. What it did accrete is *headroom*:
`tools/macro.py` is 400 lines against a `TOOL_MODULE_LIMIT` of 400, the
largest module under `tools/` and the only one with none left.

**Decision.** Issue #18 closes as **built, not deferred** -- the one row of
the five that is answered by reading the source rather than by an argument.
Concretely:

- Spec §12's row is marked answered and points here, and
  `test_structure.py::test_an_answered_deferred_row_points_at_a_decision_that_exists`
  fails if the pointer resolves to nothing.
- `docs/MACROS.md` says which row it satisfies, and stops saying "specified,
  not built" -- it was the stale status line, as much as the vocabulary gap,
  that kept the two names from meeting.
- The boundary gets the guard the issue asked for, aimed at the boundary
  rather than at the size. See below.

**The guard, and why it is not a line limit.** The issue analogized to D60's
module-size promise, and a line cap on `workflow.py` is the literal reading.
It is the wrong one: size is not what the issue was afraid of, and 948 lines
of closed-vocabulary parser is not the failure -- a 300-line runner that
imported `resolve` would be. The promise actually load-bearing here is the
one D57 stated and `workflow.py`'s own docstring repeats: *the runner is pure
with respect to the desktop; the toolbox and the watch are handed in.* That
promise currently lives in two docstrings, which is precisely the position
the module-size promise was in when D60 found it broken.

`test_structure.py::test_the_workflow_runner_reaches_the_target_only_through_its_toolbox`
names the three in-package modules `workflow.py` may import, with the reason
beside each, and fails on a fourth. It fails in both directions, like
`KNOWN_UNWIRED`: an entry that is no longer imported is stale and comes off.
A fourth entry is not forbidden -- it is required to be argued for here
first, which is the whole mechanism this log is.

**What this does not decide.** Not whether the macro vocabulary should grow
further: #97, #106 and #112 each earned their form, and nothing here says
the next one cannot. Not the second sense of "orchestration layer", which
D#16 and D#17 hold. And not `tools/macro.py`'s zero headroom -- that is a
split when it next needs a line, per D60's own rule that a module over the
limit wants a split and not a bigger limit, and it is recorded here so the
person who hits it knows it was seen rather than missed.

**What would reopen it.** A concrete capability the macro format cannot
express, argued as a capability rather than as a language: that is an issue
against the format (the way #97 and #106 were), not a revival of this row.
The row itself does not come back -- "build a DSL" has been answered by
building one.

**Evidence.** Issue #18; spec §12;
`docs/product/features/deferred-scope-tracking.md`; `src/ghostdriver/workflow.py`
(948 lines, and the six commits tabled above); `src/ghostdriver/tools/stepper.py`
(`RUNNABLE_TOOLS`); `src/ghostdriver/tools/macro.py` (400 of 400);
`docs/MACROS.md`; D57; D31; D32; D48; D62; D59; D60; D33; D#75; D#83; D#84;
D#85; D#97; D#106; D#112; D#16 and D#17 (the sibling closures, whose pointer
at this row is disambiguated rather than withdrawn); D#19 (the fourth row,
unfired rather than built).

### D#46. The portable agent contract branch is 168 commits stale, and stays dropped

**Context.** Issue #46 is a 2026-09-05 archaeology-sweep find. The 2026-09-04
fleet-wide rollout of a portable Claude/Codex agent contract
(steiner385/claude-config#15) opened #31 here, proposing to make `.agents/`
the canonical source and render `CLAUDE.md`, `AGENTS.md` and skills from it.
#31 was closed the same evening with no comment and no merge; #32 was closed
as its duplicate. The branch, `chore/portable-agent-contract`, was never
deleted. #46 asked this session to decide: adopt it (reopening from the
branch) or opt out.

**The branch is not stale by a little.** Measured against `origin/main`
today: the merge-base is `465432b`, and `main` has moved 168 commits past it
while the branch has moved none past its own tip (`c56aff5`, 2026-09-04). The
diff between them is 188 files, +2894/-24055. That deletion is not
noise -- it is the entire Linux backend (`src/ghostdriver/backends/linux/*`,
roughly twenty modules), most of `tests/test_linux_*.py`, the macro tool
suite (`tools/macro.py`, `tests/test_macro_*.py`), and 4267 of
`docs/DECISIONS.md`'s current 7282 lines: D57 through D#19, all of the
`## Revision, 2026-09-02` section and all of `## Iteration 4`. None of that
existed when the contract branch was cut, so the contract's own diff is not
what deleted it -- but merging the branch as it stands would still delete
it, because a merge does not know the difference a rebase would have caught.

**Why #31 reads as deliberate rather than dropped.** The issue's own body
raises this, and it holds up: `CLAUDE.md` is bespoke -- naming this project's
own conventions (environment gating, `D#<issue>` numbering, the 400-line
tool module limit, mypy run once per backend) -- and the contract's
`core.md` would have replaced it with fleet-generic instructions.
`docs/DECISIONS.md` describes itself, in its own header, as written so a
decision "can be *disagreed with* later -- which needs the reason, not just
the outcome." A contract built to be portable across repos has no channel
for either -- portability and this project's bespoke conventions are the
same trade-off, named twice.

**Decision.** Opt out. `chore/portable-agent-contract` is not merged or
rebased; it is deleted, and this repo keeps its own `CLAUDE.md` and
`docs/DECISIONS.md` rather than adopting `.agents/`. Concretely:

- The branch is deleted from `origin` -- no open PR points at it, and #31
  and #32 are both closed.
- steiner385/claude-config#15's rollout tracker gets a comment recording the
  opt-out, so the fleet inventory reflects this repo correctly instead of
  showing a silently dropped PR.
- Nothing under `src/` or `tests/` changes. There was never a version of the
  contract that applied to the codebase as it exists today, only to the one
  168 commits ago.

**What would reopen it.** Not "the fleet standardized and this repo is the
odd one out" -- that restates the trade-off this entry just made. What would
reopen it is a contract revision that can carry this repo's own conventions
(`D#<issue>` numbering, the environment gates, the per-backend mypy split)
without flattening them into fleet-generic text, cut against `main` as it
stands rather than against a September snapshot.

**Evidence.** Issue #46; steiner385/claude-config#15; PR #31 (closed, no
comment, no merge, 2026-09-04); PR #32 (closed as duplicate); branch
`chore/portable-agent-contract` at `c56aff5`; merge-base `465432b`; `git diff
--stat origin/main origin/chore/portable-agent-contract` (188 files,
+2894/-24055).

### D#145. The menu's keyboard route confirms each phase, and a result says which routes ran

**Context.** `tests/test_windows_menus.py` began failing intermittently on
CI with the merge of #139 (D#135), at least ten times in a week, on
changes that could not reach it. The signature never varied: the item
resolves, `tier_used` is `None`, no tier's postcondition holds. The ladder
made it one-way -- `menu_keys` queued a Return and reported delivery; when
the label had not changed inside the verify window the actuator fell to
the posted pair, which ends a menu that is not under the pointer (D#135),
and after that nothing can hold.

**What was measured, and what was not.** Locally the module passed 12 of
12 runs, and a probe over ten menu openings found the item reading back as
highlighted after the first `MN_SELECTITEM` every time. So the cause is
not reproduced on this machine: it needs CI's load. Two candidates stay
open -- the selection not taking before Return is posted, and Return not
being consumed (or the owner's handler running late) inside the window.
The result could not tell them apart, which is the defect that can be
fixed without knowing which it is (D45).

**Decision.**

- **`menu_keys` confirms each phase and names the one that fails.** The
  item must read back as highlighted (`MF_HILITE`) before Return is
  posted; re-selecting while waiting is idempotent. After Return the menu
  must end, because ending is a menu's answer to Return. Either not
  happening raises with the count and the milliseconds waited, and the
  result carries it as `declined`. Return is posted once. This is a wait
  for a condition, not a retry: nothing is sent twice that could act
  twice.
- **The postcondition clock starts when the choice was made.** Because the
  route returns only once the menu has ended, the verify window no longer
  begins at "a keystroke was queued". A slow menu costs the time it took
  and the label still gets its whole window.
- **A result says which routes ran.** `routes_attempted` rides beside
  `tiers_attempted` -- two rungs on one tier read `[3, 3]` and said
  nothing -- and a rung that returned without delivering is recorded in
  `declined` like one that raised. `declined` is reported on successful
  results too: a ladder that got there on its second rung says what the
  first one did.
- **The tests print the explaining fields.** pytest's truncated repr hid
  `error` and `declined` in every CI occurrence; the assertions now show
  them, with the routes and disturbances.

**What this does not claim.** That the flake is fixed. If the cause is the
handler running late, the second bullet removes it; if it is something
else, the next occurrence will say so in its own assertion message, which
is the point.

**Evidence.** `tests/test_windows_menus.py`: Return waits for the
highlight and is posted once; an item that never highlights is named and
Return is not posted; a menu that does not end is named; a menu that
vanishes mid-selection is named; a failed choice reports its routes.
`tests/test_actuate.py`: routes beside tiers, a quiet decline recorded, an
unnamed attempt reported by tier. Issue #145; D#135; D45; D28.

### D#182. A copy that did not work is not a page of no rows

**The field report.** `test_a_grid_that_does_not_page_says_the_view_did_not_change`
failed once on CI with `assert True is False`: `advanced` came back true
on a fixture grid that ignores PageDown. Same commit, same runner image,
passed on the attempts either side. The assertion discarded both reads,
which were the whole of the finding.

**What was found in the code.** `grid_seek` compares each copy with the
one before it. The copy route can fail without the grid having changed:
the control did not change the clipboard inside its 1.5 s, or another
program held the clipboard when it was read. `grid_seek` turned that
failure into `[]` -- a page of no rows. An empty page followed by the
real one is two *different* reads, so the loop went round again, found
the third equal to the second, and reported `reached_end` with
`pages_read == 3`: exactly the shape `advanced` reads as "the view
changed". On a loaded runner the first copy timing out is the ordinary
way to get there. Not proven to be what happened in that run -- the run
kept nothing to prove it with -- but it is a defect on its own terms: the
tool said a grid had paged when a copy had failed.

**Decision.**

- **A failed copy is not a page.** It does not count toward `pages_read`,
  never becomes the page the next one is compared with, and sends no key.
  The view has not moved, so the same copy is asked for again; two
  failures running stop the seek, which then says `copy_stopped` and why,
  with `reached_end: false` -- "the route stopped answering" is not "the
  value is not in the grid".
- **Nothing is absorbed.** Every failed copy is listed in `copies_failed`
  with the route's own reason, including the one a second attempt got
  past. The clipboard is shared with the person and every other program,
  so a copy that does not land is an ordinary event, handled the way a
  postcondition is polled; what D45 forbids is losing the evidence, and
  the result keeps it.
- **The result carries what it decided from.** `page_rows`, the row count
  of each page as read, rides beside `pages_read`. The test prints those
  fields, so the next occurrence -- if this was not the cause -- shows its
  reads.

**Not addressed here.** A copy the control answers *after* the timeout
changes the clipboard once the prior contents have been put back. That is
the person's clipboard, and it is its own issue.

**Evidence.** `tests/test_windows_grid_seek.py`: a copy that fails once is
listed and the grid still reads as not advanced, `page_rows == [3, 3]`; a
route that never answers stops after two, says so, and does not claim the
end or the value's absence (`env: windows`, the fixture grid, the
backend's copy route made to fail). Issue #182; D63; D64; D45.

### D#186. A copy answered after the route gave up is put back

**Context.** Found reading `copy_route` for #182. The route posts
`WM_COPY`, waits 1.5 s for the clipboard's sequence number to move, and
then restores what the clipboard held -- whether or not anything arrived.
A posted message is not withdrawn by giving up on it. A control that gets
to its Copy command late writes the clipboard *after* the route has
returned, and nothing put it back: the person is left holding grid rows
they never copied, with no result anywhere to say so. D70 promises that
every format is saved and put back around each copy; this was the hole in
it, and a loaded machine or a large grid is all it takes.

**Decision.** When a copy times out, the clipboard is watched for a
further ten seconds, off the calling thread.

- **A change is attributed by its owner.** `GetClipboardOwner` names the
  window that last wrote the clipboard. A change owned by the target's
  process is the late answer: what the clipboard held before is restored,
  and that is recorded.
- **Anyone else's change is theirs.** The person copying something while
  a late answer is pending must not have it undone, so a change the target
  does not own is left alone -- and becomes the new "before", because it
  is what a late answer would now destroy.
- **It is said.** The timed-out result's own detail says the clipboard is
  being watched and for how long, and what a late answer did rides on the
  next copy's caveat, since the call it belongs to has already returned.
- **Bounded.** One short-lived daemon thread per timed-out copy, ten
  seconds at most. A control slower than that is outside what this
  covers, and the caveat already says the restore is not atomic.

**Evidence.** `tests/test_clipboard_policy.py`: a late answer owned by the
target is put back and recorded; a change the target does not own is left
alone and is what gets put back afterwards; nothing arriving records
nothing; and end to end, a fixture grid that answers `WM_COPY` 600 ms late
against a 200 ms timeout leaves the clipboard holding exactly what it held
before (`env: windows`). The fixture now opens the clipboard with its main
window, as an application does, so the owner names its process. Issue
#186; D70; D#182.

### D#189. A menu item: the posted pair first, the menu's keyboard route on request

**Context.** D#135 put the menu's keyboard route (`menu_keys`: select by
position, Return to the menu window) first for every `#32768` item, on
the strength of one target whose menus close on a posted click. From the
merge of that change, `tests/test_windows_menus.py` failed on CI in about
one run in three, on changes that could not reach it, and was the main
source of red runs for every session for a week (#145). The route passes
every local run. Instrumented in D#145, the two occurrences that followed
showed the menu already gone when the second rung ran and the handler
never having updated the label; why is still not known (#190).

**What was wrong with D#135 as a default.** It generalised a fact about
one target to all of them. An ordinary Win32 menu answers the posted pair
at an item's rectangle -- the fixture's does, and did, stably, for weeks.
A menu whose modal loop hit-tests the real pointer is the exception, and
an exception is what a profile is for (D35).

**Decision.**

- **The posted pair is the first rung again**, and `menu_keys` the second.
- **The keyboard route goes first when asked:** per call with
  `menu_by_keyboard: true`, or declared for the target with
  `menus_by_keyboard: true` in its profile.
- **The one-way failure says how to get out of it.** When the posted pair
  has closed a menu that needed the keyboard, `menu_keys` finds no menu;
  its decline reason now says that this is what that looks like, and to
  open the menu again and ask for the keyboard route.
- **The route's CI failures are recorded, not blocking.** One fixture test
  still drives the keyboard route. When it fails it raises a pytest
  warning carrying the full explanation and xfails: a warning reaches the
  log under `-q` where an xfail reason does not, so the evidence D45 says
  to keep is kept, without every other session's run going red for a
  route that is no longer the default. Tracked in #190.

**What this costs.** On the target that motivated D#135, a first click on
a menu item now closes the menu and fails, once, with the message telling
the caller what to set. After that the profile carries it.

**Evidence.** `tests/test_windows_menus.py`: an ordinary menu is chosen by
the posted pair with `routes_attempted == ["posted"]`; the order of the
two routes flips with `menu_by_keyboard`; the profile key is read and a
non-boolean refused; a failed choice reports `posted` as its first route;
the keyboard-route collector test as described. The phase tests from
D#145 are unchanged. Issue #189; #145; #190; D#135; D#145; D35; D45.

### D#190. A menu that has not answered is not a menu that has gone

**Context.** `menu_keys` failed on CI in about one run in three while
D#135 made it the first rung, and passes every local run. D#189 moved it
back to second and put the one fixture test that still drives it behind a
warning-and-xfail, so the evidence keeps arriving without every session's
run going red (#190). The cause is still not established, and this record
is about what the two occurrences on file *do* settle, and about the two
places the evidence was contradicting itself.

**What the occurrences rule out.** Both showed the menu gone by the time
the second rung ran, and the label never updated. That kills one of the
two live hypotheses on its own: if `menu_keys` had merely *mis-read* a
slow menu as an absent one, the posted pair running immediately afterwards
would have found the menu still up and chosen the item, because the posted
pair is what works on this fixture's menus. It did not -- it returned
without delivering, which on a `#32768` element means the rectangle could
not be converted through the host window. So in those two runs the menu
really had ended, with nothing chosen. What remains open is whether Return
ended it and chose nothing, or whether something else ended it before
Return could.

**What was wrong with the evidence itself.**

- **A read could not tell silence from an answer.** Every read of a menu
  goes out as `SendMessageTimeout` with a 500 ms bound, and
  `popup_menu_item_state` mapped both "the window did not answer" and "the
  window says there is no such item" onto `None`. `menu_choose` reported
  that as "the menu is no longer showing", with advice to reopen the menu
  and ask for the keyboard route -- which is the one instruction a caller
  cannot act on if the menu never closed. On a loaded runner a late answer
  is exactly what you expect, so the diagnosis most likely to be wrong was
  also the one load makes most likely to be given.
- **A failed action claimed delivery its own fields denied.** The
  actuator's message read "every tier delivered but none produced the
  expected result" whatever happened, including in the two #190
  occurrences, whose `declined` said in the next field along that a rung
  had returned without delivering. An occurrence that misdescribes itself
  is worse than no occurrence: it is read first and believed.

**Decision.**

- **The read has three outcomes, not two.** `None` is silence and says
  nothing about whether a menu is there; `{"present": False}` is the
  window answering that there is not. Silence is waited out against its
  own bound, `MENU_ANSWER_S` -- a bound on "has the menu spoken yet",
  which is a different question from the phases' "has the menu done what
  was asked" and deserves its own clock.
- **Silence from a window that is not up is settled without waiting.**
  `IsWindow`/`IsWindowVisible` send no message and cannot time out, so
  they answer what the read could not. A menu closed by the posted pair
  still reports D#189's way out, at once; only a window that is up and
  quiet pays the wait.
- **What the phases could not acknowledge, they now count.** An
  unacknowledged `MN_SELECTITEM` and an unanswered read are tallied and
  ride in every message the route raises. A highlight phase that expired
  with reads outstanding failed for a different reason than one that
  expired with the menu answering promptly, and until now they read the
  same.
- **The gap between the phases is closed.** The menu is confirmed still
  showing immediately before Return is posted. Between the item reading as
  highlighted and the keystroke going out, the menu could end and the
  route would blame a Return it had not sent yet. That is named now, and
  it is one of the two shapes the open cause can take.
- **A failure says how many routes delivered, and which.** None delivering
  reads as "no route delivered, so nothing could have produced the
  expected result"; some delivering names them.

**What this does not claim.** That the flake is fixed. Nothing here has
been reproduced on a Linux box, and the mechanism that ends the menu with
nothing chosen is still unidentified. What changed is that the next
occurrence can say which of the two remaining shapes it is -- the menu
ending before Return, or Return going out and the menu ending without the
command -- instead of arriving as a sentence that contradicts the fields
below it. #190 stays open until an occurrence does that, or until the
route has been quiet long enough to call it load.

**Evidence.** `tests/test_windows_menus.py`: a menu that answers late is
waited for rather than called gone; one that never answers is named as
unanswered and nothing is sent to it; one that answers that it has gone
still says how to ask for the keyboard route, on the first read; silence
from a window that is not up is settled with no wait at all; a menu that
ends between the highlight and Return is named; unacknowledged selects and
unanswered reads appear in what is raised; the three outcomes of the read
and the two of the select are pinned at the `winapi` seam. The D#145 phase
tests are unchanged and still pass. `tests/test_actuate.py`: a failure
does not claim delivery its own declines contradict, and one that follows
a route that did deliver names it. Issue #190; #189; #145; D#189; D#145;
D#135; D45; D10.

### D#29. Closed on fixture coverage: the silent-control branch is proven, not observed live

**Context.** D76's Gate 5 ran all six validation gates against a real
Profile L1 target and found every control on it answered --
`unresponsive_count` was 0 and nothing reported `<no answer>`. So the one
branch the gate exists to exercise -- a control that never answers at all,
as against one that answers with nothing -- had never run against a real
target. Issue #29 opened to track closing that gap, and named its own
legitimate way out in advance: observe it opportunistically on a real
target, "or decide the fixture coverage is sufficient and close this
saying so, which is a legitimate answer and better than leaving it open
forever as a reproach."

**Why this session takes that way out.** Manufacturing a genuinely wedged
control needs a real Win32 application caught at the moment it is hung,
which cannot be scheduled -- and `env: windows` / `real-target` mean it
can only be attempted from a Windows box with an operator session, which
this session does not have (`docs/win-host` is offline). Re-parking the
issue changes nothing about those odds: a future session with the same
constraint would face the identical deadlock, on an outcome the issue text
already treats as acceptable.

**What already stands as proof of the code path.**
`tests/test_windows_unresponsive.py` exercises a fixture window whose
owning thread never calls `GetMessage`, so a cross-process `WM_GETTEXT`
against it hits its own timeout rather than the target answering empty --
a fixture built specifically because, per its own docstring, "every
control on every real target measured so far... answers." Three tests
cover the full path this issue is about: `read_window_text` returns `None`
rather than `""` for the silent control; `build_tree` marks the node
`responsive is False` while still carrying `text == ""`; and the CLI
prints `<no answer>` rather than a blank line. `test_the_window_is_
otherwise_entirely_normal` confirms the fixture is a faithful stand-in --
class name and rect answer normally from the kernel, and only the
message-based read times out, which is exactly the shape of a hung real
target.

**Decision.** Close #29 on fixture coverage. The code path, the tree flag
and the CLI rendering are asserted end to end against a deliberately
silent target built to reproduce the one condition no live target has
shown yet. What remains unconfirmed is only whether `read`'s timeout is
tuned correctly for a real application under real load -- not whether the
branch exists, is reachable, or is reported correctly when reached. That
narrower question is left open for whoever next has operator access to a
Windows target and happens to catch one wedged.

**What this does not claim.** That a real control has ever failed to
answer, or that the timeout value is validated against real load. D76's
Gate 5 finding stands as written: the `responsive=False` path has run in
the fixture and nowhere else. This decision closes the issue on the
fixture being sufficient evidence that the path works, not on the live
observation having happened.

**Evidence.** `tests/test_windows_unresponsive.py`; `tests/conftest.py`
(`silent_target`); D76 (Gate 5). Issue #29.

### D#196. `modals` reports each text control on its own, capped by default

**The field report.** Every `modals` call on a VendorApp error dumped the
Java stack trace held in the dialog's memo -- three to four thousand
tokens, paid about eight times -- when only the message line was needed.

**Decision.** Each readable text control in a dialog is reported on its
own (`controls`: class, length, text), in reading order, and by default
cut to its first 600 characters with `cut` saying how many were left out.
A one-line message and a memo full of trace are then told apart, and the
memo does not cost the message beside it. The joined `text` stays, built
from the capped pieces so the whole is bounded too; `truncated_chars` and
a note say when anything was cut, and `full_text: true` returns
everything. A "Message:" parser would have been target knowledge; the
cap is not. The helpers moved to `tools/dialogtext.py` because
`status.py` sat at the tool-module limit (D60).

**Evidence.** `tests/test_dialog_text.py`: three controls reported, the
long one cut with its count, `full_text` whole, the joined text bounded
(`env: any`, the tree stood in for). Issue #196; D73; D11.

### D#197. A batch's captures come back as images

**The field report.** A `capture` step in a batch returned width and
height and no pixels, so every capture had to be re-issued standalone --
the round trip a batch exists to remove.

**Decision.** The step line still carries no pixels (a JSON line cannot).
The image rides beside the batch result and the protocol layer returns
it as an image block before the JSON, exactly as a standalone `capture`
does; the step line says `image: attached`. At most four images ride in
one batch result, and a fifth capture's line says it was dropped and why.
The base64 never enters the text: unreadable and enormous there, as D73
measured.

**Evidence.** `tests/test_stepper.py`: images collected beside the steps,
none in a step line, the cap and its note (`env: any`).
`tests/test_mcp_server.py`: image blocks before the text, the base64
absent from the text and the structured result. Issue #197; D#75; D73.

### D#198. An `index=` locator that picks a different control than before says so

**The field report.** Fields on a form located by `index=N` shifted as
fields filled and emptied, and a value landed in the wrong field twice.

**What was measured.** `index` picks from the window tree's sibling
order, which on Windows is z-order, and a VCL form reorders siblings as
controls take focus. So the same locator names a different control after
the previous field was edited -- exactly the sequence a form fill is.

**Decision.** Reordering the index would change every existing locator's
meaning, so the order stays. Instead the session remembers what each
`index=` locator picked, and when the same locator picks a different
control while the earlier one is still among the matches, the next
result -- `find` or the actuation -- carries `index_drift` naming both
handles and the stable anchors: `text=` where the field has one, or
`region=` copied from an earlier `find`. Said once per drift. A control
that went away is not drift. The locator argument's own description now
says the same. The bookkeeping lives in `tools/drift.py`, off the core,
which sat at the tool-module limit (D60).

**Evidence.** `tests/test_index_drift.py`: a reordered sibling list is
reported once with both handles; a control that went away is not drift;
a locator without `index` never is (`env: any`, trees built by hand).
Issue #198; D33.
### D#194. A window that appeared is what the action did, and `changed` sees it

**The field report.** A click on Ok raised a validation Error dialog. The
result was `ok: false`, `postcondition_failed`, against `expect:
{changed: true}` -- while `disturbances` carried `window_appeared: Error`.
The click very much did something; the top line said it had not.

**What was wrong.** `changed` compared the main window's surface-shape
digest, and only that. A dialog is a separate top-level window, so the
one effect the action produced was not a change to the thing being
compared. And the sentence a failed action leads with said nothing about
the dialog either; the diagnosis was in the detail, one layer down, under
a verdict that read "try again".

**Decision, in two parts.**

- **`changed` also holds when the target's set of top-level windows
  changes or it becomes held.** The backend snapshot the actuator already
  takes carries both; the baseline is the digest, the windows and the
  block state together, and any of the three moving is the surface
  changing. Where a dialog appears in answer to a click, `changed` now
  verifies it, as its name always promised.
- **When a named expectation did not hold and a window appeared or the
  target became held, the outcome says so.** `outcome:
  delivered_raised_window`, `raised: [captions]`, and the error message
  leads with "delivered, and a window appeared (Error); the named
  expectation did not hold. Read it with modals and deal with it before
  retrying." `ok` stays false: a disturbance is information, never a
  verdict (D28), and a named expectation that did not hold did not hold.
  The retry the flat sentence invited is the thing this stops.

**Evidence.** `tests/test_outcomes.py`: the raised-window outcome, and
`changed` holding on a window appearing and on the target becoming held,
with the desktop stood in for (`env: any`).
`tests/test_changed_postcondition.py`: a fixture modal raised during the
verify window makes `{changed: true}` hold, with `window_appeared` in the
disturbances (`env: windows`). Issue #194; D77; D28.

### D#195. A delivered click that changed nothing is its own outcome, and the second one says so

**The field report.** Seven Create Plan attempts against a VCL combo
dropdown and an owner-drawn grid cell, every one `delivered_to` the right
window with `postcondition_failed`, and a wrong hand-off to a pointer tool
at the end. The tool knew: a route delivered, nothing changed, and the
focus block's note explained why a VCL control ignores a posted click.
The verdict did not say it.

**Decision.** When a route delivered, the named expectation did not hold,
and *nothing* changed around the action -- no window, no block, no
foreground move -- the result carries `outcome: delivered_no_effect` and
leads with the routes still inside the contract, in the order to try
them: the keyboard for a combo (`send_keys ["f4"]`), the in-place editor
for a grid cell (`f2` or a double-click, then `set_value` on the editor
window it shows), the menu's keyboard route for a popup item, and then a
step for a person. It never names a pointer tool (D#133).

**The second time is said to be the second.** The ledger already records
every actuation's outcome per session (D45). The report counts the failed
actuations on the same locator in this session, this one included, and
from the second onward leads with "this is delivery #N to this control
with no effect; the same route will not act on a retry." That is the
sentence that would have stopped attempt three.

**The function keys are named keys.** `f1`..`f12` join `send_keys` on
both backends, because a hint that names `f4` must be followable.

**Evidence.** `tests/test_outcomes.py`: the outcome and its hint; the
count on the second inert delivery; a route that never delivered is not
called inert; a miss with other changes keeps the plain suffix; a success
carries no outcome; the function keys resolve (`env: any`). Issue #195;
D#133; D64; D45.

### D#199. A grid cell's editor is a question the hint asks, not a fact it states

**The field report.** A Change Number cell in an owner-drawn grid took
neither a posted key nor a real keystroke -- the latter swallowed by the
application's own barcode-scan handler -- and the value went in through
the application's REST interface instead.

**What was wrong here.** D#195, written a day earlier, had the failed
click name the routes still inside the contract, and one of them read:
"an editable grid cell opens its editor on f2 or a double-click
(count=2), and then takes set_value on the editor window it shows". Two
promises in one clause -- that the editor exists, and that it is a
window -- and neither had been measured on anything. A hint that asserts
is followed; the operator above followed it into the retries D#195 exists
to stop.

**The measurement this decision does not have.** The question is one
call: post `f2` or a double-click on the cell, `find` again, and see
whether a window appeared that was not there before. It has to be taken
on the grid in question -- whether a cell edits through a window is a
property of that grid, not of grids -- and nothing here can substitute
for it. It was not taken: this was written on Linux, and the target is a
live line-of-business application in the maintainer's own session. Issue
#199 carries the procedure for whoever is in front of it.

**Decision: the hint asks instead.** It now names the check (`f2` or a
double-click, then `find` again -- an edit under the grid, *or* a popup,
which needs `all_windows=true`) and both answers. A window appeared: an
ordinary control, `set_value` reaches it, nothing new is needed. Nothing
appeared: the cell is painted rather than a window, `capture` shows it,
there is nothing for `set_value` to address, and the value goes in
through the application's own interface or a person -- said in those
words, with "do not keep trying keys", because the answer that ends an
attempt has to end it.

**Why not build the primitive and find out.** Because the two answers
need different code and only one of them needs any: the window case is
`set_value` on a control that already resolves. An `edit_cell` written
before the measurement would be a wrapper around the branch that needs no
wrapper, and a lie in the branch that has no window -- exactly the
promise this issue was opened to stop. The second answer is not a gap to
close later either: no window means no locator, and D53 says a target the
strategy cannot fit is reported as such rather than worked around. So the
out-of-band route is named in the tool's own words rather than left for
the caller to think of after the seventh key.

**Evidence.** `tests/test_outcomes.py::test_the_grid_cell_editor_is_a_check_not_a_promise`:
the old promise is gone, the check is named, both answers are present,
and the second names `capture` and the application's own interface
(`env: any`, the result built by hand). README's "What it does not do"
carries the limit. Issue #199; D#195; D53; D33.

### D#203. `at` is pixels from the window's top-left, on a framed window too

**The field report.** `at` read as screen-absolute on the main window and
client-relative on dialogs, and a point measured on `capture(locator=...)`
-- documented as needing no arithmetic -- landed low on a dialog. Several
misfires.

**What was measured.** `at` has one meaning: pixels from the element's
top-left as `find` reports it, which is also pixel (x, y) of a capture of
that element. The backend handed it to the click as a *client* point. A
child control's client area is its whole rectangle, so the two agree
there; a top-level window's client area starts below its title bar and
inside its border, so on a dialog the click landed a frame's height low.
The main window sits at the screen origin, which is what made its `at`
look screen-absolute.

**Decision.** The backend converts `at` from window-rect-relative to
client-relative (the client origin's offset inside the window rectangle)
before posting, so the documented frame is true on every window. Nothing
changes for a child control, where the offset is zero.

**Evidence.** `tests/test_windows_at_frame.py`: the fixture shell's client
area starts inside its rectangle and the conversion subtracts exactly
that; a child control has no offset; the grid's row 1 aimed *through the
shell* with an `at` taken from the shell's own rectangle lands on the grid
and is verified (`env: windows`). Issue #203; D66; D73.

### D#204. `attach` names the tools the tier excludes

**Context.** `grid_seek` needs `full`; a session opened at `interactive`
found out on first use, one round trip later.

**Decision.** The attach summary carries `not_at_this_tier`, from the same
table the refusal reads, when the tier excludes anything. Issue #204; D9.

### D#205. `wait_idle` with no indicator waits for the surface to hold still, and says so

**Context.** `wait_idle` refused when the profile named no
`busy_indicator`, and a sensible default was asked for.

**Decision.** With no indicator, it waits for the surface-shape digest to
hold still for `settle_s` (default 1 s) and reports `waited_on: surface`
with a note that this is weaker evidence than an indicator clearing -- a
grid filling rows without changing shape looks settled -- and that a
`busy_indicator` should be declared when one is known. A timeout says the
surface kept changing. The `batch` description now says a step's `args`
are the standalone tool's own parameters by name.

**Evidence.** `tests/test_feedback_2026_09_22b.py`: settles and says so;
never settles and times out honestly (`env: any`, the digest stood in
for). `tests/test_field_feedback_6.py`: the old refusal test now proves
the fallback against the fixture. Issue #205; D69; D77.

### D#206. A `text=` locator with surrounding whitespace is told the match is exact

**Decision.** Matching stays exact, whitespace included: trimming would
silently change which control a locator names (D33). When a `text=`
pattern with leading or trailing whitespace matches nothing, the error
says the match is exact including that whitespace and shows the `/regex/`
form. Issue #206; D33.

### D#207. A profile can put the insert route first; a typing miss points at `set_value`

**Context.** Masked date edits and combo edits swallowed `type_text` and
`send_keys`; `set_value`'s insert route worked, discovered per field.

**Decision.** `set_value` already falls through from typing to the insert
when the read-back shows the typed value arrived short. The profile key
`insert_first` (class patterns, declared, D35) puts the insert route first
for a class known to swallow typing, so the typed attempt and its
read-back are not paid. `type_text` has no fallback of its own, and a miss
now carries a hint saying so and naming `set_value` and the key. Typing
stays the default elsewhere: it is the toolkit's own keyboard path, which
is what a bound field commits on (D70).

**Evidence.** `tests/test_feedback_2026_09_22b.py`: the key is read and
matched, a non-list refused, the ladder order flips (`env: windows` for
the ladder), the hint text. Issue #207; D70; D35.

### D#208. The first-click trap is named; a menu form's refusal names the menu routes

**Context.** A first click on a fresh VCL grid is consumed by focus, and
an automatic repeat was asked for. `require_active` can never be satisfied
on a popup menu form, and a `foreground` that makes one active was asked
for.

**Decision.** No automatic repeat: a repeated click is a retry, which
takes the evidence with it (D45), and on a control that took the first
click it acts twice. The `delivered_no_effect` hint (D#195) gains one
sentence: on a VCL grid the first click may only give it the focus, and a
second explicit click on the same cell is the expected next step, not a
retry. No activation either (D64): the `require_active` refusal now says
that on a popup menu window it can never clear and names the menu's own
routes, `menu_by_keyboard` and `send_keys`. Issue #208; D45; D64; D#189.

### D#210. `describe` at scale: bounded and honest, and now a way back in

**Context.** Gate 3 (#28) asks whether `describe` holds at the ~1,100
windows of a fully loaded target; it had run on 108. The real-target run
still needs an operator session. What could be done without one was a
synthetic measurement: trees of 108 to 20,000 windows shaped like a
business application (a shell of forms of panels of controls), through the
same summarizer.

**What was measured.**

| windows | summary | time |
|---|---|---|
| 110 | ~20 tokens | < 1 ms |
| 1,102 | ~40 tokens | < 1 ms |
| 5,001 | ~150 tokens | < 1 ms |
| 20,002 | ~560 tokens | < 10 ms |

Independent of how many controls carry captions. The summary stays inside
the budget at every size and always says what it hid: `[8 x Form -- 1093
descendants not shown]`, `truncated: true`, `elided_by_collapsing`. The
first two of the gate's three questions hold on this shape.

**Where it stops being useful, which is the third question.**

- Same-class siblings collapse into one group and everything under its
  members is hidden: 1,093 of 1,102 windows in the 1,100 case. That is the
  right first answer -- an outline of the views -- and a dead end, because
  `describe` could not be rooted at one of them. `find within=(...)` lists
  matches; it does not summarize a view.
- `suggested_locators` was cut to 30 with nothing said (153 were offered at
  20,000): a cap that says nothing reads as "that was all of them" (D11).

**Decision.**

- **`describe` takes `within`**: a window locator that must match exactly
  one, and the summary is rooted there. Zero or several matches is an
  error naming the count, never a guess (D33).
- **A result that collapsed anything says how to get back in**
  (`expand_hint`), pointing at `within` and at the locators already in the
  result.
- **The locator cap is said**: `suggested_locators_omitted` counts what
  was left out.

**What this does not settle.** That a real target's tree has this shape.
The synthetic tree puts the views directly under the shell with one class;
a real one may nest them, or mix classes so that fewer groups collapse and
the node budget, not the collapse, does the cutting. #28 stays open for
that run.

**Evidence.** `tests/test_describe_scale.py`: the summary stays inside a
4,000-character budget and says what it hid at 108, 1,100, 5,000 and
20,000 windows, at 10% and 100% captioned; a collapsed result carries the
hint and the view's locator; `within` roots the summary at one view and
refuses zero or several; the locator cap is counted; a small tree carries
neither note (`env: any`). Issue #210; #28; D11; D33; D76.

### D#215. On a Wayland session, X-sourced desktop state is refused, not answered

**Context.** linux-host-a, the box the MCP is actually used on, runs Ubuntu 26.04
with GNOME Shell 50 in a **Wayland** session. The Linux backend reads the
window tree through AT-SPI and everything about the *desktop* (foreground,
pointer, modality, visibility, liveness, capture, real input) through X.
On a Wayland session the X server is rootless XWayland, which knows only
X clients. Nothing checked which kind of session it was talking to.

**What was measured** (2026-10-09, linux-host-a's live session, read-only):

| Read | Answer | Truth |
|---|---|---|
| X `_NET_CLIENT_LIST` | 1 client (Conky) | AT-SPI: 13 applications |
| `list-targets` (AT-SPI) | gnome-shell, Chrome, 1Password, Tabby, ... | right |
| `display.foreground_pid()` | gnome-shell | Chrome's frame was `STATE_ACTIVE` |
| `display.cursor()` | `(3081, 634)` | XWayland's last pointer, stale over Wayland surfaces |
| `snapshot(<chrome>)` | `windows={}, foreground=0, alive=False` | a live target |
| `top_level_state(<chrome>)` | `[]` | modality unknown, not absent |
| `capture_window(<chrome frame>)` | "a control is an accessible ..." | a frame with no xid, because Wayland |

Each of those is a confident answer about the wrong desktop. The one that
matters most is the foreground: the interference watch and the
live-actuation guard (D#111) would never see the operator's front change.

**Decision.** `backends/linux/session_type.py` answers *x11* or *wayland*
per claimant: the operator's desktop from `XDG_SESSION_TYPE` (which wins,
because it names the session), else `WAYLAND_DISPLAY`, else **the X server
itself** -- Xwayland advertises the `XWAYLAND` extension and a plain X
server does not. The last is not a nicety: a server launched outside the
graphical session inherits `DISPLAY=:0` and neither variable (measured on
linux-host-a, in the launcher this MCP actually runs under), and without it the
guard was off exactly where it was needed. A hidden desktop answers from
what it registered, so an Xvfb hidden desktop on a Wayland host stays X11.
On a Wayland operator desktop:

- **`display._display()` refuses** with `X11Only` (an
  `UnsupportedPlatform`, so a tool returns `denied_by_environment`, #213).
  It is the one choke point every X call passes. The degrade-to-default
  wrappers in `display.py` let it through (`_x_errors_ignored`), because
  "not hidden", "gone", "not modal" and `(0, 0)` would each be the same
  confident wrong answer the refusal exists to stop. Verifying on linux-host-a
  found `cursor()` swallowing it before this was added.
- **Frame correlation skips**: a native Wayland window has no xid, and
  enumeration must keep working.
- **Both watches refuse at construction**, not inside their poll threads.
- **`snapshot` lets the refusal through** rather than calling the target
  gone, and **the actuator refuses an action it cannot observe**
  beforehand. It used to swallow every observer failure so instrumentation
  could not stop an action; acting unwatched on the operator's desktop is
  the failure this project exists to prevent (D53). A refusal *after* an
  action leaves the action's result standing.
- **`blocked` reads `null`**, not `[]`. Unknown is not "not blocked".

- **The questions reading asks still answer.** `list_targets` asks a
  class name of every window (empty on Wayland -- there is no `WM_CLASS`),
  `attach` asks whether the main window is minimized (False: "no hint",
  until W4 measures it), and a `read` that came back empty says it could
  not be checked for rendered content instead of reading the missing
  capture as "paints nothing" (D66).

**What it costs.** On a Wayland desktop nothing can be actuated, and
`capture`, `restore`, the interference watch, macro replay (it arms one)
and the minimized strategy all refuse. `await_human` still waits, but its
notice cannot be shown, and it says `notice_shown: false`. Reading works
through the MCP tools: `list_targets`, `attach`, `describe`, `find`,
`read`. That is the D53 trade -- a refusal a caller can
read instead of an action that might take the operator's desktop with
nobody told. Each refusal narrows as its Wayland mechanism is measured
(W1-W11 in `docs/superpowers/plans/2026-10-09-wayland-support.md`).

**Found on the way, fixed here.** `describe` and `attach` failed on
*every* Linux desktop, X11 too: they ask `winapi.is_hung` and
`winapi.is_minimized`, and the Linux shim refused both. `is_minimized`
now reads the frame's `_NET_WM_STATE_HIDDEN` on X11. `is_hung` answers
`False`, as `top_level_state` already did: Linux has no
`IsHungAppWindow`, and the read deadline catches a frozen application
(D#9).

**Found on the way, not fixed here.** GNOME 50 removed `gnome-shell
--x11`, so `HiddenDesktop` (Xvfb + `gnome-shell --x11`, D75) cannot start
on linux-host-a: `test_linux_hidden_desktop.py` errors there on `main`, with or
without Wayland. linux-host-b has no gnome-shell and skips it, and CI is
Windows-only, so nothing caught it. A nested `gnome-shell --headless
--wayland` was measured starting on a private bus with Mutter's
RemoteDesktop and ScreenCast interfaces (W0 / Phase 2a of the plan).

**Evidence.** `tests/test_wayland_session_type.py` and
`tests/test_wayland_guard.py` (`env: any` -- the session type and the X
connection are injected, so they run on Windows too), including the MCP
`list_targets` under Wayland and the silent-environment probe both ways;
`tests/test_tool_contracts.py` for `blocked` and `is_hung`. Live on linux-host-a,
in a launcher environment with only `DISPLAY` set: the session reads as
Wayland, foreground and pointer refuse, and over the MCP tools
`list_targets`, `attach` and `describe` answer (`blocked: null`) while
`surfaces` returns `denied_by_environment`. On linux-host-a,
`tests/test_linux_*.py` fails the identical set on `main` and on this
change with the display variables unset (the X11 path), every failure the
missing `gnome-shell --x11`. Issue #215; #213; D9; D53; D#111; D75.

### D#217. The hidden desktop is a headless gnome-shell's Xwayland, and on it an X client cannot take focus

**Context.** `HiddenDesktop` was an `Xvfb` with `gnome-shell --x11` on it
(D75), and seven measurement harnesses built the same stack by hand. GNOME
50 removed the X11 backend (`gnome-shell --x11` → "Unknown option"), so on
linux-host-a (Ubuntu 26.04, GNOME 50.1) the strategy could not start and the
harnesses all errored. linux-host-b has no gnome-shell and skipped them; CI is
Windows-only. Every failed `prepare` also left its `Xvfb` and private
`dbus-daemon` running: five of each had piled up on linux-host-a.

**What was measured** (linux-host-a, a headless `gnome-shell --headless --wayland
--virtual-monitor 1280x800` on a private bus, the GTK fixture as an X client
of the shell's own Xwayland; the operator's foreground read before and after
every run, unmoved):

| Question | Answer |
|---|---|
| Does the shell host an X client with EWMH? | Yes. The fixture is in `_NET_CLIENT_LIST`, `_NET_WM_PID` is right, `_NET_SUPPORTING_WM_CHECK` is set. |
| Iconify, `_NET_WM_STATE_HIDDEN`, capture by `XGetImage`, XTest | All work. XTest synced in ~5ms with no portal prompt. |
| Which display did it choose? | Its own log says ("Using public X11 display :2"). Watching `/tmp/.X11-unix` for a new socket missed it: a stale socket already held the name. |
| Is the nested accessibility bus private? | **Not by default.** With no `XDG_RUNTIME_DIR` (the launcher environment again, as in D#215) the activated bus fell back to `~/.cache/at-spi/bus`, which RustDesk also used, and the "nested" bus listed RustDesk. With a private runtime directory it lists only the shell's own helpers and the fixture. |
| Does an X client's `present()` un-iconify it? | **No.** Under `--x11` it did (L6). Mutter in Wayland mode refuses it: the window stays hidden, the foreground stays put. |
| Does a modal raised by a hidden X client get out? | **Yes**: the main window comes back on screen beside the modal, focus unmoved. This is now the escape the watch probe uses. |
| Does activating a hidden window restore it? | **No.** Under `--x11` activation was the only thing that restored a window, so restoring was focusing (D#14). Here it is refused outright: the window stays hidden for the whole 30s. |
| Does the owner lose `ACTIVE` when its modal comes up? | **No.** It did under `--x11` (D#12 recorded it as not a modality signal). Here it does not even move. |

**Decision.** `HiddenDesktop` runs a headless `gnome-shell --wayland` under
a private `XDG_RUNTIME_DIR` and a private session bus, and launches the
target as an X client of the shell's Xwayland -- never with the operator's
`WAYLAND_DISPLAY`, and with `GDK_BACKEND=x11` and `QT_QPA_PLATFORM=xcb`, so
no toolkit can open it on the operator's desktop. Everything the backend
reads about a window it still reads from X, so nothing above the shell
changed; the hidden desktop's own cookie is handed to the X connection
(`display._connect`) only for the moment it opens. A `prepare` that fails
part-way tears down what it started, and `teardown` waits for the private
bus's process group to empty before removing the runtime directory (a dying
gvfs recreated its mount point in it once). The measurement harnesses share
one recipe (`tests/linux_nested_shell.{sh,py}`).

**What it changes about earlier measurements.** D#12, D#14 and L6 were
measured against mutter in X11 mode. That mode is gone on GNOME 50, and the
answers differ in one direction: mutter in Wayland mode does not let an X
client take focus or come back from iconified on its own. The tests that
pinned the old answers now pin the new ones and say what changed
(`test_active_on_the_owner_is_not_a_modality_signal`,
`test_activation_neither_restores_nor_focuses_on_the_headless_shell`,
`test_a_target_that_presents_itself_stays_put_away`). For the strategy this
is more isolation, not less. For `restore` it means a request nothing
answers, so the result now says "none came back on screen" instead of "the
application re-showed its own forms". The tier-3 harness (D#11) can no longer
produce its positive control -- it focused a window by activation -- so it
skips and says why; D#11's conclusion does not depend on it.

**Found on the way, not this decision.** at-spi2-core 2.60 renamed the role
"push button" to "button" (two tests matched the old name and now accept
both; a profile written with `type=push button` would stop matching on such
a host). And GTK now hands out a password entry's text as bullets, not
cleartext, which contradicts D#34a's finding: the tests that pin the leak
fail on linux-host-a for that reason, not this one.

**Evidence.** `tests/test_hidden_desktop_lifecycle.py` (`env: any`: the
display parse, teardown on a failed `prepare`, the target environment, the
cookie hand-off); `tests/test_restore_result.py` (`env: any`);
`tests/test_linux_hidden_desktop.py` on linux-host-a, 6/6 including no process and
no runtime directory left behind; the converted harnesses on linux-host-a --
`watch` 5/5 (with #218's watch built as `attach` builds it), `slice3` 8/8,
`slice4` 8/8, `modality` 4/4 and `foreground` 8/8 with the re-measured
answers, `tier3` skipping on its control. `restore` measured its answer once
-- activation left the hidden window hidden and the foreground where it was
-- on a run where mutter had focused the window on map; it otherwise skips,
because its harness focuses by activation, which is what is now refused. No
nested shell, runtime directory or mount is left after any of them: the
harnesses and `teardown` both sweep every process carrying the desktop's
runtime directory (the headless shell does not always die on SIGTERM). Issue #217; #218;
D75; D#8; D#11; D#12; D#14; D#215.

### D#221. On a Wayland desktop, window state comes from AT-SPI, and tier-1 actions work

**Context.** D#215 refused every X-sourced fact on a Wayland operator
desktop. That was correct, because X answered about the wrong desktop, but
it also refused every action: the actuator will not act on a desktop it
cannot observe. linux-host-a, the box the MCP is used on, runs GNOME 50 on
Wayland, so ghostdriver could read the operator's applications but not
drive them.

**How it was measured.** On linux-host-a's own session, with the operator's
consent and the desktop handed over. A nested headless shell could not
answer this: injected input there gave focus once and never moved it again,
neither by the switcher nor by closing the focused window. On the real
session, two GTK fixtures were driven, one a native Wayland client and one
an XWayland client. Focus was moved with mutter's RemoteDesktop keyboard,
so the compositor saw real input. Nothing was typed, and Super+H went only
to a fixture. `tests/linux_wayland_live_probe.py` is that run;
`tests/test_linux_wayland_live.py` gates it behind
`GHOSTDRIVER_LIVE_WAYLAND=1` and pins what it found.

| | Measured |
|---|---|
| W1, focus | After each of four Alt+Tab switches exactly one fixture frame held `STATE_ACTIVE`, alternating, for both kinds of client. A `window:deactivate`/`activate` pair arrived at the switch. For the X client, `_NET_ACTIVE_WINDOW` agreed; for the Wayland one it named nothing. `gnome-shell` (the switcher) and `mutter-x11-frames` also go active, and are skipped. |
| W2, modality | A modal is a frame with `STATE_MODAL`. It does not take focus, and carries no relation to its owner. |
| W3, position | Frame extents are `0,0,w,h`: relative to the window, never the display. |
| W4, minimized | A minimized native-Wayland GTK4 frame keeps `SHOWING` and `VISIBLE` and gains no `ICONIFIED`. Only focus leaving it shows anything happened. |
| Acting | Through the MCP tools at the `interactive` tier, with the XWayland fixture at the front: `click` on the Wayland fixture's toolbar button and `set_value` on its bound entry both landed at tier 1 (the fixture logged them), focus did not move, and no disturbance was reported. The actuator's snapshot of the target was alive, with another application's front. |

**Decision.** On a Wayland operator desktop, `snapshot`, `top_level_state`
and `blocking_ancestor` read AT-SPI frames (`tree.frames`, which lists a
process's frames without walking their trees, and `tree.active_frame`):
- **Foreground** is the target's frame handle when it holds the front,
  and the front application's pid negated otherwise. That value is stable
  and never one of the target's handles, so a move between two other
  applications is still a change, but never reads as the target taking
  the front.
- **A modal** is attributed to the application's first non-modal frame,
  so the block is reported rather than dropped. `blocking_ancestor` holds
  every control of the application except those in the modal itself.
  Wayland does not say which window a modal holds, and the safe direction
  is the X11 path's own fallback.
- **`visible`** is AT-SPI's `SHOWING`. It cannot tell a minimized window
  from a shown one (W4), which is why `restore`, the minimized strategy
  and `is_minimized` stay refused or answer "no hint" there.

Still refused on Wayland, because no Wayland signal for them has been
measured:
- capture;
- the pointer half of the interference watch, and with it live actuation
  (W5, W11);
- the operator notice (W10);
- macro replay, which arms a watch.

**Found on the way, fixed here.** `click` and `set_value` failed on *every*
Linux desktop. The tool layer aims an actuation through
`winapi.client_centre`/`client_to_screen` before it acts (the denied-region
check, D72), and the Linux shim refused both. A tier-1 action needs no
point. The aim only has to agree with the element rects and denied
regions, and those are AT-SPI extents, so that is the space these answer
in (window-relative on Wayland, and for GTK4 on X11, D#40d).

**Evidence.** `tests/test_wayland_atspi_state.py` (`env: any`, against
fakes): top-level state from frames, the modal attributed and reported,
foreground for the target and for another application, no frames reading
as gone, `blocking_ancestor` inside and outside the modal, and the aim.
`tests/test_linux_wayland_live.py` on linux-host-a: 10/10 in three runs, then
11/11 once the actuator-observation check was added. Issue #221;
D#215; D#217; D72; D#40d; D#12.
### D#219. GTK now masks password text over AT-SPI; withholding by class stays

**Context.** D#34a measured, on GTK 4.14.5, that AT-SPI hands out both kinds
of hidden field in cleartext, and that a `Gtk.Entry` with visibility off is
indistinguishable from a plain one. D#34b built the Linux read policy on
that: an editable entry's value is withheld by class. On linux-host-a (Ubuntu
26.04) the four tests pinning the leak failed: the fields came back masked.

**What was measured** (linux-host-a; the fixture under each GDK backend on a nested
headless shell, plus a GTK 3 entry):

| Toolkit | Hidden `Gtk.Entry` | `Gtk.PasswordEntry` | Plain entry |
|---|---|---|---|
| GTK 4.14.5 (D#34a) | role `text`, **cleartext** | role `password text`, **cleartext** | text |
| GTK 4.22.4, X11 backend | role `text`, `•••••••` | role `password text`, `•••••••` | text |
| GTK 4.22.4, Wayland backend | role `text`, `●●●●●●●` | role `password text`, `●●●●●●●` | text |
| GTK 3.24.52 | role **`password text`**, masked | -- | text |

These are the backend's invisible character, one per secret character, so
the length still leaks. States, interfaces and attributes (`toolkit=GTK`)
are identical across the GTK 4 entries, as before.

**Decision: the policy stands.** Withholding an editable entry's value by
class (D#34b) is still needed on GTK 4. A hidden `Gtk.Entry` is still
told apart from a plain one only by what it hands out, and a target may run
a GTK 4 that hands out cleartext. Narrowing the policy is possible and
recorded here, not taken: it is the operator's trade between safety and
form-filling verification, not a measurement's.
- **Read, then classify the answer.** Treat a value made of one repeated
  mask character as protected. This is safe only where the toolkit masks,
  so it would need the target's GTK version. On GTK 4 that is readable
  from the loaded library's file name (`libgtk-4.so.1.2200.4` is 4.22.4);
  the release that started masking is not yet pinned.
- **Trust the GTK 3 role.** GTK 3 marks a hidden entry `password text`, so
  for GTK 3 targets the role alone would be enough.

The tests now pin either measured answer (`tests/linux_probe_support.
leaked_or_masked`), and fail on anything else, which would be an
unmeasured change. The driver's own promise -- it never fetches an editable
entry's value -- is unchanged and still asserted.

**Evidence.** `tests/test_password_mask.py` (`env: any`);
`tests/test_linux_reading.py`, `test_linux_protection.py` and
`test_linux_atspi.py` on linux-host-a, passing with the masked answer. Issue #219;
D#34a; D#34b; D37; D38; D62.

**Confirmed by the operator (2026-10-09):** keep withholding by class; the
narrowing options above stay unused. `set_value` already verifies by value
without disclosure (D#34b's `confirms_value`), so there is little to gain.

### D#225. On Wayland the interference watch watches focus, and says it cannot watch the pointer

**Context.** The interference watch asks two questions while a macro replay
or a workflow run is in progress: did the target take the foreground, and
did the pointer move. On a Wayland desktop it refused at construction,
because both answers came from X (D#215). That refused macro replay and the
workflow runner outright, read-only macros included, even though every
step inside them works there since D#221.

**Decision.** The neutral watch takes an optional pointer sampler. On a
Wayland desktop, the Linux watch samples the foreground from AT-SPI's
`STATE_ACTIVE`, which W1 measured to track focus for native-Wayland and
XWayland clients alike. It polls every 0.25s rather than 0.05s, because
each sample walks every application's frames over D-Bus. It has no
pointer: Wayland gives no global pointer query, and W5 is unmeasured.

**What a result says about it.** A watch reports what it cannot see
(`unwatched`). A macro result and a workflow report carry it as
`interference_unwatched`, so an empty event list is never read as "the
pointer did not move" -- the same rule as `blocked: null` (D#215). Asked of
the watch itself, so the workflow runner stays free of imports (its
structure guard).

**What it does not change.** Live actuation (D#111) stays refused on
Wayland: its own guard reads the pointer before each keystroke. The
minimized watch stays refused: minimized state is unobservable there (W4).

**Evidence.** `tests/test_interference_without_pointer.py` (`env: any`):
the watch without a pointer, on its own thread, the Linux watch on Wayland
reading the front from AT-SPI, the result fields, and `macro_replay`
running and carrying the note. `tests/test_workflow.py`: the report says
it, and says nothing when the pointer was watched. On a nested headless
shell in Wayland mode, a native-Wayland fixture, through the tool layer: a
`find` then `click` macro replayed, 2/2 steps, with the note. Issue #225;
D#215; D#221; D#111.

### D#227. Every `describe` records how it fared, so Gate 3 is answered by ordinary use

**Context.** Gate 3 (#28) asks how `describe` holds on a fully loaded
target and has waited five weeks for a special run against one. Looking
for evidence that already existed: the operator's trace holds **97
successful `describe` calls** across 56 server runs (2026-09-03 to
2026-10-07), nearly all against the real client -- and for every one the
trace kept exactly one field, `blocked`. None of what the gate asks was
recorded, and `describe` itself never reported the denominator: how many
windows the tree it summarized held, or how much text it returned.

**What those calls do show.**

- Callers tune the budget themselves: `max_nodes` asked for ranged 10 to
  300 with a median of 80; the 200 default was used 3 times in 99. Depth
  ranged 1 to 14, median 5. 47 of 99 asked for every top-level window.
- Real latency: median 172 ms, 95th percentile 702 ms, maximum 3.6 s.
  That is enumeration, which the synthetic run (D#210) could not see: the
  summarizer itself takes under 10 ms at 20,000 windows.

**Decision.**

- `describe` reports **`windows_total`** (the windows in the trees it
  summarized, or in the subtree `within` names) and **`tree_chars`** (the
  size of the text it returned -- what the result costs a caller to hold).
- The trace keeps those with `nodes_shown`, `truncated`,
  `elided_by_collapsing`, `below_depth`, `windows_omitted_for_budget`,
  `windows_hidden`, `suggested_locators_omitted` and `within`. The tree
  text itself stays out of the trace, as before.
- **`ghostdriver trace --scale`** reads them back: one line per measured
  call, largest tree first, then what the largest was and how it came
  back. Calls traced before the numbers were kept are counted, never
  guessed at.

**Why this and not the special run.** The special run needs an operator
to load a client and hand it over, and it measures one moment. The
target is driven for real work most days; from here on every one of those
calls is a measurement, at whatever size the client happens to be, and
the gate is answered the first time a loaded client is described.

**Evidence.** `tests/test_describe_scale.py`: `windows_total` equals the
tree's size and `within` counts only the subtree; the trace summary keeps
the numbers and not the tree. `tests/test_trace.py`: the report lists
measured calls largest first, states the largest, and counts the
unmeasured. Run against the real logs today it says, correctly, that none
of 97 recorded its numbers. Issue #227; #28; D#210; D76; D11.

### D#28. Gate 3 on the real client: the tree is deep, not wide, and depth is what cut it

**Context.** Gate 3 (D76) passed on one loaded view of 108 windows and
left open how `describe` holds on a full-size instance. D#210 answered the
bounds on a synthetic tree of up to 20,000 windows; D#227 made every
`describe` record its numbers, so a real call would answer the rest.

**What was measured** (2026-10-12, read-only: attach, `describe`,
release). The Delphi/VCL client with one plan document open: 114 top-level
windows, 112 hidden, **282 windows** in all -- 2.6 times the first run,
about a quarter of the ~1,100 the gate imagined.

| call | windows | shown | chars | collapsed | below depth | ms |
|---|---|---|---|---|---|---|
| `all_windows`, defaults | 282 | 26 | 614 | 0 | 54 | 141 |
| `all_windows`, `max_nodes=80` | 282 | 26 | 614 | 0 | 54 | 125 |
| `within` the document form | 53 | 24 | 540 | 9 | 12 | 171 |

**The three questions.**

- *Inside the budget, and says so when it truncates?* Yes: 282 windows
  came back as about 150 tokens with `truncated: true`. The node budget
  was never reached (26 of 80 or 200), so `max_nodes` changed nothing.
- *Suggested locators usable?* Mostly: eight offered, none omitted, and a
  class-plus-index locator resolved to exactly one window. One captioned
  suggestion matched three windows sharing a caption, so it was ambiguous
  as offered (#229).
- *Where does it stop being useful?* At the default depth, on the first
  call: the whole document view sits below depth 5, so the default
  `describe` is an outline of the shell's chrome. The result said *that*
  54 windows lay below depth, not *where*, and `expand_hint` -- raised for
  collapsing only -- did not appear. Rooted at the document form, the view
  came back usable in 540 characters, but only to a caller who already
  knew to root there.

**The real tree is the other shape.** D#210's synthetic tree was wide and
shallow, so collapsing did the cutting (1,093 of 1,102). The real one is
deep and narrow: collapsing hid 0 of 282, depth hid 54. So the limit that
binds is not a window count at all. It is depth, it bit at 282, and it
would bite the same way at 1,100.

**Decision.**

- **A line cut by depth says so**: `TPanel [+53 below depth]`, beside the
  count that was already kept. The place is what the caller was missing.
- **`expand_hint` covers depth as well as collapsing**, naming only the
  ways this result actually hid something, and offering `within` or a
  larger `depth`.
- **The depth default stays at 5.** Raising it buys one target's document
  at the price of every other target's budget; the marker makes the way in
  one call away instead.

**Why this closes the gate below ~1,100.** The gate asked for the limits
to hold or for the number where they stop. The two limits that scale with
window count are measured: the budget holds to 20,002 synthetic windows
(D#210), and the real tree never reached it. The one that stopped holding
on the real client is structural, and now says where it cut. A loaded
client with many views may add D#210's collapse on top of the depth cut;
both are now hinted, and D#227 records that case on the first ordinary
`describe` of it -- `ghostdriver trace --scale --all-files` reads it back.
That is a reading, not an open gate.

**Evidence.** The real-client run, issue #28 (comment of 2026-10-12).
`tests/test_summarize.py`: the depth cut is marked on the line where it
happened, and a leaf at the floor is not. `tests/test_describe_scale.py`:
a client-shaped tree -- deep, narrow, nothing to collapse -- reports the
cut, marks it, hints depth and not collapsing, and `within` the marked
node shows the view. Issue #28; #229; D76; D#210; D#227; D11.

### D#231. A nested desktop lives in a slice named for its owner, and the next one reaps what a dead owner left

**Context.** `HiddenDesktop.teardown()` and `nested_env`'s sweep are
thorough, but only an owner that lives to run them runs them. One killed
outright -- an agent's timeout, a SIGKILL, a probe that raises before its
teardown -- left the whole desktop running: about 25 processes, the
runtime directory, and the document portal's FUSE mount in it. On linux-host-a
three sat for eight hours, and leaked helpers of the same kind fed RustDesk
a dead `DISPLAY` (it builds its server's environment from the user's
desktop helpers), so it stopped accepting connections.

**Decision.** Every process a desktop starts runs as a `systemd-run --user
--scope` in one transient slice, `ghostdriver_desktop_<pid>_<start>_<name>.slice`,
and its runtime directory carries the same `<pid>_<start>_`. The cgroup
holds whatever the desktop started, whatever session or group it moved
itself into, so teardown stops the slice as well as signalling groups.
Before building its own, `prepare` (and `nested_env`) stops every desktop
slice whose owner is gone and removes the directories such owners left,
unmounting first.

**"Gone" is the start time, read from `/proc` and compared only with
itself.** A slice outlives its owner by design, so its pid may since belong
to something unrelated; the pid alone would leak that slice forever. The
owner's start time (`/proc/<pid>/stat` field 22) goes into the name, and the
owner is gone when no process has the pid or the one that does started at
another time. Not systemd's `ActiveEnterTimestampMonotonic`: the kernel
counts the start time on a clock that includes suspend and that one does
not, so after a resume a live owner would look newer than its own slice.

**A directory is judged by its owner, not its age.** The first cut swept
directories nobody used that were older than a minute; measured, the one a
killed owner left was kept, because its dying processes had just written
into it and it looked as new as one being built. Age remains only for a
directory named for no owner.

**Only paths cross the command line.** `systemd-run` finds the user manager
through the operator's `XDG_RUNTIME_DIR` and session bus, which the
desktop replaces with private ones, so it runs with the operator's pair and
hands the private pair on through `env`. Nothing else goes there: the rest
of the environment can hold tokens, and `/proc/<pid>/cmdline` is
world-readable.

**Where there is no user manager** -- an ssh shell -- the desktop is built
unscoped, as before, and only unowned-directory sweeping applies.

**Nor below GNOME Shell 50, measured on CI.** The first cut assumed CI's
runner had no user manager. It has one, so every nested desktop there was
scoped, and every one failed: all 32 nested-probe tests reported "no
report" and the hidden-desktop probe hit its 60 s timeout, while the suite
went from 5 to 31 minutes. The shell's log said why. GNOME Shell 46
(`windowManager.js`, `_startX11Services`) asks systemd to start
`gnome-session-x11-services-ready.target` whenever `sd_pid_get_user_unit`
finds it in a user unit, which a scope is. It asks on its session bus,
which is the desktop's private one, where no systemd answers. Only
`NOT_SUPPORTED` ("not systemd managed") is ignored, so the failure fails
X11 initialization and Xwayland never comes up. 50.1 on linux-host-a has no such
call. So a slice is used only when `gnome-shell --version` is 50 or newer
(`SCOPED_SHELL_MAJOR`). 47 to 49 are unmeasured and treated as too old,
which costs them only the dead-owner reaping, as before this record.
Giving the private bus a systemd to answer, or pointing the call at the
operator's, were rejected: the second would start the operator's own X11
services from inside a nested desktop.

**Evidence.** `tests/test_hidden_desktop_lifecycle.py` (`env: any`): slice
naming and parsing, the command line, the fallback, which slices are
reaped, the start-time rule against a fake `/proc` and the real one, and
both directory rules. On linux-host-a: a desktop prepared, its owner `kill -9`ed,
30 processes and 213 tasks still in the slice; the next `prepare` stopped
it, unmounted the portal and removed the directory, leaving no unit,
directory or mount. `test_linux_watch.py` and `test_linux_restore.py` ran
their sessions in `nested0`/`nested1` slices and left nothing. Issue #231;
D#217.

### D#229. A suggested locator names one window, or carries the `index=` that makes it do so

Gate 3 on the real client (D#28) offered a captioned `TAdvToolBar` whose
caption three windows share. Used as offered it is refused as ambiguous
(D33), so the caller found `index=` by trial. `summarize` deduped the
*string* it offered and never asked how many windows the string names.

**Decision.** Each suggestion is resolved with the real `Locator.parse` and
`resolve` against the trees a later `find` searches (`searched=`), not
against what the summary rendered: the other holders of a caption are
often hidden, below depth, or inside a collapsed group, so counting
rendered lines misses exactly the cases that bit. A caption that matches
one window is offered as before. One that matches several is offered once
per *rendered* window, each with the `index=` that picks it, counted the
way `find` counts: across the searched trees, pre-order. `describe within=`
searches the trees from before it narrowed, since the suggestion is used
after `within` is dropped.

**Rejected: withholding and counting.** It would hide a real handle on the
window the caller was just shown. The index can drift if the tree changes;
`find` already reports that (#198).

**Evidence.** `tests/test_summarize.py`, `env: any`: a caption shared by a
hidden window and one below depth gets `index=0` and resolves to the
rendered one; two rendered sharers get `index=0` and `index=1`; the index
counts across trees. Issue #229.

### D#236. The UIA pattern rung names why it declined

**The field report.** Driving new Outlook, whose content is a WebView2
document, the pattern rung reported only "declined: returned without
delivering".

**What was wrong.** `act_via_pattern` caught every exception and returned
False, and returned False as well when the element published none of the
patterns it uses. So three different facts read alike: the element offers
no actionable pattern; the live element could not be found again by its
runtime id (the search stops at `MAX_ELEMENTS` under the host, which a web
view can exceed); or the pattern call itself raised. D#145 made the ladder
record a rung's reason, and this rung never gave one.

**Decision.** The rung raises `ElementError` naming which of these
happened -- including which patterns the element does publish, and when
the search for the live element stopped at its cap -- and the actuator
records the message as the rung's `declined` reason. The ladder still
falls through to the next rung exactly as before. Nothing about whether
WebView2 is drivable is decided here; this makes the next attempt say why
a rung declined.

**Evidence.** `tests/test_windows_elements.py`: an element with no
actionable pattern is declined naming what it does publish; one whose
runtime id is gone is declined as no longer on the surface; a rung's
message reaches the result's `declined` (`env: windows`, the fixture's tab
control). Issue #236; D#145; D45.
### D#234. `restore` falls back to the command a taskbar click sends

**The field report.** On the VendorApp client, after the operator minimized it
or a session timed out, `restore` said again and again "asked to restore 1
window(s); none came back on screen -- the window manager declined", until
the operator clicked the taskbar.

**What was wrong.** `restore` un-minimizes each minimized top-level window
with a no-activate show and relies on the application re-showing its own
forms (the design this module rests on). A classic Delphi application
minimizes through its hidden application window, and its forms come back
through the toolkit's own restore, which runs on `WM_SYSCOMMAND` /
`SC_RESTORE` -- the system command a taskbar click sends -- and not on
the window being shown. The fixture re-showed its form on the size change
a show produces, so the tests never met the case.

**Decision.** When the no-activate show brings nothing back, `restore`
posts `SC_RESTORE` to the windows that were minimized and waits again.
The result names the route (`route: restore_command`), and the note says
the plain un-minimize was not enough. The fallback may take the
foreground, as a taskbar click does; `took_foreground` already says
whether it did, and `restore` is already marked as changing the screen.
It is still the application that decides which forms come back: the
command asks it to restore, and a dialog it keeps hidden stays hidden.
When neither request brings anything back, the note says both were tried
and to ask the operator to click the taskbar.

**Evidence.** `tests/test_windows_restore.py`: the minimized fixture gains
a mode in which its form comes back only on the restore command, answered
without `DefWindowProc` so nothing is activated; in that mode the form
comes back through the fallback with `route: restore_command` and the
decoy stays hidden, and an ordinary target needs no fallback. The focus
guard stayed green. `tests/test_restore_result.py`: both notes. `env:
windows`; not yet confirmed on the real client. Issue #234; D73.

### D#238. A profile can declare a cadence per control class

**The field report.** A rich-text editor class ignored `type_text` and
`send_keys` posted at robot cadence and accepted `send_keys` at
`fast_human`. The profile could say "type at a human pace" per surface
(web or native, D26) and nowhere narrower, so the fact could not be
written down and every session would rediscover it.

**Decision.** Profile key `cadence_for_class`: fnmatch class patterns,
each naming a cadence. It is declared, not learned (D35). Precedence, most
specific first: a cadence named on the call; the class key; the
per-surface notes; robot. The choice moved out of `acting.py`, which sat
at the tool-module limit, into `tools/cadence_choice.py` (D60).

**Not done.** An automatic retry at a slower cadence after a fast one did
not land, as was asked for: it would hide which cadence worked, which is
the fact worth recording (D45), and a retry is what the conventions rule
out. Which classes need it, and the warning that another rich-edit class
accepted nothing at either cadence and left the client ignoring real
keystrokes afterward, are target knowledge and go in the operator's
profile, not the repository.

**Evidence.** `tests/test_cadence_for_class.py`: the declared cadence
applies to its class only; a cadence on the call beats it; it beats a
blanket surface note; no key changes nothing; the key is read and a bad
value refused (`env: any`). `check-profile` lists the key. Issue #238;
D26; D35; D45; D60.

### D#240. "The same action again" means the same action

**The field report.** After two no-effect clicks at different points on
one control, a right-click at a third point was reported as "delivery #3
to this control with no effect ... the same route will not act on a
retry". Two of the three were different actions.

**What was wrong.** D#195 counted every failed actuation on the same
locator in the session. The count never refuses anything -- it is the
lead sentence of the message -- but the sentence claimed a retry where
there was none, and told the caller to stop exploring a control it had
only probed.

**Decision.** The ledger records what exactly was sent (`action`: for a
click, its button, count and point). The count matches tool, locator and
action, and the sentence says "this same action". A different button,
point or count on the same control starts its own count.

**Evidence.** `tests/test_outcomes.py`: two failures of the same action
are counted and said; three different actions on one control are not
called a repeat (`env: any`). Issue #240; D#195.
### D#242. A profile is offered at attach; find looks before it suggests; a restart can be seen

**The field report.** A target with a profile on disk was driven
unprofiled for two days: `attach` without `profile_path` loads nothing and
said nothing, and the profile's control notes appeared only inside error
results. A missing profile name failed as "No such file". `hit_targets`
listed a child window that `find` then called not found. A server restart
was discovered only when the next call failed.

**Decision.**

- **Offered, never applied.** `attach` without `profile_path` lists, as
  `profile_candidates` with a `profile_hint`, every profile whose
  `executables` (a new key: executable file names) or probed
  `executable.path` names the target's executable. It loads none of them:
  a profile carries policy -- a denylist, a cadence, menu routes -- and
  silently applying the wrong one is worse than offering the right one.
  More than one can match; the operator chooses.
- **A missing name lists what is there**, instead of a file-not-found.
- **`describe` carries the notes** for the classes in what it described,
  up to twelve, so a session that describes first sees them before an
  action fails.
- **`find` looks before it suggests.** An empty main-window search counts
  matches in the other top-level windows and says which case it is: some
  there (retry with `all_windows`), or none anywhere, which for a control
  shown only under the pointer or while a menu is open means it is gone
  between calls. The two tools walk the same tree; they disagreed because
  one searched more of it.
- **A restart can be seen before it costs a call.** `list_targets` and
  `attach` carry `server_generation`, which changes when the server
  process restarts. In development mode a pending reconnect is repeated on
  those two results, where a client decides to start a long batch; other
  calls that worked stay quiet, as D#70 decided.
- The `capture` description says that an HTTP error from the client is a
  transport failure, not a result from this server, and to retry once at
  a smaller `scale`. This server cannot see or type that error.

**Evidence.** `tests/test_profile_discovery.py`: profiles listed by bare
name with backups excluded; candidates matched by file name through either
key; a missing name lists the profiles; attach offers a matching profile
and loads nothing; `describe` carries the notes; `find` counts other
windows both ways; the generation names this process (`env: any`).
`tests/test_devreload.py`: the pending reconnect is said on attach and
list_targets and not on other calls. `tests/test_tools.py`: the empty-find
hint now says when no other window has a match. Issue #242; D#137; D#70;
D35.

### D#244. A delivered action with no effect carries a hand-off for a person

**The field report.** In-place rich-text editors (windowed child controls)
ignored every posted click and keystroke, in and out of block edit. The ask
was either a real-pointer primitive or an explicit hand-off result carrying
the exact screen point and class, rather than the generic no-effect text.

**Decision.** No pointer primitive: ghostdriver never moves the operator's
mouse (D#133). The hand-off is in scope. A `delivered_no_effect` result
now carries `handoff`: the control's class, the screen point the action
aimed at (logical, and physical when the display is scaled), the routes
already tried, and an `ask` sentence ready to give `await_human`. It names
no tool. What takes the step -- the operator, or whatever the operator
chooses -- is the caller's and the operator's decision, not this server's.

The outcome logic moved from `acting.py`, which this would have taken past
the tool-module limit, into `tools/outcome.py` (D60).

**Evidence.** `tests/test_outcomes.py`: a no-effect result carries the
hand-off with the class, the aimed point, the routes tried and an ask that
names no tool; without `at` it aims at the control's centre; a raised
window carries none (`env: any`). Issue #244; D#133; D#195; D#240.

### D#246. A declared profile is offered before one a probe recorded

**What was seen.** Attaching to a VendorApp client without `profile_path` right
after D#242 landed offered four profiles and suggested an old probe file
first. Candidates were sorted by name, and a profile matched either by an
`executables` list a person wrote or by the `executable.path` a probe
recorded -- so a probe's output outranked the curated profile.

**Decision.** Profiles that declare the executable come first, then those
that matched only through probe evidence (D35: declared beats learned), and
the offer says which is which (`profile_matched_by`). The hint suggests the
first. Nothing is loaded either way (D#242).

**Evidence.** `tests/test_profile_discovery.py`: the declared profile is
ordered before the probed one, the offer carries how each matched, and the
hint names the declared one (`env: any`). Against the operator's real
directory the curated profile is now offered first. Issue #246; D#242; D35.

### D#252. Attach dates the approval it acts on, and says it sets no tier

**What was seen.** An attach to Outlook on 2026-10-27 reported an approval
recorded on 10/21 and kept across server runs (R1a). The result showed its
source and note but not when it was given, nor that it had been kept. So
the caller could not tell a fresh approval from a week-old one when
deciding whether to ask again. It also could not tell what tier had been
approved, because an approval approves none.

**Decision.** Attach's `consent` is `Grant.summary()`. It always carries
`source`, `note`, `granted_at` (local date and time) and `covers`. It adds
`restored`, `inherited_from` and `standing_for` only when they apply.
`covers` says what an approval reaches: this process and the ones it starts.
It also says that an approval sets no tier, because the tier is chosen at
each attach. How long an approval lasts depends on configuration and stays
where it is true, in the `lifetime` sentence of a consent request.

**Evidence.** `tests/test_consent_summary.py` (`env: any`). Issue #252.
### D#250. `absent` searches every window unless told not to

**What was seen.** Every `{locator, absent: true}` that named a dialog had
to carry `all_windows: true` as well. Without it, the D#118 pre-check
refused, because the dialog does not resolve in the main window. This cost
two round trips each time: once in the Outlook Open dialog (2026-10-27) and
again across the VendorApp client's prompts (2026-10-22).

**Decision.** `absent` defaults to every top-level window, and
`all_windows: false` narrows it. Other expects keep the main-window
default. The asymmetry is deliberate. What goes away is usually a dialog,
which is a window of its own. And "gone" is a claim about everywhere, so the
wider scope can only make the condition harder to meet. It cannot turn into
a false green (D#71), which a wider scope on a *presence* expect could.

**Evidence.** `tests/test_expect_absent.py`: unasked, the resolver is
called with every window; with `all_windows: false`, with the main window
only (`env: any`). Issue #250; D#118.

### D#254. `list_targets` narrows by process name and by having something on screen

**What was seen.** On a field laptop, 153 processes came back as about 15 KB
of JSON, all to find one pid (olk.exe). Most entries were tray agents and
helpers with no window on screen.

**Decision.** `list_targets` takes `name`, a case-insensitive glob on the
process name, applied before any window is enumerated. It also takes
`visible_only`, which keeps only processes with at least one visible
top-level window. Both are off by default, so the list a person is shown
when deciding what to allow is still the whole one. A filtered result says
what filter was applied (`filter`).

**Evidence.** `tests/test_list_targets_filter.py` stands in the backend and
the process list, so it runs on every platform (`env: any`). The test caught
an existing local `name` in the loop shadowing the new parameter. That local
is now `shown`. Issue #254.

### D#249. On the person's desktop, a Chromium host gets no UIA pattern call

**What was seen.** New Outlook (WebView2) on 2026-10-27: a click on the
Drafts folder worked through the posted rung. Outlook never reported the
item `selected`, so the expect failed and the ladder fell through to
SelectionItem.Select, and Outlook came to the front. The cause was then
measured on the operator's desktop with a real Edge `--app` window on a
scratch page. Every UIA pattern call took the foreground and worked: Invoke,
SelectionItem.Select, Toggle, ExpandCollapse, and Value.SetValue on a
checkbox and on a field, 7 of 7. Every posted route worked and took
nothing: clicks on a button, a tab, a checkbox and a tree item, and typing
into a field, 0 of 6.

**Decision.** On a host matching `Chrome_WidgetWin_*` or
`Chrome_RenderWidgetHostHWND`, `act_via_pattern` and `set_value_via_pattern`
decline before calling anything, with a reason that names #249. The ladder
reports it as that rung's `declined`. They are declined, not tried and
reported, because a disturbance report does not give the desktop back
(D28 still reports any take). The gate holds only on the input desktop: a
hidden-desktop session's window has no foreground to take, so the fixture's
SetValue-commits measurement (D30) still runs there. A desktop this server
made (`ghostdriver-…`) counts as nobody's. Otherwise, a desktop that cannot
be identified counts as the person's.

**Not covered.** The window-level `click_via_uia` and `set_value_via_uia` in
`input.py` (an HWND's own pattern) are not gated. A Chromium top-level window
was not seen publishing Invoke or Value, so this is unmeasured, not
decided. Also loose: after posted typing, `send_keys ["end", "x"]` did not
change the field. That is unexplained and tracked on #249.

**Evidence.** The measurement is in the issue comment on #249.
`tests/test_windows_chromium_pattern_gate.py` covers the gate on both hosts,
the hidden-desktop exemption, a native host passing through, and a
`ghostdriver-` desktop's own thread answering "not the input desktop"
(`env: windows`). `tests/test_windows_web.py` (hidden desktop) still takes
tier 1. Issue #249; D21, D30, D28.

### D#258. `find`'s look in the other windows reports its own failure

**What was seen.** While measuring #257, `find("type=Document")` matched
nothing in the main window. Its #242 follow-up, which counts matches in
the other top-level windows, raised `ElementError` (the Chromium
accessibility surface was momentarily unavailable). The whole `find` then
failed with a traceback, because the follow-up caught only `ValueError`.

**Decision.** The follow-up is advice, so a failure in it is reported and
never raised. `find` returns its main-window answer, with
`matches_in_other_windows: null` and a hint naming why the other windows
could not be looked at. It is null, not 0: "could not look" is not "none
there", and reporting 0 would be the reassuring-but-wrong answer (D10,
D35).

**Evidence.** `tests/test_profile_discovery.py::test_find_still_answers_when_it_cannot_look_in_other_windows`
(`env: any`). Issue #258.

### D#257. A posted click is not aimed by a rectangle outside its own window

**What was seen.** On 10/29 a posted click on Outlook's Drafts folder landed
on Notes. Outlook (a WebView2 host) was on the second monitor, which runs
at 100% while the primary runs at 125%. The server is DPI-unaware.
Re-measured read-only with Outlook maximized there: the element rectangles
and the click conversion were both correct, so the 10/29 window state is
unknown. An Edge test window on the same monitor showed the fault: at one
window position the rows were reported where they were not drawn, and the
click aimed at Row 3 landed on Row 4. At another position the same page
reported true. No correction fitted both positions. A hit test before the
click (ElementFromPoint) was ruled out: it answers with whatever window is
on top, and ghostdriver clicks windows that are behind others.

**Decision.** One thing a wrong rectangle can show is that it lies outside
its window. In the measured case, Row 3 ended at x=2934 in a window ending
at x=2820. An element cannot be drawn where its window is not, so
`click_posted` refuses a rectangle that is not inside its top-level
window's rectangle. It raises `ElementError` naming #257 before anything is
posted, and the ladder reports that as the rung's `declined`. The check is
against the top-level window, not the host, so a row scrolled half out of
its list still passes. A row cut off at the window's own edge is refused
too, and the message says to scroll it into view. This guard covers every
host, not only Chromium: a rectangle outside its window is wrong wherever
it comes from. Typing into an element and sending keys to one focus it
through the same click, so they inherit the guard.

**Not covered.** A shift small enough to stay inside the window passes. An
expect that names the click's result is what catches that, which is why
the `outlook-new` profile asks for one on every click. The cause of the
shift is not known.

**Evidence.** The measurements are on #257.
`tests/test_windows_rect_guard.py` covers the measured rectangle, each edge,
a rectangle inside, and one on the window's own edges (`env: windows`).
Issue #257; D10, D33, D#249.

**Follow-up: descending into a child window converts once.** The same
investigation found the two conversions disagreeing on that monitor:
`ClientToScreen` scaled x by the primary's 1.25 and `ScreenToClient` did
not. `deepest_child_at` chained them at every descent into a windowed
child (D66), so a point reaching a child could move by a quarter of its
distance from the screen origin. It did not descend in the measured
Outlook case, so this is not shown to be the 10/29 miss. Every hop is now
converted from one screen point with `ScreenToClient` alone, the call that
already places the element's rectangle in its host's client area, so a
descent no longer mixes the two. The screen point is recovered from the
host's origin as `ScreenToClient` reports it, which lets the `click_window`
path, which starts from a client point, share it. Not measured on a
mixed-DPI desktop: no machine with one was reachable from this session.
`tests/test_windows_child_descent.py` builds the measured disagreement into
a stood-in window tree and checks the point reaches the child unmoved; it
fails on the chained version.

### D#248. `changed` is refused on an action whose effect is text

**What was seen.** On 2026-10-22 a `type_text` into `TWPRichText` (VendorApp
client's Text Object Editing dialog) with `expect={changed: true}` at
`fast_human` returned `ok: false`, `outcome: delivered_no_effect`, and a
hand-off asking a person to click the control. A capture straight
afterwards showed every character had landed.

**Why.** `changed` compares the shape digest, the set of top-level windows
and `blocked_by` (D77, #194). Text painted inside a control that keeps its
size moves none of them. So `{changed: true}` could never be met by text
entry into an owner-drawn editor, and a miss read as "nothing happened"
when something had. A caller who believes that retries and types the text
twice, or hands a finished step to a person.

**Decision.** `type_text`, `set_value`, and `send_keys` with any
single-character key refuse `changed: true` before anything is sent, with
a message that says it cannot see text and names what to use instead: a
`locator` with the `text` it will read, a control the text makes appear,
or a capture. This is the same shape as the refusal of an expect that
already holds (#128): a postcondition that cannot report the effect is
refused, not run. `send_keys` with named keys alone (`enter`, `escape`)
keeps `changed`, because those keys can open or close a window, which
`changed` does see. The character test is the one `send_keys` already uses
to refuse a protected field.

**Not chosen.** Comparing the target control's pixels under `changed` on
these tools. It would see painted text, but a pixel diff also moves on a
caret blink or a hover tint, so it is weaker evidence and would
need its own field rather than `verified: effect`. It can be added later
as its own expect key if a field case needs it. The 2026-10-21 note that
`TWPRichText` ignored `type_text` at robot cadence was measured with
`changed`, so it is unproven either way until it is re-measured with a
capture.

**Evidence.** `tests/test_changed_blind_to_text.py` (`env: any`) checks
each tool refuses before `_perform` is reached, and that named keys alone
still build a `changed` condition. Issue #248; D77, D#128, D10.

---

## The public repository, from v0.2.0

> Development moved to `steiner385/ghostdriver` after v0.2.0. Everything
> above was decided in a private tracker, and its `#N` and `D#N` numbers are
> that tracker's issues -- none of them can be opened from here. They stay
> as they are: they are the identifiers the source tree cites.

### G#1. Decisions are numbered from this repository's issues, as G#N

**Decision.** A decision that comes out of issue N of this repository is
headed `### G#N.`. The `D#N` series is frozen, like D1–D77 before it: its
123 entries, up to D#258, and every reference to them stay as they are, and
no entry is added to it. The rest of the D# rule carries over unchanged:
open an issue first if the decision has none, one issue gives one decision,
and a suffix (`G#12a`, `G#12b`) splits an issue that really did produce two.

**Context.** D#N was numbered from the private tracker's issues, whose
counter reached #264. This repository's issues start again at #1, so
continuing D# from them would head the decision from issue 12 `D#12`, a
number that already means something else, or reuse one that never
happened to be taken. Either way a reader following `D#12` could not tell
which tracker it meant. The reason for numbering by issue (the block above
D#8: a shared counter collided three times in a day) is unchanged, so the
scheme stays and only its namespace moves.

**Not chosen.** Creating placeholder issues until this repository's counter
passed #264, so that D# could carry on. That would mean about 265 empty
issues on a public repository, opened in bulk against GitHub's rate limits.
Also not chosen: a qualified `D#gd-N`, which says the same thing as `G#N`
in more characters.

**Evidence.** `tests/test_structure.py`:
`test_no_new_decision_extends_the_private_tracker_series` pins the frozen
series by count as well as by highest number, because a new `D#13` where
none existed would pass any ceiling. It failed as intended on a test entry
added for the purpose. `test_no_issue_numbered_decision_is_used_twice` now
covers both prefixes, and spec §12's "Answered" rows may point at either.
Issue #1.

### G#3. A posted click on a Chromium host on a monitor at another scale is refused

**What was seen.** The desktop has a 125% primary (DISPLAY1) and a 100%
DISPLAY2 to its right, and the server is DPI-unaware. On it, a posted click
on New Outlook's Drafts folder opened Notes. It was re-measured on
2026-11-06 with Outlook on DISPLAY2. Maximized, the Drafts rectangle was
drawn where UIA said, and the centre converted correctly to the host's client
point (172, 443). It was posted to the host itself, with no descent, and
Outlook opened Notes, which contains y 443 x 1.25. The Inbox click before
it missed by the same factor. Restored at (2400, 150) and at (1930, 430),
the same path opened Drafts. An Edge `--app` window on that monitor showed
the reverse: restored at (2400, 150) the rows were reported shifted and the
click hit the next row, and at (1930, 430) it landed. The private
tracker's issue #257 has the earlier half of these measurements (D#257).

**Decision.** `click_posted` refuses before posting when the host is
Chromium's (`FOREGROUND_TAKING_HOSTS`, the same match as D#249) and the
host window's monitor is not at the system dpi. The refusal names the two
dpi values and G#3, and the ladder reports it as the rung's `declined`.
Four cases, two hosts, and both ways round: no rule (maximized or
restored, an offset from the monitor's origin) fits them. And the miss is
silent, because the click is delivered to the wrong item. So the click is
refused rather than aimed by a guess (D33, D53).

The dpi is read in a per-monitor-aware thread context, set for the call
and restored. Asked from this process's own context, `GetDpiForMonitor`
and `GetDpiForSystem` answer 96 whatever the hardware, so the
virtualization would hide itself from the question.

`physical_rect` is `null` for a rectangle on such a monitor. Logical x the
primary's scale put Outlook's window at physical 2412 when it was at about
1930. It is `null`, not absent, because absent already means "the display
is unscaled, so it equals `rect`" (D73). A click result now carries
`posted_point` (the window, its client point and the screen point), and
the trace keeps it. The 10/29 trace could not show where its click was
sent. The D#257 refusal no longer tells the caller to maximize the window,
because maximized is the state that missed.

**Not chosen.** A correction factor: none fitted both hosts. A hit test
before the click: D#257 ruled it out, because it answers with whatever
window is on top. In the maximized case it would also have said Drafts,
because the rectangle was right. Running the conversion per-monitor-aware:
the conversion was already right, and the error is in how the host reads
the posted point. Nothing measured says posting from a per-monitor-aware
context changes that.

**Not covered.** A native (non-Chromium) host on such a monitor is
unmeasured, not cleared. A desktop where every monitor runs at the same
scale refuses nothing. The cause of the misread is still not known. Lifting
the refusal needs a measurement on the mixed-dpi desktop, not a model. Also
not checked on the mixed-dpi desktop: that the monitor and system dpi
read there are 96 and 120. No machine with one was reachable from this
session, which had a single-monitor Windows VM.

**Evidence.** `tests/test_windows_dpi_guard.py` stands in the monitor's dpi
and covers the measured case on both Chromium host classes, a monitor above
the system scale, an equal or unknown dpi clicked, a native host passed,
and the guard's new advice. It also asks Windows for real that the
bindings answer, that monitor and system agree on the primary, and that the
thread's awareness is restored (`env: windows`).
`tests/test_posted_point_and_physical_rect.py` covers `physical_rect`'s
null and `posted_point` with the backend stood in (`env: any`). Issue #3;
D33, D53, D73, D#249, D#257.
