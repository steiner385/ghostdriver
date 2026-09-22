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
pytest -m "not slow and not clipboard"
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

**A standing approval, if you want one, is declared by hand.** An
approval still ends when the target itself restarts -- that is what
"that application, running" means. For an executable you have already
decided about for this machine, write
`standing-consent.json` in the operator directory:

```json
{
  "allow": [{"path": "C:\\Program Files\\Vendor\\VendorApp.exe",
             "note": "the line-of-business client"}],
  "restrict": ["C:\\Windows\\System32\\mmc.exe"]
}
```

**This server reads that file and never writes it, and no tool can** --
that is the only thing separating an approval you gave from one an agent
would like you to have given (D#125). It answers *last*: a decision about
a running pid, or about its parent, always wins, so a declaration cannot
un-restrict something you ruled out a minute ago. A target approved this
way says so wherever its grant is shown, because nobody was asked about
it. Matching is on the executable path alone, so a declaration covers
every instance of that program -- including one pointed somewhere you
would not have approved. The path to copy is in the `needs_consent`
result as `target.exe`.

**Developing it: hot reload.** Set `GHOSTDRIVER_DEV=1` in the server's
environment and an edit to `tools/` or `backends/` takes effect on the next
tool call, with open sessions kept. The next result says what reloaded.
Edits to `session`, `policy`, `consent`, `model` or the server itself are
reported as needing a reconnect (`/mcp` in Claude Code); a new tool or
parameter always does, since the host caches the tool list at connect.
An edit that fails to import keeps the previous generation running.

**A click can name the surface changing.** When no control's presence
proves an action worked -- an owner-drawn bar whose click docks a
palette seconds later -- `expect={"changed": true}` verifies against the
surface shape instead, and tells "delivered and something changed" from
"delivered and nothing did". The delivered-inactive caveat is dropped
when the click's own disturbances show a window opening or closing.

**A window can be brought forward, on request.** `foreground` is the
deliberate pair to `isolation=minimized`: everything works from the
background, but when a step needs the window frontmost -- handing the
click to a tool that uses real input for a control that ignores posted
messages -- this raises it, reports whether it took the foreground, and
warns that it interrupts the operator. Never automatic.

**The watches follow the process tree.** A session's consent covers the target's helper processes, and so do its watches: under `isolation=minimized`, a helper's window coming on screen is caught, photographed and put away, and a workflow's interference watch reports a helper taking the foreground as the target taking it.

**The clipboard is the person's.** Setting text never touches it: the whole-value rung inserts through the control's own edit path. The one route that must write it, a grid's own Copy, runs only in a session attached with `clipboard=true`, and puts every format back afterwards.

**The effect may arrive after the action.** A profile can name how the target shows it is busy -- `busy_indicator`, a locator present while busy or a region that renders ink while busy. Every actuation result then says `still_arriving` while it shows, and `wait_idle` waits for it to clear before you read a grid that is still filling.

**A result does not say ok for nothing.** A click delivered to a window
that is not active carries a `warning` and reads `delivered_inactive`,
since a control that checks focus would ignore it; `require_active` refuses
rather than delivering blind. `await_human` refuses a hand-off with no
condition and takes `until_change` to watch the surface move when you
cannot name what will appear. `hit_targets` lists a container's child
windows so a point click aims at a real target.

**A click goes to the window under the pointer.** A click posted to a panel over a windowed child is dropped by the panel; this tool posts to the innermost window under the point and says so (`delivered_to`). A control that answers empty and renders content is flagged `read_unreliable`; a window the system reports hung is reported hung; the notice a person sees during `await_human` has a Later that returns the wait as `deferred`.

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

**How long an approval lasts depends on the configuration, so the tool
says which case it is in rather than leaving anyone to assume** (#62):
the elicitation prompt and every `needs_consent` result carry the same
`lifetime` sentence, naming either "while that process keeps running,
across restarts of this server" or "this server run only" with the
environment variable that changes it. A decision can be revised at any
time, and revoking a target stops a session already using it. A decision
covers the application's whole process tree: the file dialog a browser
opens in a helper process is the application the operator approved, not a
new question, and a session sees that dialog's windows with
`all_windows=true` without a second attach. A profile
document is optional (every key is described in `docs/PROFILE.md`, and
`ghostdriver check-profile <name>` reads one back); its denylist names controls by caption or identity,
and, since D72, by *place*: `{"within": locator, "region": {left, top,
right, bottom}, "note"}` refuses any actuation aimed inside that rectangle
of the named window -- a grid cell, a painted button.

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

The directory holds `profiles/`, `workflows/`, `reports/`, `consent/`,
the optional `standing-consent.json` described above, and `logs/`,
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
- **Put a value into an owner-drawn grid cell.** A grid that edits through
  a window -- an edit appearing under it, or a popup -- hands `set_value` an
  ordinary control, and that case needs nothing new. A grid that paints its
  editing the way it paints its rows offers no window to address, and there
  is no primitive here that sets such a cell. Which one a grid is has not
  been measured on a real target; the one field report is of a cell that
  took neither a posted key nor a real one. So the tool says how to tell
  the two apart (post `f2` or a double-click, then `find` again) instead of
  promising the first, and says plainly what the second means: the value
  goes in through the application's own interface, or a person does it
  (D#199).
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
