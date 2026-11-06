"""One exact board representation and small changes in the same coordinate format."""

import json
from threading import Lock

from mcp.types import CallToolResult, TextContent

from baba_is_agent.feedback import control_context
from baba_is_agent.models import ActionResult, GameState, JsonObject, JsonValue, Unit

_STATUS = ("world", "level", "name", "menu", "selected", "won", "auto")


def text_result(data: object) -> CallToolResult:
    """Send one minified copy, not text plus duplicated structured state."""
    return CallToolResult(
        content=[
            TextContent(
                type="text", text=json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            )
        ]
    )


def group_units(units: list[Unit]) -> list[JsonValue]:
    groups: dict[tuple[str, tuple[str, ...], str, int], JsonObject] = {}
    for unit in units:
        key = (unit.name, tuple(unit.properties), unit.level, unit.completed)
        group = groups.setdefault(
            key, {"name": unit.name, "properties": list(unit.properties), "at": []}
        )
        if unit.level:
            group.update(level=unit.level, completed=unit.completed)
        positions = group["at"]
        assert isinstance(positions, list)
        positions.append([unit.x, unit.y, unit.dir, unit.id])
    return list(groups.values())


def compact_board(state: GameState) -> JsonObject:
    return {
        "frame": state.frame,
        "size": [getattr(state, "width", 0), getattr(state, "height", 0)],
        "legend": {
            "coordinates": "zero-based; x rightward, y downward",
            "at": ["x", "y", "direction", "id"],
            "directions": {"right": 0, "up": 1, "left": 2, "down": 3, "idle": 4},
            "delta": "changed contains only changed units, not whole groups; removed lists deleted IDs; unmentioned state is unchanged",
        },
        "objects": group_units(state.units),
        "rules": [rule.model_dump(mode="json") for rule in state.rules],
        "buttons": [button.model_dump(mode="json") for button in state.buttons],
    }


class Presenter:
    """A baseline per MCP process. First reply and new scenes always include a board."""

    def __init__(self) -> None:
        self.lock = Lock()
        self.previous: GameState | None = None

    def needs_board(self, state: GameState) -> bool:
        old = self.previous
        return (
            old is None
            or old.level_key != state.level_key
            or any(getattr(old, key, 0) != getattr(state, key, 0) for key in ("width", "height"))
            or (state.menu == "ingame" and old.menu != "ingame")
        )

    def render(
        self,
        state: GameState,
        *,
        full: bool = False,
        action: ActionResult | None = None,
        map_info: JsonObject | None = None,
    ) -> CallToolResult:
        full = full or self.needs_board(state)
        data: JsonObject = {key: getattr(state, key) for key in _STATUS}
        data.update(control_context(state))
        data["kind"] = "board" if full else "delta"
        if full:
            data.update(compact_board(state))
        else:
            old = self.previous
            assert old is not None
            old_units = {u.id: u for u in old.units}
            changed = [u for u in state.units if old_units.get(u.id) != u]
            if changed:
                data["changed"] = group_units(changed)
            removed: list[JsonValue] = [
                identifier for identifier in sorted(set(old_units) - {u.id for u in state.units})
            ]
            if removed:
                data["removed"] = removed
            effects: list[JsonValue] = [
                {
                    "id": u.id,
                    "was": old_units[u.id].name,
                    "now": u.name,
                    "gained": list(sorted(set(u.properties) - set(old_units[u.id].properties))),
                    "lost": list(sorted(set(old_units[u.id].properties) - set(u.properties))),
                }
                for u in changed
                if u.id in old_units
                and (u.name != old_units[u.id].name or u.properties != old_units[u.id].properties)
            ]
            if effects:
                data["effects"] = effects
            if state.rules != old.rules:
                data["rules"] = [rule.model_dump(mode="json") for rule in state.rules]
            if state.buttons != old.buttons:
                data["buttons"] = [button.model_dump(mode="json") for button in state.buttons]
        if map_info is not None:
            data["map"] = map_info
        if action is not None:
            data.update(action.model_dump(mode="json", exclude={"state"}))
        self.previous = state
        return text_result(data)
