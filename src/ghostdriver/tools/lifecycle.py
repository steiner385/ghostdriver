"""Session lifecycle: listing targets, consent, attach, isolated launch, release."""

import uuid

from ..hosting import classify_process, hosted_frame_note, is_frame_host
from ..isolation import Isolation
from ..model.result import ErrorKind, GhostdriverError
from ..operator import profile_location
from ..policy import (
    ConsentSource,
    Tier,
    describe_target,
    extract_endpoints,
)
from ..session import ConsentRequired, Profile
from .core import (
    MAX_ELEMENTS,
    _error,
    _ToolboxCore,
)


class LifecycleTools(_ToolboxCore):
    """Finding targets, consenting to them, attaching, launching and releasing."""

    def list_targets(self) -> dict:
        """Every process that owns windows, and what it is connected to.

        The endpoint is here because this is the list a person is shown when
        deciding which targets to allow. "the client" is not enough to
        answer with; "the client, connected to the dev gateway" is.
        """
        import psutil

        from ..backends import current
        winapi = current().winapi
        from ..backends import current
        top_level_windows = current().top_level_windows

        attached = {s.pid: s.session_id for s in self.sessions.open_sessions()}
        # One process snapshot for every consent lookup in this listing: a
        # per-process parent walk over a hundred candidates was seconds.
        try:
            parents = current().parent_map()
        except Exception:
            parents = {}
        targets = []
        for process in psutil.process_iter(["pid", "name"]):
            pid = process.info["pid"]
            try:
                windows = top_level_windows(pid)
            except OSError:
                continue
            if not windows:
                continue
            try:
                endpoints = extract_endpoints(psutil.Process(pid).cmdline())
            except (psutil.Error, OSError):
                endpoints = []
            grant = self.sessions.grant_for(pid, parent_of=parents.get)
            # Whether this process owns windows for other applications, or
            # is an application whose frame something else owns. Cheap: the
            # top-level class names alone decide it.
            kind, note = classify_process(
                [winapi.class_name(h) for h in windows]
            )
            targets.append({
                "pid": pid,
                "name": process.info["name"],
                "top_level_windows": len(windows),
                "endpoints": [e.normalized for e in endpoints],
                "summary": describe_target(
                    process.info["name"], pid, endpoints
                ),
                "consent": (
                    None if grant is None
                    else ("allowed" if grant.allowed else "restricted")
                ),
                "window_ownership": kind,
                "hosting_note": note,
                "session_id": attached.get(pid),
            })
        targets.sort(key=lambda t: -t["top_level_windows"])
        return {
            "ok": True,
            "targets": targets[:MAX_ELEMENTS],
            "total": len(targets),
            "note": (
                "No target may be automated until the operator approves it "
                "for this session. Show them the candidates and ask which "
                "to allow and which to leave alone."
            ),
        }

    def grant_targets(
        self,
        allow: list[int] | None = None,
        restrict: list[int] | None = None,
        *,
        note: str = "",
        source: ConsentSource = ConsentSource.OPERATOR_TOOL,
    ) -> dict:
        """Record which targets the operator approved or ruled out.

        Session-scoped and revisable: a later decision replaces an earlier one.
        Restricting a target that already has an open session takes effect
        immediately -- the next call on that session refuses (D64 says why).
        """
        recorded = []
        stopped: list[str] = []
        for pid in allow or []:
            recorded.append(self.sessions.record_grant(
                pid, allowed=True, source=source, note=note))
        for pid in restrict or []:
            recorded.append(self.sessions.record_grant(
                pid, allowed=False, source=source, note=note))
            stopped.extend(s.session_id for s in self.sessions.open_sessions()
                           if s.pid == pid)
        if not recorded:
            return _error(
                ErrorKind.NOT_ACTIONABLE,
                "nothing to record: pass allow=[...] or restrict=[...]",
            )
        grants = self.sessions.grants()
        out = {
            "ok": True,
            "recorded": [g.describe() for g in recorded],
            "allowed": sorted(g.pid for g in grants if g.allowed),
            "restricted": sorted(g.pid for g in grants if not g.allowed),
        }
        if stopped:
            out["open_sessions_stopped"] = stopped
            out["caution"] = (
                f"session(s) {', '.join(stopped)} were open against a target "
                "just restricted and will refuse from now on -- possibly "
                "another chat's work, since one server can serve several "
                "chats at once. Restrict only a target the operator ruled "
                "out: a target nobody allowed is never automated, so leaving "
                "one alone needs no record. allow=[pid] reverses this."
            )
        return out

    def attach(
        self,
        pid: int,
        *,
        tier: str = "read_only",
        profile_path: str | None = None,
        isolation: str = "none",
    ) -> dict:
        """Open a session against a target the operator has approved.

        When nobody has decided about this target yet, the result says so
        and carries what a person needs to be asked -- which application,
        and where it is pointed. That is a question, not a failure.

        `isolation="minimized"` keeps the target minimized for the life of
        the session: it is put away now without activating anything else,
        a watchdog re-minimizes it if a window of it comes on screen, and
        every such escape is captured and reported on the next result as
        `watchdog_events` -- because a background application that shows
        a window is almost always raising a modal, and that is the
        information (D49). The strategy fits a target that is already
        running and needed a person to sign in, which a hidden desktop
        cannot host. Its costs: `restore` is refused while it runs; a
        capture of the minimized window itself is not available (what the
        watchdog photographs is the window that escaped); and at release
        the window stays minimized, because no way of un-minimizing it
        leaves the operator's focus alone.
        """
        import psutil

        try:
            strategy = Isolation(isolation)
        except ValueError:
            return _error(ErrorKind.NOT_ACTIONABLE,
                          f"unknown isolation {isolation!r}; expected one of "
                          f"{[i.value for i in Isolation]}")

        try:
            process = psutil.Process(pid)
            command_line = process.cmdline()
            name = process.name()
        except (psutil.Error, OSError) as exc:
            return _error(ErrorKind.NOT_FOUND, f"cannot read pid {pid}: {exc}")

        try:
            profile = (
                Profile.load(profile_location(profile_path)) if profile_path
                else Profile.none()
            )
            session = self.sessions.attach(
                pid,
                command_line=command_line,
                tier=Tier(tier),
                profile=profile,
            )
        except ConsentRequired as exc:
            endpoints = extract_endpoints(command_line)
            return {
                "ok": False,
                "error": {"kind": exc.kind.value, "message": exc.message},
                # Everything needed to put the question to a person, so the
                # caller does not have to go and gather it.
                "needs_consent": True,
                "target": {
                    "pid": pid,
                    "name": name,
                    "endpoints": [e.normalized for e in endpoints],
                    "summary": describe_target(name, pid, endpoints),
                },
            }
        except GhostdriverError as exc:
            return _error(exc.kind, exc.message)
        except ValueError:
            return _error(ErrorKind.DENIED_BY_POLICY,
                          f"unknown tier {tier!r}; "
                          f"expected one of {[t.value for t in Tier]}")

        summary = session.summary()
        summary["ok"] = True
        summary["isolation"] = strategy.value
        if strategy is Isolation.MINIMIZED:
            from ..backends import current
            MinimizedWatch = current().MinimizedWatch
            WatchError = current().WatchError

            watch = MinimizedWatch(pid)
            try:
                session.run(watch.start)
            except WatchError as exc:
                self.sessions.release(session.session_id)
                return _error(ErrorKind.NOT_ACTIONABLE,
                              f"cannot keep pid {pid} minimized: {exc}")
            self._watches[session.session_id] = watch
            summary["note"] = (
                "kept minimized for this session; if a window of it comes on "
                "screen it is photographed, put back, and reported on the "
                "next result as watchdog_events. It stays minimized after "
                "release; the operator un-minimizes it from the taskbar."
            )
        # Said at attach, not left for the caller to discover from a
        # profile that quietly describes a title bar. Judged on the window
        # this session will actually read, not on the process, and it names
        # the application inside so the caller gets a pid to attach to.
        selected = self._trees(session, all_windows=False)
        if selected and is_frame_host(selected[0].class_name):
            from ..backends import current
            resolve_hosted_app = current().resolve_hosted_app

            found = resolve_hosted_app(selected[0].handle, session.pid)
            app_name = ""
            if found is not None:
                try:
                    app_name = psutil.Process(found.pid).name()
                except (psutil.Error, OSError):
                    app_name = ""
            summary["window_ownership"] = "measured-a-frame"
            summary["hosting_note"] = hosted_frame_note(
                found.pid if found else None, app_name,
                found.share if found else 0.0,
            )
            if found is not None:
                summary["hosted_application_pid"] = found.pid
        # Said at attach because it changes what every later call means: a
        # target with nothing on screen answers every read with nothing.
        summary["blocked"] = self._blocking(session)
        if summary["blocked"]:
            from .guidance import BLOCKED_HINT
            summary["blocked_hint"] = BLOCKED_HINT
        # Said at attach, because every read of a minimized target answers
        # about a window nobody can see, and the caller would otherwise
        # infer it from visible=false.
        from ..backends import current as _backend

        # A minimized window still carries WS_VISIBLE, so ask both.
        if selected and (not selected[0].visible
                         or session.run(lambda: _backend().winapi.is_minimized(selected[0].handle))):
            summary["minimized_or_hidden"] = True
            summary["hint"] = (
                "the main window is not on screen (minimized or hidden). "
                "`restore` brings it back -- and may bring it to the front."
            )
        return summary

    def release(self, session_id: str) -> dict:
        self.sessions.release(session_id)
        result: dict = {"ok": True, "released": session_id}
        watch = self._watches.pop(session_id, None)
        if watch is not None:
            # Anything it saw since the last call is still worth reporting.
            # The window stays minimized: every way of un-minimizing it
            # activates it (see MinimizedWatch.stop), and taking the
            # operator's focus at release would break the promise the
            # strategy exists to keep. They click the taskbar when ready.
            events = watch.drain()
            if events:
                result["watchdog_events"] = events
            watch.stop()
            result["left_minimized"] = True
            result["minimized_by_this_session"] = watch.put_away
            result["note"] = (
                "the target is still minimized"
                + (" (this session minimized it)" if watch.put_away else "")
                + "; un-minimizing it from here would bring it to the front, "
                "so that is left to you -- click it in the taskbar."
            )
        desktop = self._desktops.pop(session_id, None)
        if desktop is not None:
            # Its target was launched onto a hidden desktop and is invisible;
            # a stranded process there is especially easy to leak, so
            # teardown terminates it and closes the desktop.
            desktop.teardown()
        return result

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
