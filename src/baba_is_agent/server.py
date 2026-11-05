"""MCP tools with compact single-copy results and server-side move batches."""

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ToolAnnotations

from baba_is_agent.models import Action, Key
from baba_is_agent.presentation import Presenter, View, text_result
from baba_is_agent.service import GameService

INSTRUCTIONS = """Play the real Baba Is You without screenshots. Call get_board once per level.
Use act with a whole planned sequence: actions="R8 U2 L3 Z" or a list, max 64 moves.
U/D/L/R are directions, W waits, Z undoes. Batches stop at win/death/transition.
Ordinary replies are small deltas, not full boards. Delta units are
[id,name,x,y,direction,properties]; removed lists deleted IDs. Unmentioned state is unchanged.
Board at entries are [x,y,direction,id]. Directions right=0,up=1,left=2,down=3.
Use get_state(view="full") only when full internal metadata is actually needed.
Use press/choose_menu for menus/intros/AUTO; their view parameter can request a board.
If a reply says refresh=get_board, read the new scene. Respect rule conditions.
Properties cover common effects; consult rules for other mechanics. Native gameplay writes
Steam saves. Never blindly retry after timeout. Do not switch desktop focus during menu input.
"""


def create_server(service: GameService) -> FastMCP:
    server = FastMCP("baba", instructions=INSTRUCTIONS)
    output = Presenter()
    read_only = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
    interactive = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

    @server.tool(annotations=read_only)
    def get_state(view: View = "summary") -> CallToolResult:
        """Small status by default. Use view='full' for raw units/metadata or get_board for planning."""
        with output.lock:
            return output.render(service.get_state(), view)

    @server.tool(annotations=read_only)
    def get_board() -> CallToolResult:
        """Read exact board and rules once per scene or when refresh=get_board.

        Coordinates are zero-based, x rightward and y downward. Object at entries
        are [x,y,direction,id]; directions right=0,up=1,left=2,down=3,idle=4.
        Rules include conditions: do not infer mechanics from object names alone.
        On a map, move the select cursor with act, then press(key='confirm').
        """
        with output.lock:
            return output.render(service.get_state(), "board")

    @server.tool(annotations=interactive)
    def act(actions: list[Action] | str, view: View = "delta") -> CallToolResult:
        """Execute 1..64 planned moves, e.g. actions='R8 U2 Z', in one call.

        U/D/L/R move, W waits, Z undoes; alternatively pass a list of action names.
        Batch safe travel together; use short batches near uncertain interactions.
        requested/executed count requested/processed commands, not successful movement.
        board_changed compares visible objects/rules/scene, not hidden engine state.
        controlled always contains current controller positions; stop_reason explains
        completion/interruption. No ordinary control: undo rather than repeat moves. Batches stop
        on win, loss of an initially present player, or scene transition.
        Delta units=[id,name,x,y,direction,properties]; removed lists deleted IDs.
        Unmentioned state is unchanged. Coordinates are zero-based (x right, y down).
        If refresh=get_board, read the new scene. Use press for menus and intros;
        act has no select/confirm action. Do not blindly retry timed-out actions.
        """
        with output.lock:
            result = service.act(actions)
            return output.render(result.state, view, action=result)

    @server.tool(annotations=interactive)
    def press(key: Key, view: View = "delta") -> CallToolResult:
        """Press a menu/introduction/AUTO key; use act for batched puzzle moves.

        On a map, press(key='confirm') enters the level under the select cursor.
        If menu='levelintro', confirm dismisses the introduction. Delta replies
        omit unchanged state; refresh=get_board means read the new scene.
        """
        with output.lock:
            return output.render(service.press(key), view)

    @server.tool(annotations=interactive)
    def choose_menu(name: str, view: View = "delta") -> CallToolResult:
        """Activate a reported enabled button. Navigation is internal; return just final changes."""
        with output.lock:
            return output.render(service.choose_menu(name), view)

    @server.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)
    )
    def restart_level(view: View = "delta") -> CallToolResult:
        """Restart the unpaused level, discarding puzzle progress. Small delta unless view='board'."""
        with output.lock:
            return output.render(service.restart_level(), view)

    @server.tool(annotations=read_only)
    def list_levels(
        world: str = "baba", query: str = "", limit: int = 30, offset: int = 0
    ) -> CallToolResult:
        """Search installed metadata by name/id; paginated to avoid dumping hundreds of levels."""
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Expected limit 1..100 and nonnegative offset")
        levels = [
            level
            for level in service.list_levels(world)
            if query.casefold() in f"{level['id']} {level['name']}".casefold()
        ]
        end = offset + limit
        return text_result(
            {
                "levels": levels[offset:end],
                "total": len(levels),
                "next_offset": end if end < len(levels) else None,
            }
        )

    @server.tool(annotations=interactive)
    def launch_game() -> CallToolResult:
        """Launch Steam app 736260. Does not install the bridge or restart an existing process."""
        return text_result(service.launch_game())

    return server
