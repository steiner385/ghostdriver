# Decision log

Decisions and assumptions made while building, with the reasoning and the
evidence behind them. Written so that a decision can be *disagreed with*
later — which needs the reason, not just the outcome.

Newest last within each iteration.

---

## Iteration 2 — MCP server, read-only tier

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

---

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
