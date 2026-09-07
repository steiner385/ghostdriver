# The Linux backend: a specification, and the measurements that come first

Status: specified, not built -- but no longer unmeasured. The package
`ghostdriver.backends.linux` answers every contract name with a refusal that
points here. **D75 contradicted two things below**; the affected rows are
marked rather than rewritten, so the model and the measurement stay visible
side by side. This
document exists because the Windows backend was built by measurement --
every corner of it that mattered was a measurement contradicting a model
(D21, D47, D49, D55, D56, D58) -- and the Linux one will be too. What
follows is the model, stated so it can be contradicted.

It was written on a machine with no Linux desktop. Nothing in it has been
run.

## What the backend has to provide

The contract is the tuple in `ghostdriver/backends/__init__.py`. Every
name maps to a Windows mechanism whose behaviour is recorded in the
decision log; the table says what each becomes on Linux and which
decision holds the measurement the Linux one must repeat.

| Contract name | Windows mechanism | Linux mechanism (proposed) | Measure against |
|---|---|---|---|
| `enumerate_process`, `top_level_windows` | `EnumWindows` / `EnumChildWindows`, per pid | AT-SPI2 over D-Bus: the application's accessible tree, rooted at the desktop; X11 window ids via `_NET_CLIENT_LIST` + `_NET_WM_PID` where a window is needed | D3, D40 (main-window selection by visible nodes) |
| `process_facts`, `descendants`, `parent_map` | `CreateToolhelp32Snapshot`, `IsWow64Process`, DPI awareness | `/proc/<pid>` (exe, cmdline, maps for toolkit detection: libgtk, libQt, libwx, Electron) | D2 (toolkit inference from loaded modules) |
| `read_window_text` | `SendMessageTimeout(WM_GETTEXT)` | AT-SPI `Text` interface, or `Name` for controls without one; timeout per call because a hung application hangs the bus call | D4 (the unresponsive control), D47 |
| `direct_children` | `GetWindow(GW_CHILD/GW_HWNDNEXT)` | AT-SPI child accessibles of a node | D71 (a dialog's controls, read top to bottom) |
| `read_clipboard_text` | `OpenClipboard` / `GetClipboardData(CF_UNICODETEXT)` | `wl-paste` / `xclip -o`: the same tool the person uses, so the same clipboard | D65 (a target's own Copy is the one exact read some grids have) |
| `ink_fraction` | `PrintWindow` pixels; the most common colour is the background | the same over the AT-SPI screenshot of the window (`org.gnome.Shell.Screenshot` / `grim -g`) | D66 (a control that answers empty and renders content) |
| `deepest_child_at` | `ChildWindowFromPointEx` | the deepest accessible with a bounding box under the point | D66 (a click goes to the window under the pointer) |
| `snapshot_clipboard`, `restore_clipboard` | every format via `EnumClipboardFormats` / `GetClipboardData` | `wl-paste --list-types` and one `wl-paste -t` per type; `wl-copy` back | D70 (the clipboard is the person's; put back whole) |
| `is_protected` | `EM_GETPASSWORDCHAR` | AT-SPI `STATE_PROTECTED`, role `PASSWORD_TEXT` | D33 (constraint 4) |
| `capture_window`, `CaptureError` | `PrintWindow` | `XGetImage` on the window (composited: `XCompositeNameWindowPixmap`); never a screen grab | D46 |
| `top_level_state`, `blocking_ancestor` | `IsWindowEnabled` per window, owner chain | `_NET_WM_STATE_MODAL`, `WM_TRANSIENT_FOR`; AT-SPI `STATE_MODAL` on dialogs | D38, D48 (link vs victim) |
| `snapshot`, `surface_of` | window set + foreground + blocked-by | `_NET_ACTIVE_WINDOW`, `_NET_CLIENT_LIST`; surface by toolkit and AT-SPI role | D34 |
| `restore_process` | `SW_SHOWNOACTIVATE` (activates; D55) | `_NET_WM_STATE` remove `HIDDEN` via client message with source indication 1 (application), never 2 (pager) -- **measure whether the window manager focuses it anyway** | D55 |
| `walk_elements_awake`, `is_selected`, `_current_value` | UIA control view; wake by first query | AT-SPI is always live for toolkits that register; a Chromium engine again wakes on first query (`org.a11y.Status IsEnabled` must be set) | D56, D58 |
| `region_evidence`, `resolve_hosted_app` | UIA count under a window; frame-host resolution | AT-SPI subtree count; embedded documents are `ROLE_DOCUMENT_WEB` | D41 |
| `assess_uia`, `assess_msaa` | pattern richness | AT-SPI interface richness (`Action`, `Value`, `Text`, `Selection` counts) | D5 |
| `verbs` | posted `WM_LBUTTONDOWN/UP`, posted `WM_CHAR`, UIA patterns | tier 1: AT-SPI `Action.DoAction`; tier 3: `XSendEvent` of `ButtonPress/Release` and `KeyPress/Release` **to the window**, which toolkits may ignore as synthetic (the `send_event` flag) -- this is the measurement that decides whether a Linux tier 3 exists at all | D21, D30, D44, D56 |
| `NAMED_KEYS`, `EDIT_ACTIONS`, `button_pair` | virtual-key table; button messages with modifier flags | X keysyms via `XStringToKeysym`; `ButtonPress` with `state` modifier mask | D44, D61 |
| `copy_route`, `focus_route` | `WM_COPY`, posted `WM_SETFOCUS` | AT-SPI `Action` named "copy", `Component.GrabFocus` (which may raise the window: measure) | D50 |
| `MinimizedWatch`, `WatchError` | poll `WS_MINIMIZE` + foreground; `SW_SHOWMINNOACTIVE` | poll `_NET_WM_STATE_HIDDEN` + `_NET_ACTIVE_WINDOW`; iconify via `XIconifyWindow` (does not focus) | D49, D55 |
| `HiddenDesktop` | `CreateDesktopW` + thread binding | a nested X server (`Xephyr` or `Xvfb`) with its own `DISPLAY` and its own AT-SPI bus (`at-spi-bus-launcher` per display); launch-only, as on Windows; **no thread binding needed** -- the display is an environment variable | D51, D52, D53 |
| `InterferenceWatch` | foreground pid + cursor | `_NET_ACTIVE_WINDOW` owner + `XQueryPointer` | D57 |
| `OperatorNotice` | a topmost, no-activate popup window | an override-redirect X window with `_NET_WM_STATE_ABOVE`, never focused (`WM_HINTS` input False); under Wayland a layer-shell surface or a desktop notification (`org.freedesktop.Notifications`) | D61 |
| `winapi` | raw Win32 | a small `x11` module: the handful of Xlib and EWMH calls above | -- |

## What is the same

Everything above the backend: locators (window and element forms),
resolution, the tier ladder and its rules, cadence, disturbances,
sensitivity notes, the ledger, consent and tiers, the operator directory,
workflows, the watchdog policy, the modality rule, the surface model. The
Linux backend produces `WindowNode`s and `AccessibleElement`s and the
rest reads them unchanged. That is what the boundary is for.

## What is different enough to need its own decision

**Wayland.** Under a Wayland compositor there is no global window list,
no way to send input to a window that does not have focus, and no
`XSendEvent`. AT-SPI still works (it is D-Bus, not the display), so tier 1
exists; tier 3 does not, unless the target runs under XWayland. The
structural isolation guarantee also changes shape: a nested compositor
(`cage`, `weston --backend=headless`) instead of a nested X server. The
first Linux backend should target X11 and say so, and measure the
XWayland case before claiming anything about Wayland.

**Sandboxed applications.** A Flatpak or Snap application reaches the
AT-SPI bus only if its sandbox allows it (the `--talk-name=org.a11y.Bus`
permission). Its analogue on Windows is the Store-activated application
(D53): a target the strategy cannot fit, reported as such, not worked
around.

**The synthetic-event flag.** `XSendEvent` marks the event as sent, and
GTK and Qt can be built or configured to ignore such events. Whether the
common toolkits honour a sent `ButtonPress` to a specific window is *the*
measurement for tier 3; if they do not, the fallback is `XTest`, which
injects into the real input stream and therefore needs the target to have
focus -- which is tier 4, excluded by default (D9), and which under the
nested-server strategy is acceptable because the nested server's input is
not the operator's.

**MPX.** X input has multiple master devices; a second master pointer and
keyboard could drive the target on the operator's own display without
touching the operator's devices. It is the one Linux capability with no
Windows counterpart, and the reason the plan names it. Measure it after
the nested-server strategy works, not before: the nested server is
simpler and structurally guaranteed.

## The fixture

`tests/fixtureapp.py` is a Win32 application built to be hostile in the
ways the primary target is. The Linux one should be a GTK application
(PyGObject; GTK ships on every desktop) with the same shapes:

- a button that is a custom-drawn `DrawingArea`, not a `Button`, reacting
  only to the button-press pair (D21's "a button that is not a BUTTON");
- a bound entry whose committed value is mirrored on `focus-out`, so a
  value set without the toolkit's input path shows the split;
- a password entry (`visibility=False`), which must read as protected;
- two stacked pages with identically labelled buttons (D31's `within=`);
- a modal dialog raised on a timer, and a foreground grab on a timer
  (`gtk_window_present`), both opt-in;
- a notebook (tabs) and a toolbar of icon-only buttons, for the element
  form (D56);
- a drawing-area grid with no children that answers a copy action (D50).

It announces its pid and its X window ids on stdout as JSON, like the
Windows one, and never presents its window (`gtk_window_present` is what
a foreground grab *is*).

## The measurements, in the order they unblock things

0. **The fixture itself.** Built: `tests/fixtureapp_gtk.py`, GTK 4 (GTK 3 is
   not available from PyGObject here, which costs `Gtk.Toolbar` -- see D75).
   `tests/test_linux_fixture.py` stands it up on a nested display and passes.
1. **A nested X server with an AT-SPI bus.** `Xvfb :99`, `DISPLAY=:99
   at-spi-bus-launcher --launch-immediately`, the fixture on it, and
   `pyatspi` (or raw D-Bus) listing the fixture's tree. Until this works
   nothing else can be measured. This is also `HiddenDesktop`.
   **Correction (D75): it also needs a window manager**, and one runs --
   `gnome-shell --x11` under its own `dbus-run-session` (D#11), which
   unblocks measurements 6 and 7. A bare `Xvfb` sets
   neither `_NET_CLIENT_LIST` nor `_NET_ACTIVE_WINDOW` -- both come from a
   WM, not the X server -- so measurements 6 and 7 cannot be asked without
   one, and enumeration must walk the tree instead.
   **Correction (D#8): and a session bus of its own.** AT-SPI is discovered
   through the D-Bus *session* bus, so a nested display sharing the
   operator's finds the operator's a11y bus and enumerates the operator's
   applications. `dbus-run-session` is what makes this an isolation strategy
   rather than a convenience. Done: `tests/test_linux_atspi.py`, which
   asserts the nested bus holds exactly the fixture. The bindings are
   `Atspi 2.0` via GObject introspection -- a third route beside the
   "pyatspi (or raw D-Bus)" named above.
2. **Reading.** Names, roles, states, text of every fixture control;
   which controls answer `Text` and which only `Name`; what an unresponsive
   control does to a bus call (D4) and what timeout is right.
   **Done (D#34a, D#9).** Entries answer `Text`, buttons do not, and the
   owner-drawn grid answers neither. Two findings the measurement did not
   go looking for: AT-SPI hands out password contents in cleartext and one
   of the two ways to make a password field is undetectable (#34); and
   `Atspi.set_timeout()` does not bound a call at all, so the deadline is
   imposed by the driver instead -- 200ms, the same as Windows'.
3. **Tier 1.** `Action.DoAction` on the real button, the custom-drawn
   button (expected: no action), the entry (`Value` / `EditableText.SetText`
   -- expected: the D21 split on the bound entry).
   **Done (D#10).** First two as expected -- and the owner-drawn control has
   no Action interface at all, so a role is nameable without being drivable.
   The third went the other way: `EditableText` goes through GtkEditable, the
   binding hears the write, and there is **no split**. Tier 1 is stronger
   here than on Windows, so D25's reasoning does not carry over.
4. **Tier 3.** `XSendEvent` `ButtonPress/Release` to the custom-drawn
   button's window: does GTK act on a sent event? This decides whether the
   Windows ladder maps to Linux at all. Then `KeyPress/Release` to the
   entry, and whether the mirror follows.
   **Answered (D#11): no.** Confirmed under GNOME Shell on the nested
   display, with every experiment behind a passing XTest control. The
   provisional version follows; the one row it got wrong -- a sent key to a
   focused window appearing to work -- was an artefact of running without a
   window manager.
   **Provisionally (D75): no.** GTK 4.14.5 routes input by
   the real input state and discards a sent event that does not match it --
   a key to an unfocused window and a button with the pointer elsewhere are
   both ignored, while `XTest` works. Tier 3 does not exist here; the ladder
   is tier 1 then tier 4-under-isolation, which makes the nested server
   mandatory rather than preferred. Re-run with a WM present, and against
   Qt, before treating it as settled.
5. **Modality.** The timer modal: what `_NET_WM_STATE` and AT-SPI say,
   and whether a sent event to the held window is honoured (on Windows a
   posted message is; D48).
   **Done (D#12).** Both layers declare it -- `_NET_WM_STATE_MODAL` and
   AT-SPI `STATE_MODAL`, with `WM_TRANSIENT_FOR` naming the owner. But the
   owner is **not** disabled, so D48's walk-for-a-disabled-ancestor has no
   counterpart: the check inverts to "is anything modal transient-for me",
   and it cannot be answered from the accessibility tree at all. The sent-event
   half needs no measurement -- D#11 found sent events ignored regardless.
6. **The foreground.** `_NET_ACTIVE_WINDOW` before and after every action
   above, on the operator's display, with the target on the nested one:
   it must never change. Then the watchdog: iconify, wait, the timer
   modal, re-iconify, capture.
   **Done (D#13).** It never moves. Two corrections: an iconified window is
   still `IsViewable` under a compositor, so `_NET_WM_STATE_HIDDEN` is the
   signal rather than map state; and an iconified window *can* still be
   captured -- pixel-identical -- which is what makes the minimized strategy
   possible, but that is a property of the compositor rather than of X11 and
   a lighter window manager is unmeasured.
7. **Restore.** Un-hide via `_NET_WM_STATE` and see whether the window
   manager focuses the window (D55 says assume it does until measured).
   **Done (D#14), and stronger than assumed: you cannot un-hide without
   focusing.** A bare map leaves the window hidden; activation restores and
   focuses in one motion, and those are the only two routes a client has --
   `_NET_WM_STATE_HIDDEN` is WM-managed and not client-settable. So D55's
   "nothing ever un-minimizes" is a necessity here rather than a policy: an
   accidental un-hide is an accidental focus steal.
8. **An embedded document.** A Chromium engine on the nested display, the
   wake, the click, the typing -- D58 again.

Each measurement is a test in `tests/test_linux_*.py`, skipped where
`sys.platform != "linux"`, and each records its number in the decision
log the way the Windows ones did.

## How to build it on a Windows machine

WSL2 with a distribution, `Xvfb`, `at-spi2-core`, `python3-gi` and
`gir1.2-gtk-3.0` are enough for every measurement above; no Linux GUI
session is needed. Installing WSL is a system change this tool will not
make on the operator's behalf; it is the one prerequisite this document
cannot supply.
