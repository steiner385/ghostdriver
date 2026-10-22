"""Session lifecycle: listing targets, consent, attach, isolated launch, release."""


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
)
from .live import _LiveCore
from .profiles import profile_names, profile_offer, server_generation


class LifecycleTools(_LiveCore):
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
            name, name_extra = self._named_target(pid, process.info["name"])
            targets.append({
                "pid": pid,
                "name": name,
                **name_extra,
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
            "server_generation": server_generation(),
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

        Session-scoped and revisable; restricting a target with an open
        session stops it at its next call (D64).
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
        allowed = sorted(g.pid for g in grants if g.allowed)
        restricted = sorted(g.pid for g in grants if not g.allowed)
        out = {
            "ok": True,
            # what changed, in full; standing totals as counts (D73)
            "recorded": [g.describe() for g in recorded],
            "allowed_count": len(allowed),
            "restricted_count": len(restricted),
            **({"restricted": restricted} if restricted else {}),
        }
        if stopped:
            out["open_sessions_stopped"] = stopped
            out["caution"] = (
                f"session(s) {', '.join(stopped)} were open against a target "
                "just restricted and will refuse now -- possibly another chat's "
                "work, since one server serves several chats. Restrict only what "
                "the operator ruled out; allow=[pid] reverses this."
            )
        return out

    def attach(
        self,
        pid: int,
        *,
        tier: str = "read_only",
        profile_path: str | None = None,
        isolation: str = "none",
        clipboard: bool = False,
        live: bool = False,
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

        # The tier is validated up front, because the live-actuation check
        # below reads it -- an unknown tier is a clear refusal, not an
        # uncaught ValueError from inside that check.
        try:
            tier_value = Tier(tier)
        except ValueError:
            return _error(ErrorKind.DENIED_BY_POLICY,
                          f"unknown tier {tier!r}; "
                          f"expected one of {[t.value for t in Tier]}")

        # The operator-present live-actuation consent (D#111), resolved
        # before the session opens: a live window that is not the foreground
        # now is a refusal, not a session that quietly cannot commit.
        live_window, live_error = self._live_window_or_error(pid, tier_value, live)
        if live_error is not None:
            return live_error

        missing = _missing_profile(profile_path)
        if missing is not None:
            return missing
        try:
            profile = (
                Profile.load(profile_location(profile_path)) if profile_path
                else Profile.none()
            )
            session = self.sessions.attach(
                pid,
                command_line=command_line,
                tier=tier_value, profile=profile, clipboard=clipboard,
                live_window=live_window,
            )
        except ConsentRequired as exc:
            endpoints = extract_endpoints(command_line)
            from ..consent import StandingApprovals

            image = StandingApprovals.executable(pid)
            return {
                "ok": False,
                "error": {"kind": exc.kind.value, "message": exc.message},
                # Everything needed to put the question to a person, so the
                # caller does not have to go and gather it.
                "needs_consent": True,
                # What the approval will actually be worth, so an agent
                # relaying the question in chat relays the same lifetime the
                # elicitation prompt would have shown (#62).
                "lifetime": self.sessions.consent_lifetime(),
                "target": {
                    "pid": pid,
                    "name": name,
                    "endpoints": [e.normalized for e in endpoints],
                    "summary": describe_target(name, pid, endpoints),
                    # The image, spelled the way the process reports it: the
                    # string an operator has to copy to declare a standing
                    # approval (D#125), which is not always the one they
                    # would have guessed.
                    **({"exe": image} if image else {}),
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
        summary["server_generation"] = server_generation()
        if not profile_path:
            # Offered, never applied (#242): a profile carries policy.
            summary.update(profile_offer(command_line[0] if command_line else None))
        summary["isolation"] = strategy.value
        summary["clipboard"] = session.clipboard  # may this session write it? (D70)
        if strategy is Isolation.MINIMIZED:
            from ..backends import current
            MinimizedWatch = current().MinimizedWatch
            WatchError = current().WatchError

            watch = MinimizedWatch(pid, family=lambda: self._tree_pids(session))
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
            # Report what it saw; leave the window minimized (un-minimizing
            # activates it -- see MinimizedWatch.stop). They click the taskbar.
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


def _missing_profile(profile_path: str | None) -> dict | None:
    """A bare profile name that is not in the operator directory, refused
    with the names that are (#242), instead of a file-not-found."""
    import os

    if not profile_path or os.sep in profile_path or "/" in profile_path \
            or profile_path.endswith(".json"):
        return None
    if os.path.exists(profile_location(profile_path)):
        return None
    names = profile_names()
    return _error(
        ErrorKind.NOT_FOUND,
        f"no profile named {profile_path!r} in the operator directory; "
        + (f"it has: {', '.join(names)}" if names else "it has none"))
