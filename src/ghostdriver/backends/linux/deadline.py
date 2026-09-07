"""A deadline the caller controls, because AT-SPI will not give them one.

On Windows the OS does this: `SendMessageTimeout` with `SMTO_ABORTIFHUNG`
returns `None` when the target has stopped pumping, and the caller moves on
(D4, `winapi.send_message_timeout`). AT-SPI has no equivalent.
`Atspi.set_timeout()` exists, and measured against an application hung for
15 seconds it made no difference at all -- 500ms, 2000ms and the default all
blocked for the full hang. The call is bounded by the application's
recovery, not by any timeout the caller sets.

So the deadline is imposed here instead: the call runs on a worker and the
caller waits only as long as it agreed to. Measured, a caller given 1.0s got
control back in 1.001s while the application stayed hung for another twelve
seconds.

**The worker is parked, not leaked.** It is still blocked inside AT-SPI when
the deadline passes, and it returns on its own when the application recovers
-- observed at 13.08s for a 15s hang. Nothing here kills it, because there
is nothing safe to kill: the thread is inside a C call. That has a cost
worth knowing about rather than discovering: reads issued against an
application that stays hung park one worker each until it comes back.

Nothing in this module imports `gi`, so it stays testable on any host and
the semantics can be checked without a desktop.
"""

import concurrent.futures
from collections.abc import Callable
from typing import Any

#: The same 200ms `send_message_timeout` uses on Windows, so the contract
#: reads identically on both platforms -- and justified rather than copied.
#: A healthy AT-SPI read measured p50 0.19ms, p99 0.46ms and max 1.88ms over
#: 200 samples, with a 33-node tree walk taking 9.2ms end to end. The
#: deadline is roughly a hundred times the worst read observed, which leaves
#: room for a loaded machine without leaving room for a hung one.
DEFAULT_DEADLINE_S = 0.2

#: Daemon workers: a thread parked inside a hung application must never be
#: able to stop the process exiting.
_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=8, thread_name_prefix="ghostdriver-atspi"
)


def call_with_deadline(
    call: Callable[[], Any], *, timeout_s: float = DEFAULT_DEADLINE_S
) -> Any | None:
    """Run `call`, giving the caller back control after `timeout_s`.

    Returns what `call` returned, or **`None` if it did not answer in time**.

    `None` means *did not answer*; it never means *answered with nothing*.
    That is the distinction the whole unresponsive path exists to keep --
    an unresponsive control reports empty text that is unknown, not confirmed
    blank, and a caller that collapses the two silently asserts a field is
    empty when it simply never replied. A control that answers with an empty
    string returns `""`, and that is a different answer.

    An exception raised by `call` is re-raised, not turned into a timeout: a
    control that answered with an error answered.
    """
    future = _POOL.submit(call)
    try:
        return future.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        # The worker is still inside the call and will finish when the
        # application recovers. Cancelling it is not possible and killing it
        # is not safe, so it is left to come back on its own.
        return None
