"""Game operations independent of MCP registration and CLI argument handling."""

import configparser
import re
import shutil
import subprocess
import time
from typing import cast

from baba_is_agent.config import STEAM_APP_ID, Settings
from baba_is_agent.errors import BabaError, GameActionError
from baba_is_agent.feedback import action_result, ordinary_control_lost
from baba_is_agent.input import Keyboard, LinuxKeyboard
from baba_is_agent.models import Action, ActionResult, GameState, JsonObject, Key
from baba_is_agent.navigation import cursor_position, map_levels, map_route
from baba_is_agent.transport import BridgeClient, BridgeGateway

_ACTIONS = frozenset({"up", "down", "left", "right", "wait", "undo"})
_KEYS = _ACTIONS | {"restart", "confirm", "escape", "space"}


def parse_actions(actions: list[Action] | str) -> list[Action]:
    """Accept explicit actions, full names, or compact runs such as 'R8 U2 L3 Z'."""
    if isinstance(actions, str):
        names = re.split(r"[\s,]+", actions.strip().lower())
        if all(name in _ACTIONS for name in names):
            actions = [cast(Action, name) for name in names]
    if isinstance(actions, str):
        compact = re.sub(r"[\s,]+", "", actions.upper())
        if not re.fullmatch(r"(?:[UDLRWZ][0-9]*)+", compact) or len(compact) > 256:
            raise ValueError(
                'Invalid actions. Use actions="R4 U2 Z", actions="right up undo", '
                'or actions=["right","up","undo"] (1..64 commands). '
                'To enter a map level use enter_level(number=6) or press(key="confirm"), not select.'
            )
        mapping: dict[str, Action] = {
            "U": "up",
            "D": "down",
            "L": "left",
            "R": "right",
            "W": "wait",
            "Z": "undo",
        }
        expanded: list[Action] = []
        for match in re.finditer(r"([UDLRWZ])([0-9]*)", compact):
            count = int(match[2] or "1")
            if count < 1 or len(expanded) + count > 64:
                raise ValueError(
                    'Expected 1..64 total actions, e.g. actions="R4 U2". Split longer routes; no commands were sent.'
                )
            expanded.extend([mapping[match[1]]] * count)
        actions = expanded
    if not 1 <= len(actions) <= 64 or any(action not in _ACTIONS for action in actions):
        raise ValueError(
            'Expected 1..64 actions: up, down, left, right, wait, undo; e.g. actions=["up","right"]. No commands were sent.'
        )
    return actions


class GameService:
    """One game, one serialized input stream, and no screenshot dependencies."""

    def __init__(
        self,
        settings: Settings,
        *,
        bridge: BridgeGateway | None = None,
        keyboard: Keyboard | None = None,
    ) -> None:
        self.settings = settings
        self.bridge = bridge if bridge is not None else BridgeClient(settings)
        self.keyboard = keyboard if keyboard is not None else LinuxKeyboard()

    def get_state(self) -> GameState:
        with self.bridge.session() as session:
            return session.request()

    def get_board(self) -> JsonObject:
        """Group units by name and properties without losing their coordinates or IDs."""
        state = self.get_state()
        result = state.as_dict()
        del result["units"]
        groups: dict[tuple[str, tuple[str, ...], str, int], JsonObject] = {}
        for unit in state.units:
            key = (unit.name, tuple(unit.properties), unit.level, unit.completed)
            if key not in groups:
                group: JsonObject = {
                    "name": unit.name,
                    "properties": list(unit.properties),
                    "positions": [],
                }
                if unit.level:
                    group.update(level=unit.level, completed=unit.completed)
                groups[key] = group
            positions = groups[key]["positions"]
            assert isinstance(positions, list)
            positions.append([unit.x, unit.y, unit.dir, unit.id])
        result["objects"] = list(groups.values())
        return result

    def act(self, actions: list[Action] | str) -> ActionResult:
        """One engine-side batch when supported; fall back for an older installed mod."""
        actions = parse_actions(actions)
        with self.bridge.session() as session:
            initial = session.request()
            if not initial.ready:
                raise GameActionError("Not ready for gameplay. Inspect state or use menu input.")
            if actions[0] != "undo" and ordinary_control_lost(initial):
                return ActionResult(
                    state=initial,
                    requested=len(actions),
                    executed=0,
                    stop_reason="control_lost",
                    board_changed=False,
                )
            if "batch" in initial.capabilities:
                # Verify recovery before sending directions. A batch starting without
                # YOU cannot otherwise detect a later death using its initial baseline.
                undo_count = next(
                    (i for i, action in enumerate(actions) if action != "undo"), len(actions)
                )
                current = initial
                executed = 0
                if undo_count:
                    current = session.request("batch", actions=["undo"] * undo_count)
                    executed = current.executed
                    if (
                        executed != undo_count
                        or undo_count == len(actions)
                        or not current.ready
                        or current.level_key != initial.level_key
                        or current.wins != initial.wins
                        or ordinary_control_lost(current)
                    ):
                        return action_result(initial, current, len(actions), executed)
                native_actions = [
                    "idle" if action == "wait" else action for action in actions[undo_count:]
                ]
                current = session.request("batch", actions=native_actions)
                return action_result(initial, current, len(actions), executed + current.executed)
            expects_player = any(
                {"you", "you2"}.intersection(unit.properties) for unit in initial.units
            )
            current = initial
            executed = 0
            for action in actions:
                if action != "undo" and ordinary_control_lost(current):
                    break
                if action == "undo":
                    current = session.request("undo")
                else:
                    direction = "idle" if action == "wait" else action
                    current = session.request("move", direction)
                executed += 1
                expects_player = expects_player or any(
                    {"you", "you2"}.intersection(unit.properties) for unit in current.units
                )
                if (
                    not current.ready
                    or (current.no_player and expects_player)
                    or current.wins != initial.wins
                    or current.level_key != initial.level_key
                ):
                    break
        return action_result(initial, current, len(actions), executed)

    def press(self, key: Key) -> GameState:
        """Native keyboard input for menus and realtime/AUTO levels, not exact turns."""
        if key not in _KEYS:
            raise ValueError(f"Unsupported key: {key}")
        with self.bridge.session() as session:
            session.request()  # Refuse input when telemetry is unavailable.
            self.keyboard.press(key)
            return session.request()

    def choose_menu(self, name: str) -> GameState:
        """Navigate to a reported enabled button using ordinary keyboard events."""
        with self.bridge.session() as session:
            state = session.request()
            menu = state.menu
            button = next((b for b in state.buttons if b.name == name and not b.disabled), None)
            if button is None:
                raise GameActionError("Enabled button not found. Inspect get_state().buttons.")
            for _ in range(32):
                if state.menu != menu:
                    raise GameActionError(
                        "Menu changed during navigation. Inspect state before retrying."
                    )
                if state.selected == name:
                    self.keyboard.press("confirm")
                    time.sleep(0.35)
                    return session.request()
                dx, dy = button.x - state.menu_x, button.y - state.menu_y
                if dy:
                    direction = "down" if dy > 0 else "up"
                elif dx:
                    direction = "right" if dx > 0 else "left"
                else:
                    raise GameActionError(
                        "Button coordinates match but selection differs. Inspect state."
                    )
                self.keyboard.press(direction)
                state = session.request()
        raise GameActionError("Menu navigation exceeded 32 steps. Inspect state before retrying.")

    def restart_level(self) -> GameState:
        with self.bridge.session() as session:
            session.request("restart")
            time.sleep(0.8)
            return session.request()

    def list_levels(self, world: str = "baba") -> list[JsonObject]:
        """Read metadata only; never unlock, load, or modify a level."""
        if re.fullmatch(r"[a-zA-Z0-9_-]+", world, flags=re.ASCII) is None:
            raise ValueError("World names must contain only ASCII letters, numbers, '_' or '-'")
        result: list[JsonObject] = []
        for path in sorted((self.settings.game_dir / "Data/Worlds" / world).glob("*.ld")):
            parser = configparser.ConfigParser(strict=False, interpolation=None)
            parser.read(path, encoding="utf-8-sig")
            if parser.has_section("general"):
                result.append(
                    {
                        "id": path.stem,
                        "name": parser.get("general", "name", fallback=""),
                        "subtitle": parser.get("general", "subtitle", fallback=""),
                    }
                )
        return result

    def enter_level(self, number: int) -> GameState:
        """Walk an accessible numbered map route and confirm; never load or unlock directly."""
        with self.bridge.session() as session:
            state = session.request()
            cursor_position(state)
            matches = [
                entry
                for entry in map_levels(self.settings, state)
                if entry.number == number and entry.style == 0
            ]
            if len(matches) != 1 or not matches[0].available:
                raise GameActionError(
                    "Numbered level unavailable or ambiguous on this map; inspect the board."
                )
            target = matches[0]
            origin = state.level_key
            route = map_route(state, target)
            if route and "batch" in state.capabilities:
                state = session.request("batch", actions=list(route))
            else:
                for action in route:
                    state = session.request("move", action)
                    if state.level_key != origin or not state.ready:
                        raise GameActionError(
                            "Map changed during travel; inspect before retrying."
                        )
            if state.level_key != origin or cursor_position(state) != (target.x, target.y):
                raise GameActionError(
                    "Cursor did not reach the target; no confirm sent. Inspect the board."
                )
            self.keyboard.press("confirm")
            deadline = time.monotonic() + self.settings.request_timeout
            dismissed_intro = False
            while time.monotonic() < deadline:
                state = session.request()
                if state.level_key not in {origin, (origin[0], target.level)}:
                    raise GameActionError("Unexpected level transition; inspect before retrying.")
                if state.level_key == (origin[0], target.level):
                    if state.menu == "levelintro" and not dismissed_intro:
                        self.keyboard.press("confirm")
                        dismissed_intro = True
                    elif state.ready and not any("select" in u.properties for u in state.units):
                        return state
                time.sleep(self.settings.poll_interval)
        raise GameActionError(
            "Level entry not settled; inspect the board. Do not blindly retry confirm."
        )

    def launch_game(self) -> JsonObject:
        steam = shutil.which("steam")
        if steam is None:
            raise BabaError("Steam executable not found on PATH")
        subprocess.Popen(
            [steam, "-applaunch", STEAM_APP_ID],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"launched": True, "note": "Wait for startup, then inspect get_state()."}

    def close(self) -> None:
        self.keyboard.close()
