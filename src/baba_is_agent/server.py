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
        """Read compact exact board and rules once per scene. at=[x,y,dir,id]. No OCR."""
        with output.lock:
            return output.render(service.get_state(), "board")

    @server.tool(annotations=interactive)
    def act(actions: list[Action] | str, view: View = "delta") -> CallToolResult:
        """Execute a planned batch, e.g. 'R8 U2 Z', in one call. Return only changes by default."""
        with output.lock:
            result = service.act(actions)
            return output.render(result.state, view, executed=result.executed)

    @server.tool(annotations=interactive)
    def press(key: Key, view: View = "delta") -> CallToolResult:
        """Menu/introduction/AUTO key. Returns a small delta; use act for batched puzzle moves."""
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
