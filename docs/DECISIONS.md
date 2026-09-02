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
