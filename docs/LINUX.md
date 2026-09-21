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
| `enumerate_process`, `top_level_windows` | `EnumWindows` / `EnumChildWindows`, per pid | AT-SPI2 over D-Bus: the application's accessible tree, rooted at the desktop; X11 window ids via `_NET_CLIENT_LIST` and, since a sandboxed target's windows carry no `_NET_WM_PID`, the **XRes** extension or title+size correlation (D#101) | D3, D40 (main-window selection by visible nodes) |
| `application_name` | the process's own name is the application | the accessibility bus's name for the target, when it differs from the process name -- a Flatpak's a11y pid is its `xdg-dbus-proxy`'s, so `psutil` says `xdg-dbus-proxy` where the bus says `bambu-studio` (D#101, D#110); None when they agree | D#101, D#110 |
| `process_facts`, `descendants`, `parent_map` | `CreateToolhelp32Snapshot`, `IsWow64Process`, DPI awareness | `/proc/<pid>` (exe, cmdline, maps for toolkit detection: libgtk, libQt, libwx, Electron) | D2 (toolkit inference from loaded modules) |
| `read_window_text` | `SendMessageTimeout(WM_GETTEXT)` | AT-SPI `Text` interface, or `Name` for controls without one; timeout per call because a hung application hangs the bus call | D4 (the unresponsive control), D47 |
| `confirms_value` | read then compare | `protection.confirms`: the read is compared to the expected string and only the yes/no leaves, so a withheld field (D#34b) is matchable by value without disclosure -- the safe half of a place-plus-value locator | D#34b, D#105 |
| `direct_children` | `GetWindow(GW_CHILD/GW_HWNDNEXT)` | AT-SPI child accessibles of a node | D71 (a dialog's controls, read top to bottom) |
| `read_clipboard_text` | `OpenClipboard` / `GetClipboardData(CF_UNICODETEXT)` | **built (D#105a):** `wl-paste` under Wayland, `xclip -o` under X11 (`WAYLAND_DISPLAY` chooses), the same tool the person uses, so the same clipboard -- a choice, not a fallback, since `xclip` under Wayland reaches the wrong clipboard | D65 (a target's own Copy is the one exact read some grids have) |
| `ink_fraction` | `PrintWindow` pixels; the most common colour is the background | the same over the AT-SPI screenshot of the window (`org.gnome.Shell.Screenshot` / `grim -g`) | D66 (a control that answers empty and renders content) |
| `deepest_child_at` | `ChildWindowFromPointEx` | the deepest accessible with a bounding box under the point | D66 (a click goes to the window under the pointer) |
| `snapshot_clipboard`, `restore_clipboard` | every format via `EnumClipboardFormats` / `GetClipboardData` | **built (D#105a):** `wl-paste --list-types` / `wl-copy`, or `xclip -o -t TARGETS` / `xclip -i`, by the same `WAYLAND_DISPLAY` choice as the read; only the text value is put back, non-text targets are named as lost | D70 (the clipboard is the person's; put back whole) |
| `is_protected` | `EM_GETPASSWORDCHAR` | AT-SPI `STATE_PROTECTED`, role `PASSWORD_TEXT` | D33 (constraint 4) |
| `disclosure` | always `allowed` or `protected` -- the OS refuses the read itself, so nothing is withheld in software | `allowed`, `protected` or **`withheld`**: an editable entry is withheld by class, because a hidden one is indistinguishable from a plain one | D#34b, D#43 (the third state gets a name instead of borrowing `None`) |
| `capture_window`, `CaptureError` | `PrintWindow` | `XGetImage` on the window (composited: `XCompositeNameWindowPixmap`); never a screen grab. The window is found through the tree's frame correlation, not by matching a pid (D#101a) | D46 |
| `top_level_state`, `blocking_ancestor` | `IsWindowEnabled` per window, owner chain | `_NET_WM_STATE_MODAL`, `WM_TRANSIENT_FOR`; AT-SPI `STATE_MODAL` on dialogs | D38, D48 (link vs victim) |
| `snapshot`, `surface_of` | window set + foreground + blocked-by | `_NET_ACTIVE_WINDOW`, `_NET_CLIENT_LIST`; surface by toolkit and AT-SPI role | D34 |
| `restore_process` | `SW_SHOWNOACTIVATE` (activates; D55) | `_NET_WM_STATE` remove `HIDDEN` via client message with source indication 1 (application), never 2 (pager) -- **measure whether the window manager focuses it anyway** | D55 |
| `walk_elements_awake`, `is_selected`, `_current_value` | UIA control view; wake by first query | **built (D#104)**: the element view is assembled from the enumeration registry (`tree._Entry`) rather than a second bus walk -- an element carries the node's own handle and its screen extents, so an unnamed field is addressed by position plus value (D#101); `is_selected` re-reads the live state; `_current_value` withholds an editable field (D#34b). **Still no wake step, measured rather than assumed (D#15)**: the working engine's document was complete on the first ask every time, so there was nothing to wake; the other engine never published one at all, which a wake loop would not have fixed | D56, D58, D#104, D#15 |
| `region_evidence`, `resolve_hosted_app` | UIA count under a window; frame-host resolution | AT-SPI subtree count; embedded documents are `ROLE_DOCUMENT_WEB` | D41 |
| `assess_uia`, `assess_msaa` | pattern richness | AT-SPI interface richness (`Action`, `Value`, `Text`, `Selection` counts) | D5 |
| `verbs` | posted `WM_LBUTTONDOWN/UP`, posted `WM_CHAR`, UIA patterns | tier 1: AT-SPI `Action.DoAction` and `EditableText`; there is **no tier 3** (D#11 measured GTK discarding sent events). `set_text` takes a `live_window`: without one it is the tier-1 write alone (display only on wxGTK3, which does not commit; D#102), with one it is a single **tier-4** rung that writes and presses a real Enter, guarded by the live-actuation gate (D#111) | D21, D30, D44, D56, D#11, D#102, D#111 |
| `NAMED_KEYS`, `EDIT_ACTIONS`, `button_pair` | virtual-key table; button messages with modifier flags | X keysym **names** for XTest (`press_key`, tier 4, live only); `button_pair` only *refuses* a right click or a modifier, since an AT-SPI action carries neither and there is no posted pair (D#11); `deepest_child_at` is a no-op -- a control is an accessible, not a window to hit-test | D44, D61, D#11 |
| `copy_route`, `focus_route` | `WM_COPY`, posted `WM_SETFOCUS` | AT-SPI `Action` named "copy", `Component.GrabFocus` -- **measured (D#102): on wxGTK3 it works *and* raises the window to the foreground**, so it is a focus steal, not the harmless focus set D#11 assumed; on GTK4 it raised instead (D#10) | D50, D#102 |
| `MinimizedWatch`, `WatchError` | poll `WS_MINIMIZE` + foreground; `SW_SHOWMINNOACTIVE` | poll `_NET_WM_STATE_HIDDEN` + `_NET_ACTIVE_WINDOW`; iconify via `XIconifyWindow` (does not focus) | D49, D55 |
| `HiddenDesktop` | `CreateDesktopW` + thread binding | a nested `Xvfb` with its own `DISPLAY`, its own private D-Bus session bus, and its own AT-SPI bus (`at-spi-bus-launcher`) and window manager (`gnome-shell --x11`); launch-only, as on Windows. **Corrected (D#40f): "no thread binding needed" was half right** -- Xlib needs none, but AT-SPI is a process-wide singleton with no route to a second bus, measured against fork, a second `Atspi.init()`, and `Atspi.exit()` then reconnect, none of which worked; `run` claims the process (`desktop_claim.py`) rather than binding a context to it | D51, D52, D53, D#40f |
| `InterferenceWatch` | foreground pid + cursor | `_NET_ACTIVE_WINDOW` owner + `XQueryPointer` | D57 |
| `OperatorNotice` | a topmost, no-activate popup window | built (#40 slice 5b): an override-redirect X window with `_NET_WM_STATE_ABOVE`, drawn with the server's `fixed` font rather than a toolkit; override-redirect means no WM decision is involved in "never focused" at all. Wayland (a layer-shell surface or `org.freedesktop.Notifications`) is unmeasured | D61, D#40f |
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

**Sandboxed applications.** The model above -- "a Flatpak reaches the
AT-SPI bus only with `--talk-name=org.a11y.Bus`, otherwise it is a target
the strategy cannot fit (D53)" -- **was wrong for the commonest case, and
D#101 corrects it.** A GTK Flatpak is on the a11y bus by default: the
runtime injects `GTK_MODULES=gail:atk-bridge` and
`AT_SPI_BUS_ADDRESS=unix:path=/run/flatpak/at-spi-bus`, and an
`xdg-dbus-proxy` brokers the bus in. Bambu Studio, whose permissions name
no a11y talk-name, enumerates fully. What the sandbox *does* cost is
identity: the pid AT-SPI reports (`get_process_id`) is the **proxy's**, not
the application's, and the X windows carry **no `_NET_WM_PID`** at all, so
the pid a window belongs to has to come from the XRes extension
(`Xlib.ext.res`) or from title+`WM_CLASS`. Three identifier spaces, none of
them the pid a caller holds; see D#101.

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
   nothing else can be measured. This is also `HiddenDesktop`, built in
   #40 slice 5b as `backends/linux/hidden_desktop.py`.
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
   **Done (D#15), and the answer splits by WebKitGTK binding.** No
   Chromium engine was available to measure; WebKitGTK stood in, and its
   two GTK bindings disagreed. The GTK4 one (`WebKit` 6.0) never published
   a document over AT-SPI at all -- not once, across a dozen runs and
   sixty-second waits, load-complete or not. The GTK3 one (`webkit2gtk-4.1`)
   did, immediately: the document was already complete the first time
   anything asked, every time, so `walk_elements_awake` needed no wake
   step to add. The click and the password-field detection needed no
   web-specific code either -- `Action.DoAction` and role-based state
   reads already worked. The one real gap: a web `<input>` carries no
   `EditableText` and no `Value` at all, unlike a native GTK entry (D#10),
   so there is no tier-1 write route to one; typing would need tier 4.
   D75's "GTK 3 is not available from PyGObject here" does not hold on
   this host -- it is available -- so that was a measurement of one
   machine, not a fixed platform constraint.

Each measurement is a test in `tests/test_linux_*.py`, skipped where
`sys.platform != "linux"`, and each records its number in the decision
log the way the Windows ones did.

## How to build it on a Windows machine

WSL2 with a distribution, `Xvfb`, `at-spi2-core`, `python3-gi` and
`gir1.2-gtk-3.0` are enough for every measurement above; no Linux GUI
session is needed. Installing WSL is a system change this tool will not
make on the operator's behalf; it is the one prerequisite this document
cannot supply.
