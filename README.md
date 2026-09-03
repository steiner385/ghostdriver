# ghostdriver

An MCP server for driving desktop applications — for automated testing and
unattended tasks — without contending with a human working on the same
machine.

## Status

**Usable on Windows.** Twenty-three tools over a session manager, in three
capability tiers (`read_only`, `interactive`, `full`), with session-scoped
consent, a denylist that names controls by caption or by identity, a
tiered actuation ladder that never activates a window, two isolation
strategies (`minimized`, with a watchdog; `hidden_desktop`, launch-only),
locators for windows and for elements that are not windows, embedded web
documents driven through their accessibility tree, and an operator
directory the tool reads profiles and workflows from and refuses to read
from any repository. Linux is specified (`docs/LINUX.md`), not built.

See `docs/superpowers/specs/2026-09-01-desktop-automation-mcp-design.md` for
the design, `docs/DECISIONS.md` for what was decided along the way and why,
and `docs/VALIDATION.md` for the Iteration 1 runbook.

## Why

Most desktop automation assumes UI Automation works. For a large class of
enterprise line-of-business software it does not: applications built on
pre-UIA toolkits expose a tree in which every element is a `Pane` and no
element supports any pattern. Those applications remain drivable through
window messages, and that tier is what this tool implements.

Validation against a real target found the picture is not uniform even
within one application. Its native shell exposed 29 accessibility elements
with 2 usable patterns; an embedded web view inside the same window exposed
231 with 92. Which mechanism reads a region is a per-region question, so the
tool answers it per region.

## Install

```bash
pip install -e ".[dev,server]"
pytest
```

The quick gate for everyday changes leaves out the tests that launch an
engine, a hidden desktop or a server, or wait on a watchdog:

```bash
pytest -m "not slow"
```

Run the whole suite before a push, or after touching a backend, the
session gate or the actuation ladder. Both include the lint and type
tests and the focus guard.

That one command is the whole gate: the suite includes a test that runs
`ruff check src tests` and another that runs `mypy`, both configured in
`pyproject.toml`, so lint and type regressions fail the tests rather than
waiting for someone to remember a second command.

The `server` extra pulls in the MCP SDK. The CLI and the library work
without it.

## Use — MCP

```bash
ghostdriver-mcp          # stdio transport
```

Register it with a Claude client as a stdio server, with the operator
directory in its environment. For Claude Code (and the desktop app's Code
tab), from any directory:

```bash
claude mcp add --scope user --env GHOSTDRIVER_OPERATOR_DIR=C:\Users\you\ghostdriver-operator ghostdriver -- C:\path\to\ghostdriver-mcp\.venv\Scripts\ghostdriver-mcp.exe
```

The same server in JSON form, for a `.mcp.json` or the desktop chat
app's `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ghostdriver": {
      "command": "C:\\path\\to\\ghostdriver-mcp\\.venv\\Scripts\\ghostdriver-mcp.exe",
      "env": { "GHOSTDRIVER_OPERATOR_DIR": "C:\\Users\\you\\ghostdriver-operator" }
    }
  }
}
```

Use the virtual environment's console script, not a bare `python`: the
server needs the COM and Win32 bindings installed there. With the
operator directory configured, `attach` accepts a profile by bare name
(`profile_path="sandbox"` finds `profiles/sandbox.json` there), so no
path that names a machine crosses the wire.

Fifteen tools at the `read_only` tier: `list_targets`, `attach`,
`release`, `grant_targets`, `grant_launch`, `describe`, `find`, `read`,
`capture`, `wait_for`, `probe`, `surfaces`, `modals`, `restore`,
`await_human`. `interactive` adds `click`, `set_value`, `type_text`,
`send_keys` and `record_input_sensitivity`; `full` adds `probe_phase2`,
`probe_grid` and `launch_isolated`. The tier is chosen at `attach` and is
immutable for the session.

**A value gets there whole, or the tool says it did not.** `set_value`
types first, reads the field back, and if characters went missing pastes
the value whole as the next rung; the result names the `route` that
delivered. `send_keys` takes the editing actions `select-all`, `paste`,
`copy`, `cut` and `undo` -- what Ctrl+A/V/C/X/Z become inside an edit
control, since a posted keystroke carries no modifier state. `capture`
renders the window that holds what you named, and says its frame.

**Consent lasts as long as the application.** With an operator directory
configured, a decision about a target is kept for as long as that process
runs -- across relaunches of the operator app and redeploys of this server
-- in `consent/` under the directory, fingerprinted by process start time.
A restriction is kept the same way. Without an operator directory a
decision lives for one server run.

**Context menus are readable.** A popup menu's items come from the menu
itself: `find` lists them with rectangles and captions, an owner-drawn
item by position, and `click` takes either. `read_clipboard` reads back
what a target's own Copy command put there.

**One server, several chats.** The operator app runs one server process
for every chat, so approvals and restrictions are shared across them. A
restriction recorded in one chat stops that target's sessions in all of
them; a target nobody allowed is never automated, so leaving one alone
needs no record. A refused session says which decision refused it and
that `allow=[pid]` reverses it.

**When it needs a person, it says so on screen.** `await_human` shows its
ask in a small always-on-top notice in the corner of the operator's screen
for as long as it waits -- the one window this tool ever shows, and it
never takes focus. `click` takes `button` (left, right, middle) and
`modifiers` (ctrl, shift), so a Ctrl+right-click that opens a menu is the
tool's to do rather than the person's.

**Consent is decided in the chat, not in configuration.** `list_targets`
shows each candidate with the endpoint read from its own command line —
`the client (pid 62088) -- http://devhost:8183/devenv/gateway` — so the
person can see what they are approving. `attach` then asks them directly if
their client supports elicitation; otherwise it returns `needs_consent` and
the agent asks in chat and records the answer with `grant_targets`.

Approvals and restrictions last for that session only, can be revised at any
time, and revoking a target stops a session already using it. A decision
covers the application's whole process tree: the file dialog a browser
opens in a helper process is the application the operator approved, not a
new question, and a session sees that dialog's windows with
`all_windows=true` without a second attach. A profile
document is now optional and carries only the caption denylist.

## Use — CLI

```bash
ghostdriver list-targets
ghostdriver probe --pid 1234 --out profile.json
ghostdriver describe --pid 1234 --depth 5
ghostdriver describe --pid 1234 --depth 5 --all-windows
ghostdriver find --pid 1234 --locator 'class=VendorButton text="Expand All"'
ghostdriver find --pid 1234 --locator 'type=TabItem'                 # elements that are not windows
ghostdriver find --pid 1234 --locator 'type=MenuItem index=1 within=(class=ToolbarWindow32)'
ghostdriver find --pid 1234 --locator 'type=Button name="Save" within=(type=Document)'  # inside an embedded web document
ghostdriver read --pid 1234 --locator 'class=VendorEdit visible=true'
ghostdriver surfaces --pid 1234
ghostdriver modals --pid 1234
ghostdriver restore --pid 1234
```

## The operator directory

Everything that names a target -- profile documents with real endpoints,
curated denylists, workflow files, run reports -- lives in one directory
outside any repository, and the tool reads such things from there and
nowhere else:

```bash
set GHOSTDRIVER_OPERATOR_DIR=C:\Users\you\ghostdriver-operator
ghostdriver list-workflows
ghostdriver run-workflow walk-tabs --pid 1234
```

The directory holds `profiles/`, `workflows/`, `reports/` and `logs/`,
where every session's server writes a trace of its tool calls (one JSON
line per call: session, tool, arguments, outcome, elapsed; pixels left
out). `ghostdriver trace` prints the recent ones, so what another session
did can be read after the fact; `GHOSTDRIVER_TRACE=0` turns it off. A path
inside a git checkout is refused, and so is a packaged application's
virtualized AppData (a process inside one cannot write anywhere other
processes will see). A workflow is a JSON list of tool calls with
expectations; it names no target -- the pid is given at run time -- and
attaches at the tier and isolation it declares. The runner stops at the
first failed step, fails the run if the target ever takes the foreground,
and writes a report of every step and event back to `reports/`.

## Platforms

Windows is the backend. Linux is specified in `docs/LINUX.md` -- AT-SPI
for the tree and actuation, a nested X server for the structural
isolation guarantee -- and its package refuses every call with a pointer
there until it is built on a machine that can measure it. Everything
above the backend boundary (`ghostdriver.backends.current()`) is
platform-neutral, and a test keeps it that way.

## What it does not do

- **Un-minimize anything on its own.** Measured: every way of restoring a
  minimized window from a process allowed to set the foreground -- which any
  process launched from the operator's own application is -- brings it to
  the front. So a session under `isolation="minimized"` leaves the target
  minimized at release and says so, and `restore` reports `took_foreground`
  honestly rather than promising it stayed put. The operator clicks the
  taskbar.
- **Launch onto a hidden desktop anything but a classic Win32 process.**
  Store-activated applications are activated by the shell on the input
  desktop and ignore the desktop they were launched onto. And a target that
  needs a person to sign in cannot use a hidden desktop at all; `minimized`
  is the strategy for a target that is already running.
- **Give exact text out of an owner-drawn grid by itself.** `probe_grid`
  finds which route does -- a focus-revealed accessibility surface, or the
  control's own clipboard copy -- and records it; `capture` remains the way
  to look.
- **No role mapping.** `Locator` carries a `role` field for profiles to
  populate later, but nothing resolves it, so `Locator.parse` rejects
  `role=` outright rather than accepting a query that would match nothing.

## Design notes

- **Locators, not handles.** The OS recycles window handles and voids them
  when a process exits, so elements are re-resolved from a declarative
  query on every call. Results still report a handle, marked ephemeral,
  because it is the only thing that distinguishes two identically-captioned
  controls within a single result.
- **Input-shaped messages, not semantic ones.** Semantic messages such as
  `BM_CLICK` are implemented by a specific window class and are discarded
  by anything else. Input-shaped messages only assume the toolkit handles
  mouse and keyboard input.
- **Pure logic separated from platform calls.** The Windows backend
  produces plain `WindowNode` trees; matching, summarization, inference,
  policy and waiting operate on those and are testable on any platform.
- **The protocol layer holds no decisions.** the `tools` package returns plain data
  and carries every rule; `mcp_server.py` is an adapter over it. Anything
  that can be wrong is wrong somewhere testable without a protocol client.
- **Menus, dropdowns and dialogs are separate top-level windows.** On a
  measured target, 48% of the process's windows sat outside its main
  window. Tools default to the main window and say so; `all_windows` reaches
  the rest.
