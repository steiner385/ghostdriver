"""Run a sequence of session tools in one call (D#75).

A hybrid loop is mostly deterministic -- click a tab, set a field, press
Ok, click a row, embed, save -- and each of those steps used to cost a
round trip. `batch` runs a list of them in one call, each carrying its own
`expect`, stopping on the first that does not verify, and reports every
step's verdict.

**It is only a dispatcher.** Each step calls the same Toolbox method a
standalone call would, so it passes the identical `authorize`, denylist and
tier checks -- the batch adds no path around any of them, and grants nothing
a step could not already do. That safety model, and the allowlist that
enforces it, live in `stepper.run_steps` (D#83), shared with the macro
runner so there is one place both go through. Lifecycle and consent tools
(`attach`, `release`, `grant_*`, `launch_isolated`) and the two that
interrupt a person (`foreground`, `await_human`) are not runnable there: a
batch drives an already-approved target, it does not change what is approved
or wait on a human.

**Stop on first failure, by default.** A loop's steps depend on each other
-- there is no point pressing Ok on a dialog that never opened -- so a step
whose result is not `ok` stops the batch and the ones after it do not run.
`stop_on_failure=false` runs them all regardless, for a batch of independent
reads. Either way the result says how far it got and carries each step's
verdict, so a failure is located, not just reported.
"""

from ..model.result import GhostdriverError
from .core import _error, _ToolboxCore
from .stepper import run_steps


class BatchTools(_ToolboxCore):
    """Run several session tools in one call, each with its own expect."""

    def batch(self, session_id: str, steps: list, *,
              stop_on_failure: bool = True) -> dict:
        """Run `steps` in order against one session.

        Each step is `{tool, args}`: `tool` is one of the runnable tools (the
        session-scoped read-and-act set), `args` its keyword arguments
        *without* a session, which the batch supplies. A step carries its own
        `expect`, so its verdict is real, not "sent". The first step that does
        not verify stops the batch unless `stop_on_failure` is false.
        """
        try:
            self.sessions.authorize(session_id, "batch")
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)
        return run_steps(self, session_id, steps, stop_on_failure=stop_on_failure)
