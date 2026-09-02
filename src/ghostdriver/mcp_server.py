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

Actuation is available only to a session opened at the `interactive` tier,
and only for a target the operator approved. Four things about it:

5. Actuation refuses a locator that matches more than one element. Scope it
   with within=... rather than hoping.

6. Delivering input is not the same as the input having an effect, and on
   this class of target they come apart routinely. `expect` is how you say
   what should be true afterwards; without it, a result claims only that
   the message went out.

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
    # Actuation. Not idempotent: clicking twice is two clicks, and a client
    # that retried on a timeout would submit twice. destructiveHint stays
    # False because these are ordinary interactions rather than deletions --
    # what must never be actuated is the profile denylist\'s job, and it is
    # enforced on the resolved caption before anything is sent.
    ACTUATES = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                               idempotentHint=False, openWorldHint=True)

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

    ExpectArg = Annotated[dict | None, Field(description=(
        "How to tell that this worked, as {locator, text}. Checked after the "
        "action, and re-resolved at that point -- so it can name something "
        "that does not exist until the action succeeds. Without it the "
        "result reports only that the input was delivered."
    ))]
    CadenceArg = Annotated[str | None, Field(description=(
        "How fast to type: 'robot' (queue speed) or 'fast_human' (~80ms a "
        "character, uneven). Defaults to whatever the target's profile "
        "declares, else robot. Use fast_human where an application rejects "
        "machine-speed input; it makes a long field take seconds."
    ))]

    @server.tool(annotations=ACTUATES, description=(
        "Click one control. The locator must match exactly one element -- "
        "ambiguity is refused rather than guessed at. Refuses to act while "
        "a modal dialog holds the application, and reports anything else "
        "that changed around the click, such as a dialog it raised."
    ))
    def click(
        session_id: SessionId,
        locator: LocatorArg,
        all_windows: AllWindows = False,
        expect: ExpectArg = None,
    ) -> dict[str, Any]:
        return box.click(session_id, locator, all_windows=all_windows,
                         expect=expect)

    @server.tool(annotations=ACTUATES, description=(
        "Replace a field's contents by typing them. Always reads the field "
        "back and fails if what it displays is not what was asked for -- a "
        "control can silently take only part of a long value. If the field "
        "reformats input (a date mask), pass expect_text with the value it "
        "should end up showing. Displaying a value is not the same as the "
        "application having accepted it: pass expect naming where the "
        "committed value appears to check that too."
    ))
    def set_value(
        session_id: SessionId,
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
        return box.set_value(session_id, locator, text,
                             all_windows=all_windows, expect_text=expect_text,
                             expect=expect, cadence=cadence)

    @server.tool(annotations=ACTUATES, description=(
        "Type at the caret without clearing first. Use `set_value` to "
        "replace a field; use this to append, or to type into something "
        "that is not a field -- a grid cell in edit mode, a search box that "
        "filters as it goes."
    ))
    def type_text(
        session_id: SessionId,
        locator: LocatorArg,
        text: Annotated[str, Field(description="The characters to type.")],
        all_windows: AllWindows = False,
        cadence: CadenceArg = None,
        expect: ExpectArg = None,
    ) -> dict[str, Any]:
        return box.type_text(session_id, locator, text,
                             all_windows=all_windows, cadence=cadence,
                             expect=expect)

    @server.tool(annotations=ACTUATES, description=(
        "Send named keys to a control: enter, tab, escape, backspace, "
        "delete, or single characters. On this class of target these often "
        "reach what the mouse cannot -- committing a grid row, or "
        "dismissing a dialog whose buttons ignore clicks."
    ))
    def send_keys(
        session_id: SessionId,
        locator: LocatorArg,
        keys: Annotated[list[str], Field(description=(
            "In order, e.g. ['tab', 'enter']."
        ))],
        all_windows: AllWindows = False,
        cadence: CadenceArg = None,
        expect: ExpectArg = None,
    ) -> dict[str, Any]:
        return box.send_keys(session_id, locator, keys,
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
        session_id: SessionId,
        locator: Annotated[str | None, Field(description=(
            "Narrow the evidence to one element. Omit to use the strongest "
            "differential this session can show."
        ))] = None,
        note: Annotated[str, Field(description=(
            "Anything else worth recording alongside it -- what the "
            "application did when the fast attempt failed, for instance."
        ))] = "",
    ) -> dict[str, Any]:
        return box.record_input_sensitivity(session_id, locator=locator,
                                            note=note)

    @server.tool(annotations=READS, description=(
        "Hand a step to the person and wait for the application to show it "
        "done. Use it for anything that is not yours to do: a password or "
        "any other credential, a step the operator asked to perform "
        "themselves, an irreversible action, or a decision that needs their "
        "judgement. Pass `until` naming what will be true once they have "
        "finished -- a dialog gone, a field filled -- so you resume on "
        "something observed rather than on someone saying they did it. "
        "Never type a credential yourself, and never ask for one to be told "
        "to you: it goes from the person into the application directly."
    ))
    async def await_human(
        session_id: SessionId,
        ask: Annotated[str, Field(description=(
            "What the person needs to do, in plain words. Relayed to them "
            "exactly as written, so write it to be read by them and not by "
            "you."
        ))],
        until: Annotated[dict | None, Field(description=(
            "What proves it is done: {locator, text?, absent?}. `absent` "
            "waits for the element to be gone, which is how a sign-in "
            "dialog closing tells you someone signed in. Omit only when "
            "nothing observable would change."
        ))] = None,
        timeout_s: Annotated[float, Field(description=(
            "How long to wait before giving up and saying so."
        ))] = 120.0,
        all_windows: AllWindows = False,
        ctx: Context = None,
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
        return box.await_human(session_id, ask, until=until,
                               timeout_s=timeout_s, all_windows=all_windows,
                               confirmed=confirmed)

    return server


def main() -> None:
    """Entry point for `ghostdriver-mcp`."""
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
