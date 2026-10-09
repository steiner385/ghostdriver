"""W1-W4 on the operator's own Wayland session, driven: one JSON line.

Runs only when the operator has handed the desktop over (see
tests/test_linux_wayland_live.py, which gates it). It launches two GTK
fixtures -- one a native Wayland client, one an X client of the session's
Xwayland -- and moves focus between them with mutter's own RemoteDesktop
keyboard, so the compositor sees real input. Keys sent: Alt, Tab, Super, H,
Escape. Nothing is ever typed, and Super+H is sent only while a fixture holds
focus, so no application of the operator's is ever minimized.

Measured, per the Wayland plan:
* W1 -- does AT-SPI `STATE_ACTIVE` and `window:activate`/`deactivate` track
  focus, for both kinds of client, and how soon after the input?
* W2 -- what a modal raised by a focused native-Wayland window looks like:
  `STATE_MODAL`, who holds focus, any relation back to the owner.
* W3 -- what a frame's screen extents are on Wayland.
* W4 -- what AT-SPI says about a minimized native-Wayland window.

The X server's `_NET_ACTIVE_WINDOW` is recorded as ground truth for the X
client. Never imported -- `python -m tests.linux_wayland_live_probe`.
"""

import contextlib
import json
import os
import subprocess
import sys
import threading
import time

#: evdev key codes, sent through mutter's RemoteDesktop keyboard.
ALT, TAB, SUPER, H, ESC = 56, 15, 125, 35, 1

#: The fixture's modal timer, from its own start. Long enough for the focus
#: and minimize steps to finish first; the modal step waits for it.
MODAL_AFTER_MS = 40000

#: Helpers that report ACTIVE alongside real windows: the shell's own UI
#: (the Alt+Tab switcher) and mutter's X11 frames client.
HELPERS = ("gnome-shell", "mutter-x11-frames")


def main() -> int:
    # Here, not at module scope: a test-tree module may not bind a platform
    # at import time (test_structure.py).
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi, Gio, GLib

    bus = Gio.bus_get_sync(Gio.BusType.SESSION)

    def rd(path, iface, method, args=None, sig=None):
        return bus.call_sync("org.gnome.Mutter.RemoteDesktop", path, iface, method,
                             args, sig and GLib.VariantType(sig), 0, 5000, None)

    session = rd("/org/gnome/Mutter/RemoteDesktop", "org.gnome.Mutter.RemoteDesktop",
                 "CreateSession", None, "(o)").unpack()[0]
    iface = "org.gnome.Mutter.RemoteDesktop.Session"
    rd(session, iface, "Start")

    def key(code, down):
        rd(session, iface, "NotifyKeyboardKeycode", GLib.Variant("(ub)", (code, down)))

    ctx = GLib.MainContext.default()

    def pump(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            ctx.iteration(False)
            time.sleep(0.01)

    def chord(mod, k):
        key(mod, True)
        pump(0.12)
        key(k, True)
        pump(0.08)
        key(k, False)
        pump(0.12)
        key(mod, False)

    events: list = []

    def on_event(ev):
        try:
            app = ev.source.get_application().get_name()
            pid = ev.source.get_process_id()
        except Exception:
            app, pid = None, None
        events.append((time.monotonic(), ev.type.split(":")[1], app, pid))

    listener = Atspi.EventListener.new(on_event)
    for kind in ("window:activate", "window:deactivate"):
        listener.register(kind)

    def frames(pids):
        """Every frame of the given pids: name, states, extents."""
        out = []
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if app is None:
                continue
            try:
                for j in range(app.get_child_count()):
                    f = app.get_child_at_index(j)
                    if f is None or f.get_process_id() not in pids:
                        continue
                    states = sorted(s.value_nick for s in f.get_state_set().get_states())
                    e = f.get_extents(Atspi.CoordType.SCREEN)
                    rels = [r.get_relation_type().value_nick for r in f.get_relation_set()]
                    out.append({"pid": f.get_process_id(), "name": f.get_name(),
                                "role": f.get_role_name(), "states": states,
                                "extents": [e.x, e.y, e.width, e.height], "relations": rels})
            except Exception:
                continue
        return out

    def active_apps():
        out = []
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            try:
                for j in range(app.get_child_count()):
                    f = app.get_child_at_index(j)
                    if f and f.get_state_set().contains(Atspi.StateType.ACTIVE):
                        out.append([app.get_name(), f.get_process_id()])
            except Exception:
                continue
        return out

    def x_active():
        r = subprocess.run(["xprop", "-root", "_NET_ACTIVE_WINDOW"],
                           capture_output=True, text=True)
        return int(r.stdout.strip().rsplit("# ", 1)[-1], 16) if "#" in r.stdout else 0

    def fixture_active(pids):
        return [p for name, p in active_apps() if p in pids and name not in HELPERS]

    real_pids: list[int] = []
    fixture_events: dict[int, list] = {}

    def launch(backend, *flags):
        env = dict(os.environ, GDK_BACKEND=backend)
        p = subprocess.Popen([sys.executable, "-m", "tests.fixtureapp_gtk", *flags,
                              "--quit-after", "180000"],
                             env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        announced = json.loads(p.stdout.readline())
        real_pids.append(announced["pid"])
        seen = fixture_events.setdefault(announced["pid"], [])

        def read():
            for line in p.stdout:
                with contextlib.suppress(ValueError):
                    seen.append(json.loads(line))
        threading.Thread(target=read, daemon=True).start()
        return announced

    report: dict = {"operator_active_before": active_apps()}
    try:
        wl = launch("wayland", "--modal-after", str(MODAL_AFTER_MS))
        pump(1.5)
        xc = launch("x11")
        pump(2.5)
        pids = {wl["pid"], xc["pid"]}
        report["pids"] = {"wayland": wl["pid"], "x11": xc["pid"], "x11_xid": xc["main"]}
        report["focused_on_map"] = fixture_active(pids)

        # --- W1: focus moves, four times --------------------------------
        switches = []
        for _ in range(4):
            events.clear()
            t = time.monotonic()
            chord(ALT, TAB)
            pump(3)
            switches.append({
                "fixture_active": fixture_active(pids),
                "all_active": active_apps(),
                "x_active": x_active(),
                "events": [(round(e[0] - t, 3), e[1], e[2], e[3]) for e in events],
            })
        report["switches"] = switches

        # --- acting on a native-Wayland target that does NOT hold focus ---
        # The point of #221: through the real tool layer, at tier 1, with
        # another application at the front, the action lands and focus
        # stays where it was.
        for _ in range(3):
            if fixture_active(pids) == [xc["pid"]]:
                break
            chord(ALT, TAB)
            pump(3)
        report["act_front_before"] = fixture_active(pids)
        from ghostdriver.policy import ConsentSource
        from ghostdriver.session import SessionManager
        from ghostdriver.tools import Toolbox
        box = Toolbox(SessionManager())
        box.sessions.record_grant(wl["pid"], allowed=True, source=ConsentSource.ELICITED)
        attached = box.attach(wl["pid"], tier="interactive")
        report["act_attach"] = {k: attached.get(k) for k in ("ok", "error", "blocked")}
        if attached.get("ok"):
            sid = attached["session_id"]
            # What the actuator observes around each action: alive, and the
            # front held by something that is not the target -- so an empty
            # disturbance list below is an observation, not a silent miss.
            from ghostdriver.backends import current
            snap = current().snapshot(wl["pid"])
            report["act_snapshot"] = {"alive": snap.alive, "windows": len(snap.windows),
                                      "foreground": snap.foreground,
                                      "foreground_is_target": snap.foreground in snap.windows}
            before = len(fixture_events[wl["pid"]])
            clicked = box.click(sid, 'text="Save"')
            pump(1)
            report["act_click"] = {
                "ok": clicked.get("ok"), "tier_used": clicked.get("tier_used"),
                "error": clicked.get("error"), "disturbances": clicked.get("disturbances"),
                "fixture_saw": fixture_events[wl["pid"]][before:],
                "front_after": fixture_active(pids)}
            before = len(fixture_events[wl["pid"]])
            typed = box.set_value(sid, 'text="bound entry"', "w221")
            pump(1)
            report["act_set_value"] = {
                "ok": typed.get("ok"), "tier_used": typed.get("tier_used"),
                "error": typed.get("error"), "disturbances": typed.get("disturbances"),
                "fixture_saw": fixture_events[wl["pid"]][before:],
                "front_after": fixture_active(pids)}
            box.release(sid)

        # Bring the Wayland fixture to the front for W2-W4.
        for _ in range(3):
            if fixture_active(pids) == [wl["pid"]]:
                break
            chord(ALT, TAB)
            pump(3)
        report["wayland_focused_for_w234"] = fixture_active(pids) == [wl["pid"]]
        report["w3_frames"] = frames({wl["pid"], xc["pid"]})

        # --- W4: minimize the (fixture's) focused window -----------------
        if report["wayland_focused_for_w234"]:
            events.clear()
            t = time.monotonic()
            chord(SUPER, H)
            pump(3)
            report["w4_minimized"] = {
                "frames": frames({wl["pid"]}), "fixture_active": fixture_active(pids),
                "all_active": active_apps(),
                "events": [(round(e[0] - t, 3), e[1], e[2], e[3]) for e in events]}
            # Back: Alt+Tab to the minimized application restores it.
            for _ in range(3):
                chord(ALT, TAB)
                pump(3)
                if fixture_active(pids) == [wl["pid"]]:
                    break
            report["w4_restored"] = {"frames": frames({wl["pid"]}),
                                     "fixture_active": fixture_active(pids)}

        # --- W2: the modal fires on the focused native-Wayland fixture ---
        started = time.monotonic()
        while time.monotonic() - started < 50:
            pump(0.5)
            if any("modal" in f["states"] for f in frames({wl["pid"]})):
                break
        events.clear()
        pump(2)
        report["w2_modal"] = {"frames": frames({wl["pid"]}),
                              "fixture_active": fixture_active(pids),
                              "events": [(e[1], e[2], e[3]) for e in events]}
    finally:
        key(ESC, True)
        key(ESC, False)
        for pid in real_pids:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
        try:
            rd(session, iface, "Stop")
        except Exception:
            pass
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and any(os.path.exists(f"/proc/{p}") for p in real_pids):
            pump(0.25)
        # The fixture does not always exit on SIGTERM promptly (measured);
        # it must not outlive the run on the operator's desktop.
        for pid in real_pids:
            with contextlib.suppress(OSError):
                os.kill(pid, 9)
        pump(1)
        report["operator_active_after"] = active_apps()
        def alive(pid):
            # A killed child is a zombie until reaped: present, not running.
            try:
                with open(f"/proc/{pid}/stat") as f:
                    return f.read().split(") ", 1)[1][0] != "Z"
            except OSError:
                return False
        report["left_running"] = [p for p in real_pids if alive(p)]
        print(json.dumps(report), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
