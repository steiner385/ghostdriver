"""launch_isolated: start a target on a hidden desktop and open a session.

Split from lifecycle.py (D60): the hidden-desktop launch is a distinct
concern -- the tool's one process-launching path, gated on a per-command
grant -- and keeping it here holds both files under the module limit.
"""

import uuid

from ..model.result import ErrorKind, GhostdriverError
from ..policy import Tier
from .core import _error, _ToolboxCore


class LaunchTools(_ToolboxCore):
    def launch_isolated(
        self,
        command: list[str],
        *,
        tier: str = "read_only",
        announces_pid: bool = False,
    ) -> dict:
        """Launch a target onto a hidden desktop and open a session on it.

        The only way to get a hidden-desktop session: the strategy is
        launch-only, because a window's desktop is fixed when it is created
        and a running target cannot be moved to one. So this is also the
        tool\'s one process-launching path, and it is gated the way R1 gates
        automation -- nothing launches until the operator has approved this
        exact command. An unapproved command comes back needs_consent naming
        it; the agent asks, and the operator records the answer with
        grant_launch. Consent is on the command and lasts the session.

        The guarantee is structural: the target has no foreground to steal
        because it is not on the input desktop. That is also its cost --
        nobody can see or interact with it, so a target needing interactive
        login cannot use this without a SwitchDesktop that takes over the
        operator\'s screen, which this does not do.
        """
        grant = self.sessions.launch_grant_for(command)
        if grant is None:
            return {
                "ok": False,
                "needs_consent": True,
                "error": {
                    "kind": ErrorKind.DENIED_BY_POLICY.value,
                    "message": (
                        "launching a process is not automatic: the operator "
                        "must approve this exact command first. Ask them, "
                        "then record it with grant_launch."
                    ),
                },
                "command": list(command),
            }
        if not grant.allowed:
            return _error(ErrorKind.DENIED_BY_POLICY,
                          f"the operator declined to launch {command!r}"
                          + (f" ({grant.note})" if grant.note else ""))

        from ..backends import current
        HiddenDesktop = current().HiddenDesktop

        desktop = HiddenDesktop(name=f"ghostdriver-{uuid.uuid4().hex[:8]}")
        try:
            desktop.prepare()
            pid = desktop.launch(list(command), announces_pid=announces_pid)
        except OSError as exc:
            desktop.teardown()
            return _error(ErrorKind.DENIED_BY_ENVIRONMENT,
                          f"could not launch on a hidden desktop: {exc}")

        # The launch is the consent: a pid grant is recorded from it so the
        # per-call gate authorizes this session like any other, without a
        # second question about a target the operator just asked to start.
        from ..policy import ConsentSource

        self.sessions.record_grant(
            pid, allowed=True, source=ConsentSource.ELICITED,
            note=f"launched on a hidden desktop by operator request: {command!r}",
        )
        try:
            session = self.sessions.attach(
                pid, command_line=list(command), tier=Tier(tier),
                runner=desktop.run,
            )
        except (GhostdriverError, ValueError) as exc:
            desktop.teardown()
            kind = getattr(exc, "kind", ErrorKind.DENIED_BY_POLICY)
            return _error(kind, str(getattr(exc, "message", exc)))

        self._desktops[session.session_id] = desktop
        summary = session.summary()
        summary["ok"] = True
        summary["isolation"] = "hidden_desktop"
        summary["launched_pid"] = pid
        summary["note"] = (
            "launched on a hidden desktop; it is invisible to you and cannot "
            "take your foreground. Release the session to close it."
        )
        return summary
