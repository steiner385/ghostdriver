# Sourced by the nested-display probes, never run on its own (#217).
#
# GNOME 50 removed `gnome-shell --x11`, so a nested display is no longer an
# Xvfb with gnome-shell on it: it is a headless `gnome-shell --wayland` whose
# own Xwayland hosts the target as an X client -- still mutter, so the same
# window manager answers `_NET_CLIENT_LIST`, `_NET_ACTIVE_WINDOW` and iconify.
# `HiddenDesktop` does the same in Python; this is that recipe for the shell
# probes, which predate it.
#
# Call from inside `dbus-run-session`, with `XDG_RUNTIME_DIR` set to a
# private directory (tests/linux_nested_shell.py builds that environment):
# the shell's sockets and the accessibility bus land there.

gd_start_nested_shell() {
  local log="$XDG_RUNTIME_DIR/gnome-shell.log" n="" i
  gnome-shell --headless --wayland --virtual-monitor 1280x800 \
    --wayland-display "gd-nested-$$" >/dev/null 2>"$log" &
  GD_SHELL_PID=$!
  for i in $(seq 1 100); do
    n=$(grep -o 'Using public X11 display :[0-9]*' "$log" 2>/dev/null | grep -o ':[0-9]*$' | head -1)
    if [ -n "$n" ] && ls "$XDG_RUNTIME_DIR"/.mutter-Xwaylandauth.* >/dev/null 2>&1; then
      break
    fi
    sleep 0.1
  done
  if [ -z "$n" ]; then
    echo "the nested gnome-shell announced no Xwayland display; its log ends:" >&2
    tail -5 "$log" >&2
    return 1
  fi
  XAUTHORITY=$(ls "$XDG_RUNTIME_DIR"/.mutter-Xwaylandauth.* | head -1)
  export DISPLAY="$n" XAUTHORITY XDG_SESSION_TYPE=x11 GDK_BACKEND=x11 QT_QPA_PLATFORM=xcb
  unset WAYLAND_DISPLAY
  for i in $(seq 1 30); do
    xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -q 0x && return 0
    sleep 1
  done
  echo "the nested gnome-shell never managed its Xwayland" >&2
  return 1
}
