# ghostdriver-mcp

An MCP server that drives desktop applications without stealing the desktop from
the person using it. There are two backends. Windows is complete. Linux
(X11, AT-SPI) wires 38 of the 42 contract names. Its missing piece is
assessment (`region_evidence`, `resolve_hosted_app`, `assess_uia`,
`assess_msaa`), so `surfaces` and `probe` refuse there. `docs/LINUX.md`
says what has been measured and what has not.

Read `docs/DECISIONS.md` before changing behaviour. It is the project's real
tracker: every decision that mattered was forced by a measurement, and it is
written so a decision can be *disagreed with* later — which needs the reason,
not just the outcome. New decisions go at the end of the current iteration,
numbered, with the evidence.

**Number a new decision from its issue in this repository.** The decision
that came out of issue 12 is `### G#12.`; if the thing you decided has no
issue, open one first. GitHub hands each issue number out once, so two people
working at the same time cannot pick the same one.

Two older series are frozen, and `tests/test_structure.py` fails if either is
extended, so you do not have to remember this:

- **D1–D77**: numbered from a counter. Several hundred references across the
  source tree point at them.
- **D#N** (123 entries, up to D#258): numbered from the issues of the private
  tracker this project was developed in until v0.2.0. A `#N` or `D#N` in the
  log, the source or a commit message before v0.2.0 means *that* tracker's
  issue N, not this repository's. Why there is a new prefix: G#1.

Numbers now skip and arrive out of order, because issue numbers do. That is
expected, and two tests deliberately assert that neither contiguity nor
sorting is required — don't add a guard for either.

## Environment-gated issues

**This repository cannot be fully worked from one machine.** Most issues are
tagged with the environment they require. Check the tag before you start.

| Label | Project field | Means |
|---|---|---|
| `env: windows` | `Environment: Windows only` | Needs a Windows box. The target, the fixture and the backend under test are Win32. |
| `env: linux` | `Environment: Linux only` | Needs a Linux box with X11, an AT-SPI bus and GTK. |
| `env: any` | `Environment: Any` | Docs, spec, or platform-neutral code. Work it anywhere. |
| `env: both` | `Environment: Both - Linux then Windows` | Edit and reproduce on one, re-verify on the other before merge. |

### The rule

**Do not start an issue whose environment you are not on.** Not "start it and
see how far you get" — the failure mode is silent, which is the whole reason
this rule is written down rather than assumed.

### If you picked one up by mistake

Put it back so the next implementer finds it available:

1. Clear the project **Status** field back to **Todo** (or empty). An issue
   left in *In Progress* reads as claimed, and the next person skips it.
2. **Unassign yourself.**
3. Push or discard your working branch — do not leave a half-finished branch
   that looks like progress.
4. Comment only if you learned something worth keeping. "Wrong environment,
   putting it back" needs no comment; the Status change says it.

Doing this promptly matters more than doing it neatly. A wrongly-claimed issue
is invisible to everyone else until it is released.

### Why the rule is not "just run the tests and see"

A wrong-platform run **looks like success**. Measured on Linux, re-measured
for #39:

- 1021 collected, 589 passed, **430 skipped (42%)**. Collection itself now
  works: `conftest.user32()` defers the `ctypes.WinDLL` binding to call time,
  so a module that needs Win32 skips instead of aborting the run (issue #21).
- **370 of 956 test functions are in 41 modules gated `on_windows` at module
  level.** Most of that is correct — the subject really is Win32 — but not
  all of it was, and #39 audited the difference. See `D#39`.

`tests/conftest.py` defines the gate that produces those skips:

```python
on_windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows backend test")
```

So on Linux, **a green run has verified less than half the suite** and told you
nothing about the backend. `docs/LINUX.md` sets the mirror-image convention for
Linux tests: `tests/test_linux_*.py`, skipped where `sys.platform != "linux"`.

Neither platform can confirm the other. Treat "no failures" as "no failures
*among the tests that ran*", and check what ran.

## Platform boundaries in code

- Platform-specific code lives **only** under `src/ghostdriver/backends/`.
  `backends/__init__.py` holds the contract and `load()` picks the backend by
  `sys.platform`.
- A structure guard enforces this in `tests/test_structure.py`: every module
  must be reachable from an entry point, and the source tree may hold no
  profile, workflow or report. If it fails, the fix is to move the code, not
  to loosen the guard.
- Everything above the boundary — locators, resolution, the tier ladder,
  cadence, disturbances, the ledger, consent, the operator directory,
  workflows, the surface model — is platform-neutral and reads `WindowNode`s
  and `AccessibleElement`s. Keep it that way (D59).
- No module under `src/ghostdriver/tools/` may exceed 400 lines
  (`TOOL_MODULE_LIMIT`, `tests/test_structure.py`). This is a test, not a
  convention, because the promise was broken once when it lived only in a
  decision record (D60).

## Testing

```bash
PYTHONPATH=src python3 -m pytest
```

`ruff` and `mypy` run under `pytest` via `tests/test_quality.py`
(`test_ruff_finds_nothing`, `test_mypy_finds_nothing`); a failing lint or type
check is a failing test.

**mypy runs once per backend, not once.** One run assumes one platform, and a
run with none set assumes the *host* — which made the same tree give 39 errors
on Linux and none on Windows. Each pass names its `--platform` and excludes
the other backends; the shared tree is checked under every platform, each
backend under its own (D#23). Adding a backend means adding it to
`BACKEND_PLATFORMS`, and a test fails if you don't.

A session-long focus guard (`tests/test_zz_focus_guard.py`, last in the run on
purpose) fails any run in which a test-spawned window takes the foreground. If it trips, something took the desktop from the operator —
that is the bug the project exists to prevent, so do not silence it.

## Conventions that are easy to get wrong

- **Errors are results, not exceptions** (D10). A tool returns a result that
  explains itself; it does not raise at the protocol layer.
- **A disturbance is reported, never a verdict** (D28). Noticing that the
  desktop moved is information for the caller, not grounds for failing.
- **A measurement never overrules a person, at any grain** (D35). A declared
  note beats a learned one.
- **Refuse ambiguity rather than picking** (D33). If a locator matches more
  than one thing, that is an error, not a coin flip.
- **A target the strategy cannot fit is reported as such, not worked around**
  (D53). Do not loosen a sandbox or elevate to make an unfitted target work.
- **Do not "fix" a flaky test with a retry.** A retry takes the evidence with
  it; instrument it so the next occurrence explains itself (D45).
- **Never gate a guard on the condition it exists to detect.** Two tests
  claimed to prevent a stack trace and could not run where the stack trace
  happens: one asserted "an error, not a traceback" and was `@on_windows`,
  where a backend exists; the other tested the wrong dependency version from
  inside a module that skipped unless the right version was installed. The
  tell is a gate naming the same condition as the assertion, with opposite
  polarity. Put the test where the failure is *possible* — or make it
  platform-neutral by construction, by making the subject fail on purpose.
  The same failure at scale is a whole module gated because the *fixture* it
  reached for was platform-specific, not the promise it checks: prefer the
  seam that needs no backend (`SessionManager.attach`, not the `attach`
  tool). `test_structure.py::test_neutral_policy_tests_are_not_gated_to_one_platform`
  guards a named list of neutral-policy modules. Audit and what is left:
  `D#39`, issue #39.
