from contextlib import contextmanager
from unittest.mock import Mock, call, patch

import pytest
from conftest import make_state

from baba_is_agent.errors import GameActionError
from baba_is_agent.presentation import compact_board
from baba_is_agent.service import GameService, parse_actions


class FakeBridge:
    def __init__(self, *states):
        self.request = Mock(side_effect=states)
        self.entered = 0

    @contextmanager
    def session(self):
        self.entered += 1
        yield self


@pytest.mark.parametrize(
    "actions", [[], ["quit"], ["left"] * 65, "select", "R65", "up " * 65, '["up"]', "up R2"]
)
def test_action_validation(settings, actions):
    bridge = FakeBridge()
    with pytest.raises(ValueError):
        GameService(settings, bridge=bridge).act(actions)
    bridge.request.assert_not_called()


@pytest.mark.parametrize(
    "changes", [{"won": True}, {"menu": "pause"}, {"paused": 1}, {"ignore": 1}]
)
def test_no_moves_when_not_ready(settings, changes):
    bridge = FakeBridge(make_state(**changes))
    with pytest.raises(GameActionError):
        GameService(settings, bridge=bridge).act(["left"])
    assert bridge.request.call_count == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"won": True},
        {"wins": 1},
        {"menu": "pause"},
        {"level": "1level"},
        {"no_player": 1},
        {"ignore": 1},
    ],
)
def test_batch_stops_on_game_event(settings, changes):
    player = {
        "id": 1,
        "name": "baba",
        "x": 2,
        "y": 3,
        "dir": 0,
        "type": "object",
        "properties": ["you"],
    }
    bridge = FakeBridge(make_state(units=[player]), make_state(**changes))
    result = GameService(settings, bridge=bridge).act(["right"] * 8)
    assert result.executed == 1
    assert bridge.request.call_args == call("move", "right")
    assert bridge.entered == 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("down", ["down"]),
        (" WAIT ", ["wait"]),
        ("right, up undo", ["right", "up", "undo"]),
        ("R2 U Z", ["right", "right", "up", "undo"]),
    ],
)
def test_action_names_and_compact_notation(text, expected):
    assert parse_actions(text) == expected


def test_invalid_actions_give_a_concrete_correction_before_any_request(settings):
    bridge = FakeBridge()
    with pytest.raises(ValueError, match='actions="R4 U2 Z"'):
        GameService(settings, bridge=bridge).act("select")
    bridge.request.assert_not_called()


def test_wait_and_undo_are_native_operations(settings):
    bridge = FakeBridge(make_state(), make_state(), make_state())
    result = GameService(settings, bridge=bridge).act(["wait", "undo"])
    assert result.executed == 2
    assert bridge.request.call_args_list == [call(), call("move", "idle"), call("undo")]


def test_compact_board_preserves_units_without_mutation(settings):
    unit = {
        "id": 1,
        "name": "wall",
        "x": 2,
        "y": 3,
        "dir": 0,
        "type": "object",
        "properties": ["stop"],
    }
    state = make_state(units=[unit, dict(unit, id=2, x=4)])
    service = GameService(settings, bridge=FakeBridge(state))
    compact = compact_board(service.get_state())
    assert "units" not in compact
    assert compact["objects"] == [
        {"name": "wall", "properties": ["stop"], "at": [[2, 3, 0, 1], [4, 3, 0, 2]]}
    ]
    assert len(state.units) == 2


def test_press_checks_telemetry_before_keyboard(settings):
    keyboard = Mock()
    bridge = FakeBridge(GameActionError("not connected"))
    with pytest.raises(GameActionError):
        GameService(settings, bridge=bridge, keyboard=keyboard).press("confirm")
    keyboard.press.assert_not_called()


def test_choose_menu_navigates_and_confirms(settings):
    button = {"name": "resume", "text": "Resume", "disabled": 0, "x": 0, "y": 1}
    first = make_state(menu="pause", buttons=[button], selected="return")
    selected = first.model_copy(update={"selected": "resume", "menu_y": 1})
    bridge = FakeBridge(first, selected, make_state())
    keyboard = Mock()
    with patch("baba_is_agent.service.time.sleep"):
        result = GameService(settings, bridge=bridge, keyboard=keyboard).choose_menu("resume")
    assert result.menu == "ingame"
    assert keyboard.press.call_args_list == [call("down"), call("confirm")]


def test_disabled_button_is_not_activated(settings):
    button = {"name": "quit", "text": "Quit", "disabled": 1, "x": 0, "y": 0}
    keyboard = Mock()
    bridge = FakeBridge(make_state(menu="main", buttons=[button]))
    with pytest.raises(GameActionError, match="Enabled button"):
        GameService(settings, bridge=bridge, keyboard=keyboard).choose_menu("quit")
    keyboard.press.assert_not_called()


@pytest.mark.parametrize("world", ["../baba", "/tmp", "", "мир"])
def test_world_paths_are_validated(settings, world):
    with pytest.raises(ValueError):
        GameService(settings).list_levels(world)


def test_level_metadata_is_not_interpolated(settings):
    directory = settings.game_dir / "Data/Worlds/baba"
    directory.mkdir(parents=True)
    (directory / "0level.ld").write_text(
        "[general]\nname=100% Baba\nsubtitle=Test\n", encoding="utf-8-sig"
    )
    assert GameService(settings).list_levels() == [
        {"id": "0level", "name": "100% Baba", "subtitle": "Test"}
    ]
