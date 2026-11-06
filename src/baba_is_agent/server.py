"""One MCP tool set: exact observations, batched actions, and compact automatic deltas."""

import configparser
from dataclasses import asdict
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field

from baba_is_agent.errors import BabaError
from baba_is_agent.models import Action, ActionResult, GameState, JsonObject, Key
from baba_is_agent.navigation import map_levels
from baba_is_agent.presentation import Presenter, text_result
from baba_is_agent.service import GameService

INSTRUCTIONS = """Play Baba Is You. Start with observe(); it reads without advancing time.
act(actions=["right","right","up"]) executes 1..64 turns, including routes with turns.
Use undo to recover, restart to reset, enter_level for a numbered level on the current map.
Ordinary action replies are changes, not repeated boards; observe reads the whole board.
Properties are actual effects: OPEN does not imply PUSH. Respect rule conditions.
Use press/choose_menu for menus, intros, and AUTO. Native actions can update Steam saves.
After a timeout, observe before acting: the previous command may already have executed.
"""


def create_server(service: GameService) -> FastMCP:
    server = FastMCP("baba", instructions=INSTRUCTIONS)
    output = Presenter()
    read_only = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
    interactive = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

    def reply(
        state: GameState, *, full: bool = False, action: ActionResult | None = None
    ) -> CallToolResult:
        full = full or output.needs_board(state)
        map_info: JsonObject | None = None
        if full and any("select" in u.properties for u in state.units):
            try:
                map_info = {
                    "levels": [asdict(entry) for entry in map_levels(service.settings, state)],
                    "styles": "0=numbered, 1=letter/extra, 2=map",
                }
            except (BabaError, OSError, ValueError, configparser.Error) as error:
                map_info = {"error": str(error)}
        return output.render(state, full=full, action=action, map_info=map_info)

    def play(actions: list[Action]) -> CallToolResult:
        with output.lock:
            result = service.act(actions)
            return reply(result.state, action=result)

    @server.tool(annotations=read_only)
    def observe() -> CallToolResult:
        """Read the full exact board, rules, controller, and menu without advancing time.

        Start here, or use to resynchronize after a timeout or unexpected result.
        Object at=[x,y,direction,id]; zero-based x rightward, y downward.
        Directions right=0,up=1,left=2,down=3,idle=4. Respect rule conditions;
        OPEN does not imply PUSH. On maps, map.levels gives local numbers and availability.
        """
        with output.lock:
            return reply(service.get_state(), full=True)

    @server.tool(annotations=interactive)
    def act(
        actions: Annotated[list[Action], Field(min_length=1, max_length=64)],
    ) -> CallToolResult:
        """Execute 1..64 actions, e.g. {"actions":["right","right","up"]}.

        Pass an actual array, not a string. Allowed: up/down/left/right/wait/undo.
        Batch safe planned routes, including turns; use short batches near uncertainty.
        wait advances time; use observe to read. executed is commands processed, not distance.
        kind=delta: changed lists only changed units, grouped like observe().objects;
        at=[x,y,direction,id], removed lists deleted IDs. Unmentioned state is unchanged.
        effects highlights transformations/property changes since the previous reply.
        Current controller positions are always included. Scene changes return kind=board. After control_lost use undo
        or restart. Never blindly repeat a timed-out action: observe first.
        """
        return play(actions)

    @server.tool(annotations=interactive)
    def undo(steps: Annotated[int, Field(ge=1, le=64)] = 1) -> CallToolResult:
        """Undo 1..64 turns. Recover from a bad move or loss of control; returns changes."""
        return play(["undo"] * steps)

    @server.tool(annotations=ToolAnnotations(destructiveHint=True, openWorldHint=False))
    def restart() -> CallToolResult:
        """Discard the current puzzle attempt and return its initial board."""
        with output.lock:
            return reply(service.restart_level(), full=True)

    @server.tool(annotations=interactive)
    def press(key: Key) -> CallToolResult:
        """Press a menu/introduction/AUTO key; ordinary puzzle routes use act.

        confirm enters the level under the map cursor or dismisses levelintro.
        Returns changes, or a full board on scene change. Use observe for a read-only check.
        """
        with output.lock:
            return reply(service.press(key))

    @server.tool(annotations=interactive)
    def choose_menu(name: str) -> CallToolResult:
        """Activate an enabled button by its exact name from observe().buttons.

        Navigation and confirmation are internal. Returns changes or the new scene.
        """
        with output.lock:
            return reply(service.choose_menu(name))

    @server.tool(annotations=interactive)
    def enter_level(number: Annotated[int, Field(ge=0)]) -> CallToolResult:
        """Enter a regular numbered level on the current map, e.g. number=6 for 06.

        observe().map.levels lists local numbers and availability. Walks the native
        cursor, verifies the target, confirms and dismisses its intro; returns the board.
        Never unlocks or directly loads levels. On failure, observe before retrying.
        """
        with output.lock:
            return reply(service.enter_level(number), full=True)

    @server.tool(annotations=read_only)
    def list_levels(
        world: str = "baba",
        query: str = "",
        limit: Annotated[int, Field(ge=1, le=100)] = 30,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> CallToolResult:
        """Search installed level names/IDs; this is not the numbering on the current island.

        For a local numbered level, use observe().map.levels and enter_level instead.
        This read-only catalog is paginated and does not open or unlock levels.
        """
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
        """Launch Steam Baba Is You if needed, then observe. Does not install the bridge."""
        return text_result(service.launch_game())

    return server
