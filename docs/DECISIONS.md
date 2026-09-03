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

## Open, for whoever picks this up

- **The denylist matches captions and nothing else.** It is now exercised
  end to end -- an actuation resolves, the caption is checked, and a match
  refuses before anything is sent. What it cannot express is a control
  identified by anything other than its caption: an unlabelled toolbar
  button, or a grid cell. Those are exactly the controls a person would most
  want to forbid.
- **Nothing gives *exact* text out of an owner-drawn region.** The model can
  read a capture, which is enough to decide what to do next, but not enough
  to verify a value (D46). The routes that would give exact text -- the
  control's own clipboard copy, an export command, a hidden accessible
  surface -- are unprobed. That is the gap worth closing, and it is a
  different gap from the one OCR was imagined to fill.

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
