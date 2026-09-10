"""MCP binding: a thin adapter over `tools.Toolbox`.

Everything with judgement in it lives in `tools.py`, which is why this file
is dull. The rule is that no decision belongs here — if a rule about tiers,
truncation or error shape has leaked into this module, it has leaked out of
where it can be tested without a protocol client.

Tool descriptions are written for the agent that will read them, and are
part of the interface rather than commentary on it. An agent that does not
know menus and dialogs are separate top-level windows will search one window
and conclude a control does not exist.

Returns are annotated `dict[str, Any]` rather than `dict`: the SDK refuses a
bare `dict` for structured output, and without a concrete annotation a
client receives JSON text it has to parse rather than a structured result.
"""

import sys
from typing import Annotated, Any

from pydantic import BaseModel, Field

from .devreload import LiveToolbox
from .devreload import enabled as dev_reload_enabled
from .policy import ConsentSource
from .session import SessionManager

SERVER_INSTRUCTIONS = """\
Drives desktop applications that predate modern accessibility APIs, by
reading their window tree directly.

Start with `list_targets`. **No target may be automated until the person
you are working with has approved it for this session.** Show them the
candidates, ask which to automate, then `attach`. If your client supports
it, `attach` will ask them directly; otherwise record their answer with
`grant_targets`. Approvals last for this server run and can be changed at
any time. Record a *restriction* only for a target the operator ruled
out: a target nobody allowed is never automated, and one server can serve
several chats at once, so a restriction recorded here stops that target's
sessions in every chat.

Four things about this class of target are worth knowing before you plan:

1. Menus, dropdowns, lookup lists and modal dialogs are usually *separate
   top-level windows*, and some -- a browser's file dialog -- live in a
   helper process of their own. Tools default to the main window; pass
   all_windows=true to reach the rest, including windows the target's
   child processes own. Approval of a target covers its child processes,
   so never re-ask for a dialog the approved application opened. A "not
   found" that did not search them is not evidence the control is absent.

2. A modal dialog disables the window it belongs to, so every control there
   legitimately refuses input. `describe` and `attach` report this as
   `blocked`. Deal with the dialog before anything else — retrying will not
   work.

3. Not every region can be read the same way. `surfaces` classifies each
   one: native controls answer window messages, some regions expose an
   accessibility tree instead, embedded web documents need their own
   mechanism, and owner-drawn regions expose nothing at all and can only be
   captured as pixels.

4. A control that did not answer is not the same as a control that is
   empty. `read` distinguishes them; treat a null value as unknown. A
   control that answers empty and renders content is flagged
   `read_unreliable`: verify by capture, not by read. A window the system
   reports `hung` will handle nothing until it recovers: stop and tell the
   person.

Actuation is available only to a session opened at the `interactive` tier,
and only for a target the operator approved. Four things about it:

5. Actuation refuses a locator that matches more than one element. Scope it
   with within=... rather than hoping.

6. Delivering input is not the same as the input having an effect, and on
   this class of target they come apart routinely. `expect` is how you say
   what should be true afterwards; without it, a result claims only that
   the message went out. A click into a window that is not active carries
   a `warning` and reads `delivered_inactive`, because a control that
   checks focus ignores it; `require_active` refuses instead. A step that
   truly needs an active window is a step for a person: `await_human`,
   which now refuses a hand-off with no condition and takes `until_change`
   for the case where you cannot yet name what will appear.

7. `set_value` always reads the field back, because a control can silently
   accept only part of a long value. A field displaying what you typed is
   still not proof the application accepted it -- for a data-bound field,
   name where the committed value appears.

8. Every action reports what else changed around it: a dialog that
   appeared, the application becoming held, the target coming to the front.
   Read it even on success. If an action fails and something appeared next
   to it, that may be the application objecting -- retrying at
   cadence=fast_human is the experiment that tells input sensitivity apart
   from an ordinary validation failure. Ask the operator before retrying
   anything that submits.\
"""

SessionId = Annotated[str, Field(description=(
    "The session handle from `attach` (its `session_id`). Named "
    "`session_ref` here, not `session_id`, because a tool argument named "
    "`session_id` collides with MCP's own protocol-level `session_id` and "
    "some clients strip it in transit (#79)."
))]
LocatorArg = Annotated[
    str,
    Field(description=(
        'Declarative query, e.g. class=TPanel text="Save" visible=true. '
        "Keys: class (glob, case-sensitive), text (exact, or /regex/), "
        "visible, index, within=(...) to scope by ancestor. Add type= "
        "and/or name= to name an element that is not a window (a tab "
        "item, a toolbar button) on the accessibility surface. Prefer "
        "these over handles: handles are recycled by "
        "the OS and are valid only within one result."
    )),
]
AllWindows = Annotated[
    bool,
    Field(description=(
        "Search every top-level window rather than the main one. Needed for "
        "dialogs, menus, dropdowns and lookup lists."
    )),
]


class ConsentAnswer(BaseModel):
    """What the operator is asked when a target has not been decided on."""

    allow: bool = Field(
        description=(
            "Allow this application to be automated for the rest of this "
            "session? Choose no to leave it alone."
        )
    )
    note: str = Field(
        default="",
        description="Optional reason, recorded with the decision.",
    )


class HumanDone(BaseModel):
    """What the operator is asked when a step is handed to them.

    Only a confirmation. There is deliberately no field for a value: the
    whole point of handing a step over is that whatever it involves goes
    from the person into the application without passing through here.
    """

    done: bool = Field(
        description="Tick once you have done it, or leave it to skip."
    )


def build_server(sessions: SessionManager | None = None) -> Any:
    """Construct the server. Importable without starting anything."""
    import json

    try:
        from mcp.server.mcpserver import Context, MCPServer
        from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations
    except ImportError as exc:
        # `import mcp` succeeding proves nothing: FastMCP was renamed to
        # MCPServer at the 2.0 boundary, so a 1.x install answers the import
        # and then fails on an inner path whose name explains nothing to the
        # person reading it. Say what is actually wrong.
        installed = "not installed"
        try:
            from importlib.metadata import version

            installed = version("mcp")
        except Exception:
            pass
        raise RuntimeError(
            "the protocol layer needs the mcp package at 2.1 or later "
            f"(found: {installed}). It is the optional [server] extra: "
            "pip install -e '.[server]'. Versions 1.x are not "
            "interchangeable with 2.x -- FastMCP was renamed to MCPServer at "
            f"that boundary, which is why the import failed as {exc}."
        ) from exc

    # The closures below call through this; with GHOSTDRIVER_DEV set it
    # rebuilds the toolbox from freshly imported modules on change (D68).
    box = LiveToolbox(sessions or SessionManager())
    server = MCPServer(
        name="ghostdriver",
        instructions=SERVER_INSTRUCTIONS,
    )

    # Every tool here reads. Declaring it lets a client decide for itself
    # how much ceremony a call deserves, rather than treating them all as
    # potentially destructive. `restore` is the one that changes anything a
    # person can see -- it un-minimizes a window -- so it is not marked
    # read-only, even though it changes no application state.
    READS = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                            idempotent_hint=True, open_world_hint=True)
    CHANGES_SCREEN = ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                     idempotent_hint=True, open_world_hint=True)
    # Actuation. Not idempotent: clicking twice is two clicks, and a client
    # that retried on a timeout would submit twice. destructiveHint stays
    # False because these are ordinary interactions rather than deletions --
    # what must never be actuated is the profile denylist\'s job, and it is
    # enforced on the resolved caption before anything is sent.
    ACTUATES = ToolAnnotations(read_only_hint=False, destructive_hint=False,
                               idempotent_hint=False, open_world_hint=True)

    @server.tool(annotations=READS, description=(
        "Every process that owns windows, with how many top-level windows "
        "each has and whether a session is already open against it. Start "
        "here, then `attach` to the pid you want."
    ))
    def list_targets() -> dict[str, Any]:
        return box.list_targets()

    @server.tool(description=(
        "Record which targets the operator has approved for automation in "
        "this session, and which they want left alone. Use this after "
        "asking them. Decisions last for this session only and can be "
        "revised; restricting a target with an open session stops it "
        "immediately, in every chat this server serves -- so restrict only "
        "what the operator ruled out, never what this chat merely does not "
        "need."
    ))
    def grant_targets(
        allow: Annotated[list[int] | None, Field(description=(
            "Pids the operator approved."
        ))] = None,
        restrict: Annotated[list[int] | None, Field(description=(
            "Pids the operator wants left alone."
        ))] = None,
        note: Annotated[str, Field(description=(
            "Optional reason, recorded with the decision."
        ))] = "",
    ) -> dict[str, Any]:
        return box.grant_targets(allow=allow, restrict=restrict, note=note)

    @server.tool(annotations=CHANGES_SCREEN, description=(
        "Open a session against a running target. If the operator has not "
        "yet approved this target for the session, asks them directly where "
        "the client supports it, and otherwise returns needs_consent so you "
        "can ask them and call grant_targets. Reports whether the target is "
        "currently held by a modal dialog."
    ))
    async def attach(
        ctx: Context,
        pid: Annotated[int, Field(description="From `list_targets`.")],
        tier: Annotated[str, Field(description=(
            "read_only (default), interactive, or full. Immutable for the "
            "session's lifetime."
        ))] = "read_only",
        profile_path: Annotated[str | None, Field(description=(
            "Optional profile document: a bare name looked up in the operator "
            "directory (profiles/<name>.json under GHOSTDRIVER_OPERATOR_DIR), "
            "or a path. Supplies the denylist, safe controls, input "
            "sensitivity notes and the busy_indicator wait_idle uses."
        ))] = None,
        clipboard: Annotated[bool, Field(description=(
            "Allow this session to write the person's clipboard. Only the "
            "grid copy route (probe_grid, grid_seek) needs it -- the target's "
            "own Copy command writes the clipboard, which the person notices. "
            "Off by default; every format is saved and put back around each "
            "copy when on. Setting text never uses the clipboard."
        ))] = False,
        isolation: Annotated[str, Field(description=(
            "none (default) or minimized. minimized keeps the target "
            "minimized for the session without activating anything else; "
            "if a window of it comes on screen -- usually a modal -- it is "
            "photographed, put back, and reported on the next result as "
            "watchdog_events. restore is refused while it runs, and the "
            "window stays minimized after release (un-minimizing it would "
            "bring it to the front); the operator clicks the taskbar."
        ))] = "none",
    ) -> dict[str, Any]:
        result = box.attach(pid, tier=tier, profile_path=profile_path,
                            isolation=isolation, clipboard=clipboard)
        if not result.get("needs_consent"):
            return result

        # Nobody has decided about this target yet. Ask the operator
        # directly if the client can carry the question -- consent obtained
        # this way cannot be fabricated by whatever is calling this tool.
        target = result["target"]
        try:
            answer = await ctx.elicit(
                message=(
                    f"Allow automation of {target['summary']}?\n\n"
                    "This lasts for this session only."
                ),
                schema=ConsentAnswer,
            )
        except Exception:
            # No elicitation support, or the client refused to carry it.
            # Say what to do instead rather than failing blankly.
            result["error"]["message"] = (
                f"pid {pid} has not been approved for automation, and this "
                "client cannot be asked directly. Ask the operator which "
                "targets to allow, then call grant_targets."
            )
            return result

        action = getattr(answer, "action", None)
        data = getattr(answer, "data", None)
        if action != "accept" or data is None:
            result["error"]["message"] = (
                f"the operator did not approve pid {pid}"
            )
            return result

        box.grant_targets(
            allow=[pid] if data.allow else None,
            restrict=None if data.allow else [pid],
            note=data.note,
            source=ConsentSource.ELICITED,
        )
        if not data.allow:
            result["error"]["message"] = (
                f"the operator restricted pid {pid} for this session"
            )
            result["needs_consent"] = False
            return result
        return box.attach(pid, tier=tier, profile_path=profile_path)

    @server.tool(annotations=READS, description=(
        "Close a session and forget it. Safe to call twice; a session that "
        "was never opened is not an error."
    ))
    def release(session_ref: SessionId) -> dict[str, Any]:
        return box.release(session_ref)

    @server.tool(annotations=READS, description=(
        "Summarized window tree, bounded to fit a context window. Repeated "
        "siblings collapse to counts, and what was dropped is reported "
        "rather than silently omitted. Returns suggested locators. Each "
        "node's `enabled` is its WS_DISABLED bit (IsWindowEnabled), not "
        "proof of availability: an owner-drawn control paints its own greyed "
        "state without clearing that bit and still reports enabled=true."
    ))
    def describe(
        session_ref: SessionId,
        depth: Annotated[int, Field(description="Levels to descend.")] = 5,
        max_nodes: Annotated[int, Field(description=(
            "Total node budget for the whole call, shared across windows."
        ))] = 200,
        all_windows: AllWindows = False,
        include_hidden: Annotated[bool, Field(description=(
            "Include windows and controls that are not visible. Roughly 90% "
            "of this target class is hidden, so expect far more output."
        ))] = False,
    ) -> dict[str, Any]:
        return box.describe(session_ref, depth=depth, max_nodes=max_nodes,
                            all_windows=all_windows,
                            include_hidden=include_hidden)

    @server.tool(annotations=READS, description=(
        "Resolve a locator to elements. Returns a re-resolvable locator for "
        "each match alongside its properties. Window locators (class=, "
        "text=) resolve against the window tree; element locators (type=, "
        "name=) resolve on the accessibility surface, where tab items, "
        "toolbar buttons and menu entries live without a window of their "
        "own -- e.g. type=TabItem, or type=MenuItem index=1 "
        "within=(class=ToolbarWindow32) for an unlabelled button. A context "
        "menu (class #32768, all_windows=true) lists its items from the "
        "menu itself: type=MenuItem name=\"Copy row values\", or index=N "
        "for an owner-drawn item that publishes no caption. "
        "`enabled` is the WS_DISABLED bit (IsWindowEnabled), the control's "
        "own flag -- not proof it will act. An owner-drawn control paints "
        "its own greyed, do-nothing state without clearing that bit, so it "
        "reports enabled=true while unavailable; confirm with capture or "
        "expect={changed} rather than trusting enabled. A match carries "
        "`obscured` only when its window is not clickable where its rect says "
        "-- minimized, or its centre covered by another program's window -- "
        "so a rect with no `obscured` is a safe target and one with it is not "
        "(restore or foreground first)."
    ))
    def find(session_ref: SessionId, locator: LocatorArg,
             all_windows: AllWindows = False) -> dict[str, Any]:
        return box.find(session_ref, locator, all_windows=all_windows)

    @server.tool(annotations=READS, description=(
        "Text of matching controls. A null value means the control never "
        "answered — unknown, not empty. An empty string means it answered "
        "and has no text."
    ))
    def read(session_ref: SessionId, locator: LocatorArg,
             all_windows: AllWindows = False) -> dict[str, Any]:
        return box.read(session_ref, locator, all_windows=all_windows)

    @server.tool(annotations=READS, description=(
        "The text on the clipboard: the result of a target's own Copy "
        "command, such as a grid's 'Copy row values' -- on an owner-drawn "
        "grid, the one exact read there is. Interactive tier, because the "
        "clipboard is the person's too: read it straight after the copy "
        "you triggered."
    ))
    def read_clipboard(session_ref: SessionId) -> dict[str, Any]:
        return box.read_clipboard(session_ref)

    @server.tool(annotations=READS, description=(
        "A picture of the target window, or of one element or region, "
        "returned as an image you can look at. The only way into "
        "owner-drawn regions such as grids, which expose no text through "
        "any accessibility surface. Does not bring the window to the front. "
        "Read what you see to decide what to do next -- but do not use it "
        "to confirm a value was saved. Reading pixels is a guess, however "
        "good a one, and this server is built so an action only claims "
        "success against something exactly checked: verify with `read`, or "
        "with an `expect` naming where the committed value appears. A capture "
        "with a locator returns an image whose pixel coordinates equal that "
        "element's own logical coordinates, so a point measured in it is an "
        "`at` with no arithmetic; and a scrollable pane shows only part of "
        "its text -- `read` or `modals` returns the whole buffer."
    ))
    def capture(
        session_ref: SessionId,
        locator: Annotated[str | None, Field(description=(
            "Capture just this element. Must match exactly one."
        ))] = None,
        region: Annotated[dict | None, Field(description=(
            "Screen rectangle {left, top, right, bottom}, as returned by "
            "`find` or `surfaces`."
        ))] = None,
        save_as: Annotated[str | None, Field(description=(
            "Also keep the PNG on disk under the operator directory's "
            "captures/ folder, by this file name; the result says where."
        ))] = None,
        frame: Annotated[str, Field(description=(
            "The frame `region` is in: logical (default) or physical (pixels "
            "of a DPI-aware screenshot)."
        ))] = "logical",
    ) -> CallToolResult:
        result = box.capture(session_ref, locator=locator, region=region, save_as=save_as,
                             frame=frame)
        if not result.get("ok"):
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps(result, indent=2),
                )],
                structured_content=result,
            )

        # The PNG goes back as an image block, so a model can look at it.
        # Returned inside the JSON as base64 it was unreadable *and*
        # enormous: measured on a real 3840x1200 window, 12.4MB of base64,
        # around three million tokens of a string nothing could see. The
        # same picture as an image block is a couple of thousand tokens and
        # legible, which is the entire reason this tool exists.
        image = result.pop("base64")
        return CallToolResult(
            content=[
                ImageContent(type="image", data=image, mime_type="image/png"),
                TextContent(type="text", text=json.dumps(result, indent=2)),
            ],
            # Without the pixels: the dimensions are worth having as data,
            # the image is not worth having twice.
            structured_content=result,
        )

    @server.tool(annotations=READS, description=(
        "Poll until a condition holds. Its start is traced as well as its "
        "end. Conditions: present, absent, "
        "visible, enabled, responsive, settled. Use `settled` after "
        "navigating — a screen that is still filling answers accurately and "
        "uselessly."
    ))
    def wait_for(
        session_ref: SessionId,
        locator: LocatorArg,
        condition: Annotated[str, Field(description="Default present.")] = "present",
        timeout_s: Annotated[float, Field(description=(
            "Seconds; default 10, up to 300. A screen that takes forty "
            "seconds to fill is one sixty-second wait, not four short ones."
        ))] = 10.0,
        all_windows: AllWindows = False,
    ) -> dict[str, Any]:
        return box.wait_for(session_ref, locator, condition=condition,
                            timeout_s=timeout_s, all_windows=all_windows)

    @server.tool(annotations=READS, description=(
        "Capability profile: toolkit, bitness, DPI mode, accessibility "
        "verdicts, class census. Read-only and slow-ish; the result is "
        "evidence for a human as much as for you."
    ))
    def probe(session_ref: SessionId) -> dict[str, Any]:
        return box.probe(session_ref)

    @server.tool(annotations=READS, description=(
        "Classify each region by which mechanism can drive it: native "
        "window messages, an accessibility surface, an embedded web "
        "document, or pixels only. Returns a shape digest; pass it back as "
        "changed_from later to detect that the screen now needs a different "
        "approach."
    ))
    def surfaces(
        session_ref: SessionId,
        all_windows: AllWindows = False,
        include_hidden: bool = False,
        changed_from: Annotated[str | None, Field(description=(
            "A shape digest from an earlier call."
        ))] = None,
    ) -> dict[str, Any]:
        return box.surfaces(session_ref, all_windows=all_windows,
                            include_hidden=include_hidden,
                            changed_from=changed_from)

    @server.tool(annotations=READS, description=(
        "Whether a modal dialog is holding the target, and which one. A "
        "held window refuses all input by design — that is not a hang, and "
        "retrying will not help."
    ))
    def modals(session_ref: SessionId) -> dict[str, Any]:
        return box.modals(session_ref)

    @server.tool(annotations=READS, description=(
        "The child windows inside a native container -- a panel of "
        "toggle bars, a toolbar of speed buttons -- with their "
        "rectangles, so a point click can be aimed at a real target "
        "instead of a coordinate read off a screenshot by eye. None "
        "listed means the parts are painted, not windowed: capture and "
        "click at an offset, or hand it to a person."
    ))
    def hit_targets(session_ref: SessionId, locator: LocatorArg,
                    all_windows: AllWindows = False) -> dict[str, Any]:
        return box.hit_targets(session_ref, locator, all_windows=all_windows)

    @server.tool(annotations=READS, description=(
        "Wait until the target's busy indicator clears, as its profile names "
        "it. On a target whose grids fill seconds after the click that asked "
        "for them, an actuation result marked still_arriving means a read "
        "taken now can be incomplete; call this first, then read. Refused, "
        "with instructions, when the profile names no busy_indicator."
    ))
    def wait_idle(session_ref: SessionId,
                  timeout_s: Annotated[float, Field(description="Seconds; default 30.")] = 30.0,
                  ) -> dict[str, Any]:
        return box.wait_idle(session_ref, timeout_s=timeout_s)

    @server.tool(annotations=READS, description=(
        "Dwell for a fixed number of seconds, then return. A deliberate "
        "stopgap: where the target declares a busy_indicator, wait_idle "
        "waits on the screen and is better; where a control's arrival can be "
        "named, wait_for is. Use pace only for the gap before either exists, "
        "instead of waiting on a locator built never to match. Clamped to "
        "120s; the result points at the better tool."
    ))
    def pace(session_ref: SessionId,
             seconds: Annotated[float, Field(description=(
                 "How long to dwell, in seconds. Positive, clamped to 120."
             ))]) -> dict[str, Any]:
        return box.pace(session_ref, seconds)

    @server.tool(annotations=ACTUATES, description=(
        "Run a list of steps against this session in one call, so a "
        "deterministic stretch of a loop is not one round trip per step. "
        "Each step is {tool, args}: `tool` is a session-scoped read-or-act "
        "tool (click, set_value, type_text, send_keys, find, read, "
        "read_clipboard, capture, describe, modals, surfaces, hit_targets, "
        "wait_for, wait_idle, grid_seek) and `args` its arguments WITHOUT "
        "the session, which the batch supplies. Give each acting step its own "
        "`expect` -- a batch verifies exactly what a standalone call does, so "
        "a step without one claims only that it was delivered. Stops on the "
        "first step that does not verify (stop_on_failure, default true), "
        "since a loop's steps depend on each other; the result says how far "
        "it got and carries every step's verdict. It is only a dispatcher -- "
        "each step passes the same approval, denylist and tier checks as its "
        "standalone call -- so lifecycle and consent tools (attach, release, "
        "grant_*, launch_isolated) and the two that interrupt a person "
        "(foreground, await_human) are refused inside it and run on their own."
    ))
    def batch(session_ref: SessionId,
              steps: Annotated[list[dict], Field(description=(
                  "The steps to run in order, each {tool, args}. args omits "
                  "the session. Example: [{\"tool\": \"click\", \"args\": "
                  "{\"locator\": \"type=TabItem name=Parts\", \"expect\": "
                  "{\"locator\": \"type=TabItem name=Parts\", \"selected\": "
                  "true}}}, {\"tool\": \"set_value\", \"args\": {...}}]"
              ))],
              stop_on_failure: Annotated[bool, Field(description=(
                  "Stop at the first step that does not verify (default). "
                  "false runs every step regardless, for independent reads."
              ))] = True) -> dict[str, Any]:
        return box.batch(session_ref, steps, stop_on_failure=stop_on_failure)

    @server.tool(annotations=READS, description=(
        "Save a step-list as a named macro under the operator directory, so a "
        "sequence you have worked out -- the batch you just ran, say -- can be "
        "replayed later. `steps` is the macro body: leaves ({tool, args, "
        "expect, ...}) and `when` branches ({when: {locator, ...}, then: [...], "
        "else: [...]}). `params` declares values bound at replay and referenced "
        "as ${name} in a step's args; `provenance` records where it came from. "
        "A malformed macro is refused here, not at replay. Operator "
        "bookkeeping: it touches the operator directory, not a target."
    ))
    def macro_save(
        name: Annotated[str, Field(description="A bare macro name (no path).")],
        steps: Annotated[list[dict], Field(description=(
            "The macro body: leaf steps and/or `when` branches (see the tool "
            "description). A leaf omits the session; the replay supplies it."
        ))],
        description: Annotated[str, Field(description="One line, shown in macro_list.")] = "",
        tier: Annotated[str, Field(description=(
            "The tier replay opens the session at: read_only, interactive, full."
        ))] = "read_only",
        isolation: Annotated[str, Field(description="none (default) or minimized.")] = "none",
        profile: Annotated[str | None, Field(description=(
            "A profile name replay attaches under; also the target class this "
            "macro was written for."
        ))] = None,
        params: Annotated[dict | None, Field(description=(
            "name -> {required, note}. Referenced as ${name} in a step's args."
        ))] = None,
        provenance: Annotated[dict | None, Field(description=(
            "{recorded_at, recorded_against (a profile id), revision}."
        ))] = None,
    ) -> dict[str, Any]:
        return box.macro_save(name, steps, description=description, tier=tier,
                              isolation=isolation, profile=profile, params=params,
                              provenance=provenance)

    @server.tool(annotations=READS, description=(
        "List the saved macros: each name, its one-line description, its step "
        "count and its params."
    ))
    def macro_list() -> dict[str, Any]:
        return box.macro_list()

    @server.tool(annotations=READS, description=(
        "Read one macro back: its metadata, provenance, params, and per-step "
        "verified / delivery_only flags -- so you can see, before replaying, "
        "which steps were confirmed and which were only delivered (an offset "
        "click on a painted region cannot be verified by locator)."
    ))
    def macro_show(
        name: Annotated[str, Field(description="The macro name.")],
    ) -> dict[str, Any]:
        return box.macro_show(name)

    @server.tool(annotations=READS, description=(
        "Archive a macro. It leaves the listing but stays recoverable under "
        "the operator directory's archive -- a delete you can undo, because "
        "the macro is the operator's, not the tool's."
    ))
    def macro_delete(
        name: Annotated[str, Field(description="The macro name to archive.")],
    ) -> dict[str, Any]:
        return box.macro_delete(name)

    @server.tool(annotations=CHANGES_SCREEN, description=(
        "Bring a window of the target to the front -- the deliberate pair to "
        "isolation=minimized. Everything else works from the background, so "
        "this is only for a step that needs the window frontmost, such as "
        "handing the click to a tool that uses real input. It interrupts the "
        "operator (the keyboard focus moves with the window), so it is never "
        "automatic; interactive tier. Says whether it took the foreground -- "
        "a background SetForegroundWindow can be refused."
    ))
    def foreground(session_ref: SessionId,
                   locator: Annotated[str | None, Field(description=(
                       "A specific window to raise; omit for the main window."
                   ))] = None) -> dict[str, Any]:
        return box.foreground(session_ref, locator=locator)

    @server.tool(annotations=CHANGES_SCREEN, description=(
        "Un-minimize the target so it can be read. Changes no application "
        "state; does nothing if the target is already visible. It CAN bring "
        "the window to the front: a plain minimized window comes back "
        "activated, and took_foreground in the result says whether it did. "
        "If the operator must not be interrupted, ask them to click the "
        "taskbar instead. Refused on a session that keeps its target "
        "minimized."
    ))
    def restore(session_ref: SessionId) -> dict[str, Any]:
        return box.restore(session_ref)

    ExpectArg = Annotated[dict | str | None, Field(description=(
        "How to tell that this worked: {locator, text}, a bare locator string "
        "for \"this is now present\", or {changed: true} when no control can be "
        "named and the effect is the surface itself moving -- a palette docking "
        "a few seconds later (timeout_s, default 6). timeout_s widens the "
        "verify window for any expect -- name it when a dialog or menu takes "
        "longer than ~2s to appear, or the action is declared failed while "
        "it is still arriving (#75). Keys: locator, text, "
        "selected, changed, timeout_s, all_windows; anything else, or an "
        "object with neither locator nor changed, is refused rather than "
        "ignored. Checked after the action, and re-resolved at that point -- "
        "so it can name something that does not exist until the action "
        "succeeds. Without it the result reports only that the input was "
        "delivered."
    ))]
    CadenceArg = Annotated[str | None, Field(description=(
        "How fast to type: 'robot' (queue speed) or 'fast_human' (~80ms a "
        "character, uneven). Defaults to whatever the target's profile "
        "declares, else robot. Use fast_human where an application rejects "
        "machine-speed input; it makes a long field take seconds."
    ))]

    @server.tool(annotations=ACTUATES, description=(
        "Click one control: a window, or an element that is not one -- a "
        "tab item, a toolbar button -- named by type=/name= (see find). An "
        "element is driven through the pattern it publishes, else by a "
        "click posted to its host window at its own rectangle; `at` aims "
        "the click at a point inside it (a grid row, a column header, a "
        "tree expander) and `button`/`count` make it a right- or double-"
        "click; frame=\"physical\" takes `at` in the pixels of a DPI-aware "
        "screenshot. The click goes to the innermost window under the point "
        "and the result says which (`delivered_to`). After a Copy command, "
        "`read_clipboard` reads what it put there. The locator must match "
        "exactly one element -- "
        "ambiguity is refused rather than guessed at. Refuses to act while "
        "a modal dialog holds the application, and reports anything else "
        "that changed around the click, such as a dialog it raised."
    ))
    def click(
        session_ref: SessionId,
        locator: LocatorArg,
        all_windows: AllWindows = False,
        expect: ExpectArg = None,
        button: Annotated[str, Field(description=(
            "left (default), right or middle. A right-click's context menu "
            "is a new top-level window: find it with all_windows=true."
        ))] = "left",
        modifiers: Annotated[list[str] | None, Field(description=(
            "Held keys: ctrl and/or shift. Carried in the click's own flags; "
            "a target that reads them sees Ctrl+click, one that asks the "
            "keyboard does not -- say what should follow in `expect`."
        ))] = None,
        at: Annotated[dict | None, Field(description=(
            "A point {x, y} in pixels inside the element, from its top-left "
            "corner, instead of its centre. For a region that paints its own "
            "rows and exposes none of them (a data grid): `capture` it, see "
            "where the row or link is, and click there. Read off a "
            "DPI-aware screenshot instead? Pass frame=physical and the point "
            "as measured; nothing needs converting by hand. Still posted; "
            "still activates nothing."
        ))] = None,
        frame: Annotated[str, Field(description=(
            "The frame `at` is in: logical (default; this tool's own "
            "rectangles) or physical (pixels of a DPI-aware screenshot, "
            "divided by the result's display_scale)."
        ))] = "logical",
        require_active: Annotated[bool, Field(description=(
            "Refuse rather than deliver when the target's window is not "
            "its thread's active window -- a control that checks focus "
            "would ignore the click. Default false: deliver anyway (many "
            "controls do not check), with a warning when it is inactive."
        ))] = False,
        count: Annotated[int, Field(description=(
            "1 for a click, 2 for a double-click (how most grids open a row)."
        ))] = 1,
    ) -> dict[str, Any]:
        return box.click(session_ref, locator, all_windows=all_windows,
                         expect=expect, button=button, modifiers=modifiers,
                         at=at, count=count, frame=frame, require_active=require_active)

    @server.tool(annotations=ACTUATES, description=(
        "Replace a field's contents by typing them. Always reads the field "
        "back and fails if what it displays is not what was asked for -- a "
        "control can silently take only part of a long value. If the field "
        "reformats input (a date mask), pass expect_text with the value it "
        "should end up showing. If typing arrives with characters missing, "
        "the value is pasted whole as the next rung (the result's `route` "
        "says which delivered). Displaying a value is not the same as the "
        "application having accepted it: pass expect naming where the "
        "committed value appears to check that too."
    ))
    def set_value(
        session_ref: SessionId,
        locator: LocatorArg,
        text: Annotated[str, Field(description="The value to put in.")],
        all_windows: AllWindows = False,
        expect_text: Annotated[str | None, Field(description=(
            "What the field should display afterwards, when that differs "
            "from what was typed. For masked or reformatting fields."
        ))] = None,
        expect: ExpectArg = None,
        cadence: CadenceArg = None,
    ) -> dict[str, Any]:
        return box.set_value(session_ref, locator, text,
                             all_windows=all_windows, expect_text=expect_text,
                             expect=expect, cadence=cadence)

    @server.tool(annotations=ACTUATES, description=(
        "Type at the caret without clearing first. Use `set_value` to "
        "replace a field; use this to append, or to type into something "
        "that is not a field -- a grid cell in edit mode, a search box that "
        "filters as it goes."
    ))
    def type_text(
        session_ref: SessionId,
        locator: LocatorArg,
        text: Annotated[str, Field(description="The characters to type.")],
        all_windows: AllWindows = False,
        cadence: CadenceArg = None,
        expect: ExpectArg = None,
    ) -> dict[str, Any]:
        return box.type_text(session_ref, locator, text,
                             all_windows=all_windows, cadence=cadence,
                             expect=expect)

    @server.tool(annotations=ACTUATES, description=(
        "Send named keys to a control: enter, tab, escape, backspace, "
        "delete, home, end, pageup, pagedown, arrows, or single characters; "
        "and the editing actions select-all, paste, copy, cut, undo, which "
        "are what Ctrl+A/V/C/X/Z become inside an edit control -- a posted "
        "keystroke carries no modifier state, so ctrl+ combinations cannot "
        "be sent as keys. On this class of target keys often reach what the "
        "mouse cannot: moving through a grid, committing a row, dismissing "
        "a dialog whose buttons ignore clicks."
    ))
    def send_keys(
        session_ref: SessionId,
        locator: LocatorArg,
        keys: Annotated[list[str], Field(description=(
            "In order, e.g. ['tab', 'enter']."
        ))],
        all_windows: AllWindows = False,
        cadence: CadenceArg = None,
        expect: ExpectArg = None,
    ) -> dict[str, Any]:
        return box.send_keys(session_ref, locator, keys,
                             all_windows=all_windows, cadence=cadence,
                             expect=expect)

    @server.tool(annotations=CHANGES_SCREEN, description=(
        "Record that this target refuses machine-speed input, so later "
        "sessions are told rather than having to find out by tripping it. "
        "Only works when this server saw the evidence itself: the same "
        "action failing at the default cadence and succeeding at "
        "cadence=fast_human. If it has not, the refusal says which half is "
        "missing. The note goes into the target's profile document; without "
        "one it is returned for the operator to place."
    ))
    def record_input_sensitivity(
        session_ref: SessionId,
        locator: Annotated[str | None, Field(description=(
            "Narrow the evidence to one element. Omit to use the strongest "
            "differential this session can show."
        ))] = None,
        note: Annotated[str, Field(description=(
            "Anything else worth recording alongside it -- what the "
            "application did when the fast attempt failed, for instance."
        ))] = "",
    ) -> dict[str, Any]:
        return box.record_input_sensitivity(session_ref, locator=locator,
                                            note=note)

    @server.tool(annotations=READS, description=(
        "Hand a step to the person and wait for the application to show it "
        "done. SAY THE ASK IN CHAT FIRST, in your own message, before "
        "calling this: the call blocks while it waits, and a person should "
        "not have to open a tool call to learn what you need. While it "
        "waits, the ask is also shown in a small always-on-top notice in the "
        "corner of their screen, which never takes focus and closes when "
        "the wait ends. Use it for anything a person must do themselves -- "
        "a password, a sign-in, a judgement call. A condition is required: "
        "`until` names a control that will appear or vanish; "
        "`until_change` waits for the target's surface to change when you "
        "do not yet know what will. Never carries a value."
    ))
    async def await_human(
        session_ref: SessionId,
        ask: Annotated[str, Field(description=(
            "What the person needs to do, in plain words. Relayed to them "
            "exactly as written, so write it to be read by them and not by "
            "you."
        ))],
        until: Annotated[dict | str | None, Field(description=(
            "What proves it is done: {locator, text?, absent?}, or a bare "
            "locator string. `absent` waits for the element to be gone, "
            "which is how a sign-in dialog closing tells you someone "
            "signed in. Use until_change instead when you cannot name it."
        ))] = None,
        until_change: Annotated[bool, Field(description=(
            "Wait for the target's surface shape to change, for the "
            "exploratory case where you do not yet know what will appear."
        ))] = False,
        timeout_s: Annotated[float, Field(description=(
            "How long to wait before giving up and saying so."
        ))] = 120.0,
        all_windows: AllWindows = False,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        confirmed = False
        if ctx is not None:
            try:
                answer = await ctx.elicit(
                    message=ask, schema=HumanDone,
                )
                data = getattr(answer, "data", None)
                if getattr(answer, "action", None) == "accept" and data:
                    confirmed = bool(data.done)
            except Exception:
                # No elicitation here. The agent relays the ask in chat
                # instead, and `until` still decides whether it happened --
                # which is why the condition is the part that matters.
                confirmed = False
        return box.await_human(session_ref, ask, until=until,
                               until_change=until_change,
                               timeout_s=timeout_s, all_windows=all_windows,
                               confirmed=confirmed)

    @server.tool(annotations=ACTUATES, description=(
        "Learn how this target's controls actuate, by actuating them. "
        "Requires a session at the `full` tier and a `safe_controls` list "
        "in the target's profile document -- it never chooses its own "
        "targets, and `only` can narrow that list but never add to it. "
        "Each listed control carries what should be true afterwards; "
        "anything that cannot be verified is reported rather than recorded, "
        "because a tier that cannot be shown to have worked is not a tier "
        "that works. Writes what it learned into the profile, touching "
        "nothing else in it."
    ))
    def probe_phase2(
        session_ref: SessionId,
        only: Annotated[list[str] | None, Field(description=(
            "Run just these locators. Each must already appear in the "
            "profile's safe_controls."
        ))] = None,
        settle_ms: Annotated[int, Field(description=(
            "How long to watch for the application pulling itself to the "
            "front after each control. A real target can take over a "
            "second."
        ))] = 1500,
    ) -> dict[str, Any]:
        return box.probe_phase2(session_ref, only=only, settle_ms=settle_ms)

    @server.tool(annotations=ACTUATES, description=(
        "Find how exact text comes out of an owner-drawn region such as a "
        "data grid, where `read` returns nothing and a capture is only "
        "pixels. Tries a focus-revealed accessibility surface first (no "
        "side effects), then the control's own copy, which uses the "
        "session-wide clipboard: prior text is restored afterwards, but the "
        "restore is not atomic and clipboard history sees the grid text. "
        "Pass allow_clipboard=false to try only the free route. Requires "
        "the `full` tier. Records the winning route in the profile as "
        "grid_strategy; never records cell data."
    ))
    def grid_seek(
        session_ref: SessionId,
        locator: LocatorArg,
        value: Annotated[str | None, Field(description=(
            "Stop at the first row containing this text; omit to read every "
            "page to the end."
        ))] = None,
        advance: Annotated[str, Field(description=(
            "The named key that pages the grid: pagedown (default) or down."
        ))] = "pagedown",
        max_pages: Annotated[int, Field(description="Stop after this many pages.")] = 50,
        all_windows: AllWindows = False,
    ) -> dict[str, Any]:
        return box.grid_seek(session_ref, locator, value=value, advance=advance,
                             max_pages=max_pages, all_windows=all_windows)

    @server.tool(annotations=CHANGES_SCREEN, description=(
        "Read an owner-drawn grid a page at a time -- one that yields its "
        "rows only to its own Copy and shows only the rows in view. Copies "
        "the current rows, matches `value` if given, pages with a caret key, "
        "and stops at the value, the end (a page that repeats), or max_pages. "
        "Full tier; needs a session attached with clipboard=true, since the "
        "target's Copy writes the person's clipboard; paging needs the grid to "
        "act on a posted key, which it may decline unless its window is "
        "active -- a view that never changes says so."
    ))
    def probe_grid(
        session_ref: SessionId,
        locator: LocatorArg,
        allow_clipboard: Annotated[bool, Field(description=(
            "Whether the clipboard route may be tried after the free one "
            "fails. It touches the shared clipboard."
        ))] = True,
        all_windows: AllWindows = False,
    ) -> dict[str, Any]:
        return box.probe_grid(session_ref, locator,
                              allow_clipboard=allow_clipboard,
                              all_windows=all_windows)

    @server.tool(annotations=CHANGES_SCREEN, description=(
        "Record the operator's decision about launching one exact command "
        "on a hidden desktop. Use it after asking them, the way "
        "grant_targets records a decision about a running target. Keyed by "
        "the command; a later decision replaces an earlier one."
    ))
    def grant_launch(
        command: Annotated[list[str], Field(description=(
            "The exact command the operator approved or declined, argv-style."
        ))],
        allow: Annotated[bool, Field(description="True to permit launching it.")],
        note: Annotated[str, Field(description="Optional reason, recorded.")] = "",
    ) -> dict[str, Any]:
        box.sessions.record_launch_grant(command, allowed=allow, note=note)
        return {"ok": True, "command": command, "allowed": allow}

    @server.tool(annotations=ACTUATES, description=(
        "Launch a target onto a hidden desktop and open a session on it. "
        "The target has no foreground to steal because it is not on the "
        "input desktop -- a structural guarantee, stronger than the "
        "minimized strategy's. It is also invisible and cannot be "
        "interacted with by a person, so a target needing interactive "
        "login cannot use it. Launching is the tool's widest authority and "
        "needs the operator's approval of the exact command first (see "
        "grant_launch); an unapproved command returns needs_consent. "
        "Release the session to close the target and the desktop."
    ))
    def launch_isolated(
        command: Annotated[list[str], Field(description=(
            "The target to launch, argv-style: [exe, arg, ...]."
        ))],
        tier: Annotated[str, Field(description=(
            "Tier of the opened session: read_only, interactive, or full."
        ))] = "read_only",
        announces_pid: Annotated[bool, Field(description=(
            "Only for a launcher that re-execs (a virtualenv python, say) "
            "and prints its real pid as one JSON line. A normal application "
            "leaves this false; setting it true would hang on one that "
            "prints nothing."
        ))] = False,
    ) -> dict[str, Any]:
        return box.launch_isolated(command, tier=tier,
                                   announces_pid=announces_pid)

    return server


def main() -> int:
    """Entry point for `ghostdriver-mcp`.

    A missing or wrong-version dependency is a broken install, not a crash:
    it is reported the way the CLI reports an unsupported platform, because
    the person reading it needs the sentence, not the stack.
    """
    if dev_reload_enabled():
        print("ghostdriver: dev reload on (GHOSTDRIVER_DEV). Implementation modules "
              "re-import when their files change; session, policy, consent, model "
              "and the server itself need a reconnect.", file=sys.stderr, flush=True)
    try:
        server = build_server()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
