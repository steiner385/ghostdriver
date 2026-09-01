# ghostdriver

An MCP server for driving desktop applications — for automated testing and
unattended tasks — without contending with a human working on the same
machine.

## Status

Iteration 1: read-only reconnaissance. A CLI that enumerates a target's
window tree, resolves declarative locators, reads control text, and emits a
capability profile. No actuation. The MCP server arrives in Iteration 2.

See `docs/superpowers/specs/2026-09-01-desktop-automation-mcp-design.md`.

## Why

Most desktop automation assumes UI Automation works. For a large class of
enterprise line-of-business software it does not: applications built on
pre-UIA toolkits expose a tree in which every element is a `Pane` and no
element supports any pattern. Those applications remain drivable through
window messages, and that tier is what this tool implements.

## Install

```bash
pip install -e ".[dev]"
pytest
```

## Use

```bash
ghostdriver list-targets
ghostdriver probe --pid 1234 --out profile.json
ghostdriver describe --pid 1234 --depth 5
ghostdriver find --pid 1234 --locator 'class=VendorButton text="Expand All"'
ghostdriver read --pid 1234 --locator 'class=VendorEdit visible=true'
```

See `docs/VALIDATION.md` for the full validation runbook, including gate-by-
gate pass criteria and the shell form for ancestor-scoped locators.

## What this iteration does not do

- **No actuation of any kind.** Nothing in this iteration clicks, types,
  focuses, or otherwise changes a target's state.
- **Only two cross-process messages are ever sent:** `WM_GETTEXT` and
  `WM_GETTEXTLENGTH`. No other window message goes out to a target.
- **Owner-drawn data grids yield no text through any accessibility
  surface.** Neither UI Automation nor MSAA exposes cell contents for
  that control shape, and this iteration does not address it — a grid
  reading strategy is future work.
- **Ancestor scoping (`within`) is Python-API-only.** `Locator.parse` has
  no shorthand for it; there is no command-line equivalent in Iteration 1.
- **There is no MCP server yet.** Everything above is a CLI that calls the
  same functions an MCP server will call later. The protocol layer arrives
  in Iteration 2.

## Design notes

- **Locators, not handles.** The OS recycles window handles and voids them
  when a process exits, so elements are re-resolved from a declarative
  query on every call.
- **Input-shaped messages, not semantic ones.** Semantic messages such as
  `BM_CLICK` are implemented by a specific window class and are discarded
  by anything else. Input-shaped messages only assume the toolkit handles
  mouse and keyboard input.
- **Pure logic separated from platform calls.** The Windows backend
  produces plain `WindowNode` trees; matching, summarization, and inference
  operate on those and are testable on any platform.
