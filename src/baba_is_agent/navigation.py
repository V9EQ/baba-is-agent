"""Read map labels and plan only cursor travel, never puzzle solutions or unlocks."""

import configparser
import re
from collections import deque
from dataclasses import dataclass
from typing import Literal

from baba_is_agent.config import Settings
from baba_is_agent.errors import GameActionError
from baba_is_agent.models import GameState

type MapMove = Literal["up", "down", "left", "right"]


@dataclass(frozen=True)
class MapLevel:
    number: int | None
    style: int
    level: str
    name: str
    x: int
    y: int
    available: bool
    completed: int


def map_levels(settings: Settings, state: GameState) -> list[MapLevel]:
    if not any("select" in u.properties for u in state.units):
        return []
    if any(re.fullmatch(r"[a-zA-Z0-9_-]+", value) is None for value in state.level_key):
        raise GameActionError("Invalid world/map identifier")
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.read(
        settings.game_dir / "Data/Worlds" / state.world / f"{state.level}.ld", encoding="utf-8-sig"
    )
    if not parser.has_section("levels"):
        raise GameActionError(
            "Map numbering metadata unavailable; use the cursor and press(confirm)."
        )
    live = {(u.level, u.x, u.y): u for u in state.units if u.level}
    result = []
    for key, filename in parser.items("levels"):
        match = re.fullmatch(r"(\d+)file", key)
        if not match:
            continue
        prefix = match[1]
        x = parser.getint("levels", prefix + "x", fallback=-1)
        y = parser.getint("levels", prefix + "y", fallback=-1)
        unit = live.get((filename, x, y))
        if unit is not None:
            result.append(
                MapLevel(
                    number=parser.getint("levels", prefix + "number", fallback=None),
                    style=parser.getint("levels", prefix + "style", fallback=0),
                    level=filename,
                    name=parser.get("levels", prefix + "name", fallback=filename),
                    x=x,
                    y=y,
                    available=unit.completed > 1,
                    completed=unit.completed,
                )
            )
    return result


def cursor_position(state: GameState) -> tuple[int, int]:
    cursors = [u for u in state.units if "select" in u.properties]
    if (
        not state.ready
        or len(cursors) != 1
        or any({"you", "you2"}.intersection(u.properties) for u in state.units)
    ):
        raise GameActionError("Expected a ready map with exactly one SELECT cursor, not a puzzle.")
    return cursors[0].x, cursors[0].y


def map_route(state: GameState, target: MapLevel) -> list[MapMove]:
    start, goal = cursor_position(state), (target.x, target.y)
    # Native mapcursor_move accepts adjacent targets with COMPLETED > 1.
    # Visibility and unusual rules are still checked by the engine, not bypassed.
    cells = {(u.x, u.y) for u in state.units if u.completed > 1}
    queue: deque[tuple[tuple[int, int], list[MapMove]]] = deque([(start, [])])
    seen = {start}
    directions: list[tuple[int, int, MapMove]] = [
        (1, 0, "right"),
        (0, 1, "down"),
        (-1, 0, "left"),
        (0, -1, "up"),
    ]
    while queue:
        (x, y), route = queue.popleft()
        if (x, y) == goal:
            return route
        if len(route) >= 64:
            continue
        for dx, dy, action in directions:
            cell = x + dx, y + dy
            if cell in cells and cell not in seen:
                seen.add(cell)
                queue.append((cell, [*route, action]))
    raise GameActionError("No accessible map route within 64 moves; move the cursor manually.")
