"""MCP tools with compact single-copy results and server-side move batches."""

import configparser
from dataclasses import asdict
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field

from baba_is_agent.errors import BabaError
from baba_is_agent.models import Action, ActionResult, GameState, JsonObject, Key
from baba_is_agent.navigation import map_levels
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


LITE_INSTRUCTIONS = """Play Baba Is You with observe, move, undo, restart, press, and enter_level.
Start with observe(). It reads without advancing time; never wait just to inspect.
Move safe straight sections together with steps. Check actual properties after rule changes:
OPEN is not PUSH. If a result contradicts your plan, reconsider the plan rather than repeat it.
Use press for menus/intros/AUTO. Actions can update Steam saves. Never retry after timeout
without observing first. Do not change desktop focus during menu input.
"""


def create_server(service: GameService, profile: Literal["expert", "lite"] = "expert") -> FastMCP:
    if profile not in {"expert", "lite"}:
        raise ValueError("Expected MCP profile: expert or lite")
    server = FastMCP("baba", instructions=LITE_INSTRUCTIONS if profile == "lite" else INSTRUCTIONS)
    output = Presenter(spatial=profile == "lite")
    read_only = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
    interactive = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

    def board_reply(state: GameState, action: ActionResult | None = None) -> CallToolResult:
        map_info: JsonObject | None = None
        if any("select" in u.properties for u in state.units):
            try:
                map_info = {
                    "levels": [asdict(entry) for entry in map_levels(service.settings, state)],
                    "styles": "0=numbered, 1=letter/extra, 2=map",
                }
            except (BabaError, OSError, ValueError, configparser.Error) as error:
                map_info = {"error": str(error)}
        return output.render(state, "board", action=action, map_info=map_info)

    @server.tool(annotations=interactive)
    def enter_level(number: Annotated[int, Field(ge=0)]) -> CallToolResult:
        """Enter a regular numbered level on the current map, e.g. number=6 for 06.

        Read get_board (expert) or observe (lite) for map.levels and availability.
        Walks the native cursor and confirms the target, dismissing its introduction.
        Never unlocks or directly loads levels. If entry fails, inspect before retrying.
        """
        with output.lock:
            return board_reply(service.enter_level(number))

    if profile == "lite":

        def play(actions: list[Action]) -> CallToolResult:
            with output.lock:
                result = service.act(actions)
                return board_reply(result.state, result)

        @server.tool(annotations=read_only)
        def observe() -> CallToolResult:
            """Read the current board, rules, controller, and menu without advancing time.

            Start here. Use this to inspect a result, not move(direction='wait').
            Grid cells are space-separated: uppercase words, lowercase objects, + stacks.
            Positions have named x/y fields. properties describe actual checked effects;
            OPEN does not imply PUSH. changes_since_previous_reply flags transformations
            and property changes, not a proposed solution. Rule conditions still apply.
            """
            with output.lock:
                return board_reply(service.get_state())

        @server.tool(annotations=interactive)
        def move(
            direction: Literal["up", "down", "left", "right", "wait"],
            steps: Annotated[int, Field(ge=1, le=64)] = 1,
        ) -> CallToolResult:
            """Move in one direction for 1..64 turns, returning the resulting board.

            Example: {"direction":"right","steps":4}. Combine safe straight travel;
            use short runs near uncertain pushes. 'wait' advances time, not inspection.
            executed counts processed commands, not distance. Use undo after control_lost.
            """
            return play([direction] * steps)

        @server.tool(annotations=interactive)
        def undo(steps: Annotated[int, Field(ge=1, le=64)] = 1) -> CallToolResult:
            """Undo 1..64 turns and return the board. Use to recover from a bad move."""
            return play(["undo"] * steps)

        @server.tool(annotations=ToolAnnotations(destructiveHint=True, openWorldHint=False))
        def restart() -> CallToolResult:
            """Discard the current puzzle attempt and return its initial board."""
            with output.lock:
                return board_reply(service.restart_level())

        @server.tool(annotations=interactive)
        def press(key: Key) -> CallToolResult:
            """Press a menu/introduction/AUTO key and return the board.

            confirm enters the level under the map cursor or dismisses levelintro.
            For ordinary puzzle movement use move; to read without acting use observe.
            """
            with output.lock:
                return board_reply(service.press(key))

        return server

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
        On maps, map.levels connects displayed numbers to files and availability.
        Use enter_level(number=6), or move the cursor with act then press(key='confirm').
        """
        with output.lock:
            return board_reply(service.get_state())

    @server.tool(annotations=interactive)
    def act(
        actions: Annotated[list[Action], Field(min_length=1, max_length=64)]
        | Annotated[
            str,
            Field(
                max_length=256, description="Compact moves: R4 U2 Z; or full names: right up undo"
            ),
        ],
        view: View = "delta",
    ) -> CallToolResult:
        """Execute 1..64 planned moves, e.g. actions='R8 U2 Z', in one call.

        U/D/L/R move, W waits, Z undoes; full names such as 'right up undo'
        or a list ["right","up","undo"] also work. Never quote an entire JSON array.
        Batch safe travel together; use short batches near uncertain interactions.
        requested/executed count requested/processed commands, not successful movement.
        board_changed compares visible objects/rules/scene, not hidden engine state.
        controlled always contains current controller positions; stop_reason explains
        completion/interruption. With no ordinary control, directions/waits are not
        sent (executed=0, stop_reason=control_lost); start with Z to undo, or restart.
        Maps, LEVEL/EMPTY IS YOU, and AUTO are exempt from this guard. Batches stop
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
        world: str = "baba",
        query: str = "",
        limit: Annotated[int, Field(ge=1, le=100)] = 30,
        offset: Annotated[int, Field(ge=0)] = 0,
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
