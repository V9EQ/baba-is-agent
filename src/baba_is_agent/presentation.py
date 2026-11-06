"""Small, single-copy MCP responses and state deltas for agent context efficiency."""

import json
from threading import Lock
from typing import Literal

from mcp.types import CallToolResult, TextContent

from baba_is_agent.feedback import control_context
from baba_is_agent.models import ActionResult, GameState, JsonObject, JsonValue

type View = Literal["delta", "summary", "board", "full"]
_STATUS = ("world", "level", "name", "menu", "selected", "won", "no_player", "auto")


def text_result(data: object) -> CallToolResult:
    """Avoid FastMCP's pretty-printed text plus duplicated structured state."""
    return CallToolResult(
        content=[
            TextContent(
                type="text", text=json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            )
        ],
    )


def compact_board(state: GameState, *, named_positions: bool = False) -> JsonObject:
    position_key = "positions" if named_positions else "at"
    groups: dict[tuple[str, tuple[str, ...], str, int], JsonObject] = {}
    for unit in state.units:
        key = (unit.name, tuple(unit.properties), unit.level, unit.completed)
        group = groups.setdefault(
            key, {"name": unit.name, "properties": list(unit.properties), position_key: []}
        )
        if unit.level:
            group.update(level=unit.level, completed=unit.completed)
        positions = group[position_key]
        assert isinstance(positions, list)
        positions.append(
            {"x": unit.x, "y": unit.y, "direction": unit.dir, "id": unit.id}
            if named_positions
            else [unit.x, unit.y, unit.dir, unit.id]
        )
    result = {key: getattr(state, key) for key in _STATUS}
    result["frame"] = state.frame
    result.update(control_context(state))
    result["legend"] = {
        "coordinates": "zero-based; x rightward, y downward",
        "at": ["x", "y", "direction", "id"],
        "delta_units": ["id", "name", "x", "y", "direction", "properties"],
        "directions": {"right": 0, "up": 1, "left": 2, "down": 3, "idle": 4},
        "delta": "Unmentioned state is unchanged; removed lists deleted IDs",
    }
    result["size"] = [getattr(state, "width", 0), getattr(state, "height", 0)]
    result["objects"] = list(groups.values())
    result["rules"] = [rule.model_dump(mode="json") for rule in state.rules]
    result["buttons"] = [button.model_dump(mode="json") for button in state.buttons]
    return result


def spatial_board(state: GameState) -> JsonObject:
    """A self-contained textual grid plus named positions; never hide inert objects."""
    board = compact_board(state, named_positions=True)
    width, height = getattr(state, "width", 0), getattr(state, "height", 0)
    cells: dict[tuple[int, int], list[str]] = {}
    for unit in state.units:
        label = unit.name[5:].upper() if unit.name.startswith("text_") else unit.name
        cells.setdefault((unit.x, unit.y), []).append(label)
    board["grid"] = [
        f"{y:02d} | " + " ".join("+".join(cells.get((x, y), [])) or "." for x in range(width))
        for y in range(height)
    ]
    board["columns"] = list(range(width))
    board["legend"] = {
        "coordinates": "zero-based; x rightward, y downward; row starts with y",
        "grid": "Space-separated cells; uppercase=word tile, lowercase=object, +=stack, .=empty",
        "directions": {"right": 0, "up": 1, "left": 2, "down": 3, "idle": 4},
    }
    return board


class Presenter:
    """Baseline belongs to the current MCP process; first deltas request a board refresh."""

    def __init__(self, *, spatial: bool = False) -> None:
        self.spatial = spatial
        self.lock = Lock()
        self.previous: GameState | None = None
        self.has_board = False

    def render(
        self,
        state: GameState,
        view: View,
        *,
        executed: int | None = None,
        action: ActionResult | None = None,
        map_info: JsonObject | None = None,
    ) -> CallToolResult:
        if view == "full":
            data = state.as_dict()
        elif view == "board":
            data = spatial_board(state) if self.spatial else compact_board(state)
            if self.spatial and self.previous and self.previous.level_key == state.level_key:
                old = {u.id: u for u in self.previous.units}
                changes: list[JsonValue] = [
                    {
                        "id": u.id,
                        "before": {
                            "name": old[u.id].name,
                            "properties": list(old[u.id].properties),
                        },
                        "after": {"name": u.name, "properties": list(u.properties)},
                    }
                    for u in state.units
                    if u.id in old
                    and (u.name != old[u.id].name or u.properties != old[u.id].properties)
                ]
                if changes:
                    data["changes_since_previous_reply"] = changes
        elif view == "summary":
            data = {key: getattr(state, key) for key in _STATUS}
        else:
            data = self._delta(state)
        data.update(control_context(state))
        if map_info is not None:
            data["map"] = map_info
        if executed is not None:
            data["executed"] = executed
        if action is not None:
            data.update(action.model_dump(mode="json", exclude={"state"}))
        if view != "summary":
            self.previous = state
        if view in {"board", "full"}:
            self.has_board = True
        return text_result(data)

    def _delta(self, state: GameState) -> JsonObject:
        previous = self.previous
        data: JsonObject = {"level": state.level, "menu": state.menu, "won": state.won}
        if not self.has_board or previous is None or previous.level_key != state.level_key:
            self.has_board = False
            data.update({key: getattr(state, key) for key in _STATUS})
            data["refresh"] = "get_board"
            return data
        for key in _STATUS:
            if getattr(state, key) != getattr(previous, key):
                data[key] = getattr(state, key)
        old_units = {unit.id: unit for unit in previous.units}
        new_ids = {unit.id for unit in state.units}
        changed: list[JsonValue] = []
        for unit in state.units:
            if old_units.get(unit.id) != unit:
                changed.append(
                    [unit.id, unit.name, unit.x, unit.y, unit.dir, list(unit.properties)]
                )
        removed: list[JsonValue] = [
            identifier for identifier in old_units if identifier not in new_ids
        ]
        if changed:
            data["units"] = changed
        if removed:
            data["removed"] = removed
        if state.rules != previous.rules:
            data["rules"] = [rule.model_dump(mode="json") for rule in state.rules]
        if state.buttons != previous.buttons:
            data["buttons"] = [button.model_dump(mode="json") for button in state.buttons]
        return data
