"""Validated wire models; unknown engine metadata is preserved."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

type Action = Literal["up", "down", "left", "right", "wait", "undo"]
type Key = Literal[
    "up", "down", "left", "right", "wait", "undo", "restart", "confirm", "escape", "space"
]
type Direction = Literal["up", "down", "left", "right", "idle"]
type Operation = Literal["state", "move", "undo", "restart", "batch"]
type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


class WireModel(BaseModel):
    """Do not discard fields added by the game's telemetry bridge."""

    model_config = ConfigDict(extra="allow", strict=True)


class Unit(WireModel):
    id: int
    name: str
    x: int
    y: int
    dir: int
    type: str
    properties: list[str]
    level: str = ""
    completed: int = 0


class Rule(WireModel):
    words: list[str]
    conditions: list[JsonValue]


class Button(WireModel):
    name: str
    text: str
    disabled: int
    x: int
    y: int


class GameState(WireModel):
    protocol: Literal[2]
    request_id: str
    capabilities: list[str] = Field(default_factory=list)
    executed: int = 0
    frame: int
    units: list[Unit]
    rules: list[Rule]
    buttons: list[Button]
    menu: str = ""
    world: str = ""
    level: str = ""
    name: str = ""
    paused: int = 0
    ignore: int = 0
    no_player: int = 0
    auto: int = 0
    won: bool = False
    wins: int = 0
    turns: int = 0
    undo_depth: int = 0
    menu_x: int = 0
    menu_y: int = 0
    selected: str = ""
    menu_structure: list[JsonValue] = Field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.menu == "ingame" and not self.paused and not self.ignore and not self.won

    @property
    def level_key(self) -> tuple[str, str]:
        return self.world, self.level

    def as_dict(self) -> JsonObject:
        """Return JSON-compatible data, including extension fields."""
        return self.model_dump(mode="json")


class ActionResult(BaseModel):
    executed: int
    state: GameState
