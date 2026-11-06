import asyncio
from dataclasses import replace
from unittest.mock import Mock, call, patch

import pytest
from conftest import make_state
from test_feedback import CURSOR, PLAYER
from test_service import FakeBridge

from baba_is_agent.errors import GameActionError
from baba_is_agent.navigation import cursor_position, map_levels, map_route
from baba_is_agent.server import create_server
from baba_is_agent.service import GameService


@pytest.fixture
def map_state(settings):
    directory = settings.game_dir / "Data/Worlds/baba"
    directory.mkdir(parents=True)
    (directory / "map.ld").write_text(
        "[levels]\n0file=target\n0name=100% Baba\n0number=6\n0style=0\n0X=2\n0Y=0\n"
        "1file=stale\n1number=6\n1X=8\n1Y=0\n"
    )
    return make_state(
        level="map",
        units=[
            dict(CURSOR, x=0, y=0),
            dict(PLAYER, id=2, name="level", level="target", properties=[], completed=2, x=2, y=0),
            dict(PLAYER, id=3, name="line", properties=[], completed=3, x=1, y=0),
        ],
    )


def moved(state, x):
    return state.model_copy(
        update={
            "units": [
                u.model_copy(update={"x": x}) if "select" in u.properties else u
                for u in state.units
            ]
        }
    )


def test_map_labels_join_live_units_not_stale_metadata(settings, map_state):
    entries = map_levels(settings, map_state)
    assert len(entries) == 1
    assert entries[0].number == 6 and entries[0].available
    assert entries[0].level == "target" and entries[0].name == "100% Baba"
    assert entries[0].x == 2


@pytest.mark.parametrize("native", [False, True])
def test_enter_uses_native_travel_and_one_intro_confirmation(settings, map_state, native):
    initial = map_state.model_copy(update={"capabilities": ["batch"] if native else []})
    intro = make_state(level="target", menu="levelintro")
    puzzle = make_state(level="target", units=[PLAYER])
    states = (
        [initial, moved(initial, 2)] if native else [initial, moved(initial, 1), moved(initial, 2)]
    )
    bridge = FakeBridge(*states, intro, puzzle)
    keyboard = Mock()
    with patch("baba_is_agent.service.time.sleep"):
        result = GameService(settings, bridge=bridge, keyboard=keyboard).enter_level(6)
    assert result.level == "target"
    assert bridge.entered == 1
    assert keyboard.press.call_args_list == [call("confirm"), call("confirm")]
    assert bridge.request.call_args_list[1] == (
        call("batch", actions=["right", "right"]) if native else call("move", "right")
    )


@pytest.mark.parametrize("reason", ["locked", "missing", "ambiguous", "disconnected", "extra"])
def test_unavailable_targets_never_move_or_confirm(settings, map_state, reason):
    state = map_state
    if reason == "locked":
        state = state.model_copy(
            update={
                "units": [
                    u.model_copy(update={"completed": 1}) if u.level else u for u in state.units
                ]
            }
        )
    elif reason == "disconnected":
        state = state.model_copy(update={"units": [u for u in state.units if u.name != "line"]})
    elif reason in {"ambiguous", "extra"}:
        metadata = settings.game_dir / "Data/Worlds/baba/map.ld"
        with metadata.open("a") as f:
            f.write(
                "2file=target\n2number=6\n2style=0\n2X=2\n2Y=0\n"
                if reason == "ambiguous"
                else "0style=1\n"
            )
    bridge = FakeBridge(state)
    keyboard = Mock()
    with pytest.raises(GameActionError):
        GameService(settings, bridge=bridge, keyboard=keyboard).enter_level(
            99 if reason == "missing" else 6
        )
    assert bridge.request.call_count == 1
    keyboard.press.assert_not_called()


def test_unexpected_cursor_position_never_confirms(settings, map_state):
    bridge = FakeBridge(
        map_state.model_copy(update={"capabilities": ["batch"]}), moved(map_state, 1)
    )
    keyboard = Mock()
    with pytest.raises(GameActionError, match="no confirm"):
        GameService(settings, bridge=bridge, keyboard=keyboard).enter_level(6)
    keyboard.press.assert_not_called()


def test_entry_timeout_never_retries_confirm(settings, map_state):
    bridge = FakeBridge(moved(map_state, 2))
    keyboard = Mock()
    with (
        patch("baba_is_agent.service.time.monotonic", side_effect=[0, 1]),
        pytest.raises(GameActionError, match="Do not blindly retry"),
    ):
        GameService(settings, bridge=bridge, keyboard=keyboard).enter_level(6)
    keyboard.press.assert_called_once_with("confirm")


def test_route_is_bounded_and_metadata_paths_are_validated(settings, map_state):
    target = replace(map_levels(settings, map_state)[0], x=65)
    long_map = make_state(
        units=[dict(CURSOR, x=0, y=0)]
        + [
            dict(PLAYER, id=x + 1, name="line", properties=[], completed=3, x=x, y=0)
            for x in range(1, 66)
        ]
    )
    with pytest.raises(GameActionError, match="64"):
        map_route(long_map, target)
    with pytest.raises(GameActionError, match="identifier"):
        map_levels(settings, map_state.model_copy(update={"world": "../other"}))


def test_wrong_scene_after_confirm_stops_without_more_input(settings, map_state):
    bridge = FakeBridge(moved(map_state, 2), make_state(level="unexpected"))
    keyboard = Mock()
    with pytest.raises(GameActionError, match="Unexpected level"):
        GameService(settings, bridge=bridge, keyboard=keyboard).enter_level(6)
    keyboard.press.assert_called_once_with("confirm")


def test_puzzle_or_multiple_cursors_refused():
    for units in [[PLAYER], [CURSOR, dict(CURSOR, id=2)]]:
        with pytest.raises(GameActionError, match="map"):
            cursor_position(make_state(units=units))


def test_observe_includes_map_numbers_and_survives_missing_metadata(settings, map_state):
    async def exercise():
        service = GameService(settings, bridge=FakeBridge(map_state, map_state))
        server = create_server(service)
        result = await server.call_tool("observe", {})
        assert "100% Baba" in str(result) and "number" in str(result)
        (settings.game_dir / "Data/Worlds/baba/map.ld").unlink()
        result = await server.call_tool("observe", {})
        assert "numbering metadata unavailable" in str(result)
        assert "objects" in str(result)

    asyncio.run(exercise())
