# ghostdriver

An MCP server for driving desktop applications — for automated testing and
unattended tasks — without contending with a human working on the same
machine.

## Status

**Iteration 2: MCP server, read-only tier.** Thirteen tools over a session
manager, with capability tiers, a caption denylist, and session-scoped
consent: no target can be automated until the person running the session
approves it, and approvals die with the session. Still no actuation:
nothing clicks, types, or changes application state.

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

The `server` extra pulls in the MCP SDK. The CLI and the library work
without it.

## Use — MCP

```bash
ghostdriver-mcp          # stdio transport
```

Thirteen tools at the `read_only` tier: `list_targets`, `attach`,
`release`, `grant_targets`, `describe`, `find`, `read`, `capture`,
`wait_for`, `probe`, `surfaces`, `modals`, `restore`.

**Consent is decided in the chat, not in configuration.** `list_targets`
shows each candidate with the endpoint read from its own command line —
`the client (pid 62088) -- http://devhost:8183/devenv/gateway` — so the
person can see what they are approving. `attach` then asks them directly if
their client supports elicitation; otherwise it returns `needs_consent` and
the agent asks in chat and records the answer with `grant_targets`.

Approvals and restrictions last for that session only, can be revised at any
time, and revoking a target stops a session already using it. A profile
document is now optional and carries only the caption denylist.

## Use — CLI

```bash
ghostdriver list-targets
ghostdriver probe --pid 1234 --out profile.json
ghostdriver describe --pid 1234 --depth 5
ghostdriver describe --pid 1234 --depth 5 --all-windows
ghostdriver find --pid 1234 --locator 'class=VendorButton text="Expand All"'
ghostdriver read --pid 1234 --locator 'class=VendorEdit visible=true'
ghostdriver surfaces --pid 1234
ghostdriver modals --pid 1234
ghostdriver restore --pid 1234
```

## What this iteration does not do

- **No actuation of any kind.** Nothing clicks, types, focuses, or changes
  application state. No actuation verb is registered as a tool, because a
  tool an agent can find is a tool it will call.
- **`launch` is not implemented.** It needs an isolation strategy, and the
  `minimized` strategy ships in Iteration 4. Attach to a running target.
- **The denylist is enforced but unexercised.** The machinery matches
  captions and refuses, and is tested — but nothing calls it end to end,
  because there is no action to refuse yet.
- **Owner-drawn grids yield no text through any accessibility surface.**
  Measured directly against two real grids across four surfaces: no child
  windows, no text, no MSAA children, and a UIA subtree containing only
  their own scrollbars. `capture` is the way in; a grid reading strategy is
  future work.
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
- **The protocol layer holds no decisions.** `tools.py` returns plain data
  and carries every rule; `mcp_server.py` is an adapter over it. Anything
  that can be wrong is wrong somewhere testable without a protocol client.
- **Menus, dropdowns and dialogs are separate top-level windows.** On a
  measured target, 48% of the process's windows sat outside its main
  window. Tools default to the main window and say so; `all_windows` reaches
  the rest.
