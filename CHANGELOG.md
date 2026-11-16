# Changelog

Each entry says what changed for someone using the tool. The reasons are in
`docs/DECISIONS.md`, by decision number.

## 0.2.0 — 2026-11-16

The first public release, under the MIT license. Install from the tag:

```bash
pip install "ghostdriver[server] @ https://github.com/steiner385/ghostdriver/archive/refs/tags/v0.2.0.zip"
```

### Packaging

- MIT license; `LICENSE` ships in the wheel and the sdist.
- Project metadata for an index or a tag install: readme, classifiers,
  project URLs. Building needs setuptools 77 or newer (pip fetches it).
- Console scripts are unchanged: `ghostdriver-mcp` (the MCP server, stdio)
  and `ghostdriver` (the CLI). The `server` extra brings the MCP SDK
  (`mcp>=2.1,<3`); the CLI and the library work without it.
- The MCP `initialize` handshake reports the installed version
  (`serverInfo.version`), so a client pinned to a tag can tell which release
  answered. It was an empty string before.

### Windows backend

- A posted click aimed into a child window descends with one coordinate
  conversion, not two (#257).
- A posted click aimed by a rectangle outside its window is refused, instead
  of landing somewhere else (#257).
- `expect {changed: true}` is refused on actions whose effect is text
  (`set_value`, `type`), where a pixel change cannot see the effect (#248).
- `expect {absent: ...}` searches every window unless told not to (#250).
- `find` reports a failed look in other windows instead of raising (#258).
- No UIA pattern call on a Chromium host on the person's desktop (#249).

### Tools

- `list_targets` narrows by process name and by visible windows (#254).
- `attach` dates the approval it acts on and says it sets no tier (#252).
- A delivered action with no visible effect carries a hand-off for a person
  (#244).
- Profiles are offered at `attach`; `find` looks in other windows; a target
  restart is detectable (#242).
- A profile can declare a cadence per control class (#238).
- `describe` marks where depth cut the tree, takes `within`, says how to
  expand a collapsed group, and records how each call fared;
  `ghostdriver trace --scale` reads that back (#210, #227, #230).
- A failed actuation says what it did: a window raised, or nothing at all
  (#194, #195).
- Macros: record, save, replay, parameters, `when`, bounded loops, and
  reactive `on_disturbance` handlers (#84–#112).

### Linux backend

- X11 and AT-SPI wire 38 of the 42 backend contract names. Assessment is
  missing, so `surfaces` and `probe` refuse there (`docs/LINUX.md`).
- Wayland (GNOME): focus and modality read from AT-SPI, so tier-1 actions
  work; the interference watch watches focus and says it cannot watch the
  pointer (#221, #225).
- A hidden desktop on GNOME 50 through a headless gnome-shell (#217).

## 0.1.0

Never tagged. The development line that 0.2.0 releases.
