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

from typing import Annotated, Any

from pydantic import BaseModel, Field

from .policy import ConsentSource
from .session import SessionManager
from .tools import Toolbox

SERVER_INSTRUCTIONS = """\
Drives desktop applications that predate modern accessibility APIs, by
reading their window tree directly.

Start with `list_targets`. **No target may be automated until the person
you are working with has approved it for this session.** Show them the
candidates, ask which to automate and which to leave alone, then `attach`.
If your client supports it, `attach` will ask them directly; otherwise
record their answer with `grant_targets`. Approvals last for this session
only and can be changed at any time.

Four things about this class of target are worth knowing before you plan:

1. Menus, dropdowns, lookup lists and modal dialogs are usually *separate
   top-level windows*. Tools default to the main window; pass
   all_windows=true to reach the rest. A "not found" that did not search
   them is not evidence the control is absent.

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
   empty. `read` distinguishes them; treat a null value as unknown.

This server is read-only. Nothing here clicks, types or changes application
state.\
"""

SessionId = Annotated[str, Field(description="From `attach`.")]
LocatorArg = Annotated[
    str,
    Field(description=(
        'Declarative query, e.g. class=TPanel text="Save" visible=true. '
        "Keys: class (glob, case-sensitive), text (exact, or /regex/), "
        "visible, index. Prefer these over handles: handles are recycled by "
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


def build_server(sessions: SessionManager | None = None) -> Any:
    """Construct the server. Importable without starting anything."""
    from mcp.server.mcpserver import Context, MCPServer
    from mcp.types import ToolAnnotations

    box = Toolbox(sessions=sessions or SessionManager())
    server = MCPServer(
        name="ghostdriver",
        instructions=SERVER_INSTRUCTIONS,
    )

    # Every tool here reads. Declaring it lets a client decide for itself
    # how much ceremony a call deserves, rather than treating them all as
    # potentially destructive. `restore` is the one that changes anything a
    # person can see -- it un-minimizes a window -- so it is not marked
    # read-only, even though it changes no application state.
    READS = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                            idempotentHint=True, openWorldHint=True)
    CHANGES_SCREEN = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                     idempotentHint=True, openWorldHint=True)

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
        "immediately."
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
            "Optional profile document supplying the caption denylist."
        ))] = None,
    ) -> dict[str, Any]:
        result = box.attach(pid, tier=tier, profile_path=profile_path)
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
    def release(session_id: SessionId) -> dict[str, Any]:
        return box.release(session_id)

    @server.tool(annotations=READS, description=(
        "Summarized window tree, bounded to fit a context window. Repeated "
        "siblings collapse to counts, and what was dropped is reported "
        "rather than silently omitted. Returns suggested locators."
    ))
    def describe(
        session_id: SessionId,
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
        return box.describe(session_id, depth=depth, max_nodes=max_nodes,
                            all_windows=all_windows,
                            include_hidden=include_hidden)

    @server.tool(annotations=READS, description=(
        "Resolve a locator to elements. Returns a re-resolvable locator for "
        "each match alongside its properties."
    ))
    def find(session_id: SessionId, locator: LocatorArg,
             all_windows: AllWindows = False) -> dict[str, Any]:
        return box.find(session_id, locator, all_windows=all_windows)

    @server.tool(annotations=READS, description=(
        "Text of matching controls. A null value means the control never "
        "answered — unknown, not empty. An empty string means it answered "
        "and has no text."
    ))
    def read(session_id: SessionId, locator: LocatorArg,
             all_windows: AllWindows = False) -> dict[str, Any]:
        return box.read(session_id, locator, all_windows=all_windows)

    @server.tool(annotations=READS, description=(
        "PNG of the target's window, or of one element or region. The only "
        "way to read owner-drawn regions such as grids, which expose no "
        "text through any accessibility surface. Does not bring the window "
        "to the front."
    ))
    def capture(
        session_id: SessionId,
        locator: Annotated[str | None, Field(description=(
            "Capture just this element. Must match exactly one."
        ))] = None,
        region: Annotated[dict | None, Field(description=(
            "Screen rectangle {left, top, right, bottom}, as returned by "
            "`find` or `surfaces`."
        ))] = None,
    ) -> dict[str, Any]:
        return box.capture(session_id, locator=locator, region=region)

    @server.tool(annotations=READS, description=(
        "Poll until a condition holds. Conditions: present, absent, "
        "visible, enabled, responsive, settled. Use `settled` after "
        "navigating — a screen that is still filling answers accurately and "
        "uselessly."
    ))
    def wait_for(
        session_id: SessionId,
        locator: LocatorArg,
        condition: Annotated[str, Field(description="Default present.")] = "present",
        timeout_s: Annotated[float, Field(description="Seconds.")] = 10.0,
        all_windows: AllWindows = False,
    ) -> dict[str, Any]:
        return box.wait_for(session_id, locator, condition=condition,
                            timeout_s=timeout_s, all_windows=all_windows)

    @server.tool(annotations=READS, description=(
        "Capability profile: toolkit, bitness, DPI mode, accessibility "
        "verdicts, class census. Read-only and slow-ish; the result is "
        "evidence for a human as much as for you."
    ))
    def probe(session_id: SessionId) -> dict[str, Any]:
        return box.probe(session_id)

    @server.tool(annotations=READS, description=(
        "Classify each region by which mechanism can drive it: native "
        "window messages, an accessibility surface, an embedded web "
        "document, or pixels only. Returns a shape digest; pass it back as "
        "changed_from later to detect that the screen now needs a different "
        "approach."
    ))
    def surfaces(
        session_id: SessionId,
        all_windows: AllWindows = False,
        include_hidden: bool = False,
        changed_from: Annotated[str | None, Field(description=(
            "A shape digest from an earlier call."
        ))] = None,
    ) -> dict[str, Any]:
        return box.surfaces(session_id, all_windows=all_windows,
                            include_hidden=include_hidden,
                            changed_from=changed_from)

    @server.tool(annotations=READS, description=(
        "Whether a modal dialog is holding the target, and which one. A "
        "held window refuses all input by design — that is not a hang, and "
        "retrying will not help."
    ))
    def modals(session_id: SessionId) -> dict[str, Any]:
        return box.modals(session_id)

    @server.tool(annotations=CHANGES_SCREEN, description=(
        "Un-minimize the target without taking the foreground, so it can be "
        "read. Changes no application state. Safe to call before reading; "
        "does nothing if the target is already visible."
    ))
    def restore(session_id: SessionId) -> dict[str, Any]:
        return box.restore(session_id)

    return server


def main() -> None:
    """Entry point for `ghostdriver-mcp`."""
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
