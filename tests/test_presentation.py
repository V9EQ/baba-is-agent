import json

from conftest import make_state
from test_service import FakeBridge

from baba_is_agent.presentation import Presenter, compact_board, text_result
from baba_is_agent.service import GameService, parse_actions


def decode(result):
    assert result.structuredContent is None
    assert len(result.content) == 1
    return json.loads(result.content[0].text)


def test_reply_is_one_minified_copy():
    result = text_result({"value": [1, 2, 3]})
    content = result.content[0]
    assert content.type == "text"
    assert content.text == '{"value":[1,2,3]}'
    assert result.structuredContent is None


def test_delta_omits_unchanged_world():
    unit = {
        "id": 1,
        "name": "baba",
        "x": 2,
        "y": 3,
        "dir": 0,
        "type": "object",
        "properties": ["you"],
    }
    before = make_state(units=[unit])
    after = make_state(units=[dict(unit, x=3)])
    presenter = Presenter()
    presenter.render(before, "board")
    result = decode(presenter.render(after, "delta", executed=1))
    assert result == {
        "level": "0level",
        "menu": "ingame",
        "won": False,
        "executed": 1,
        "units": [[1, "baba", 3, 3, 0, ["you"]]],
        "phase": "puzzle",
        "ready": True,
        "paused": 0,
        "ignore": 0,
        "no_player": 0,
        "controller": "you",
        "controlled": [{"id": 1, "name": "baba", "x": 3, "y": 3, "direction": 0}],
        "can_undo": False,
    }
    assert "rules" not in result
    assert "frame" not in result


def test_level_changes_request_refresh_instead_of_dumping_new_board():
    presenter = Presenter()
    presenter.render(make_state(), "board")
    result = decode(presenter.render(make_state(level="1level"), "delta"))
    assert result["refresh"] == "get_board"
    assert "objects" not in result
    assert "units" not in result


def test_compact_board_keeps_inert_objects_and_coordinates():
    unit = {"id": 1, "name": "rock", "x": 2, "y": 3, "dir": 0, "type": "object", "properties": []}
    assert compact_board(make_state(units=[unit]))["objects"] == [
        {"name": "rock", "properties": [], "at": [[2, 3, 0, 1]]}
    ]


def test_board_is_self_describing_without_server_instructions():
    board = compact_board(make_state())
    legend = board["legend"]
    assert isinstance(legend, dict)
    assert legend["at"] == ["x", "y", "direction", "id"]
    directions = legend["directions"]
    assert isinstance(directions, dict)
    assert directions["idle"] == 4
    delta = legend["delta"]
    assert isinstance(delta, str)
    assert "Unmentioned state is unchanged" in delta


def test_compact_actions_are_expanded_once():
    assert parse_actions("R3 U2,Z") == ["right"] * 3 + ["up"] * 2 + ["undo"]


def test_engine_batch_has_one_ack_for_all_moves(settings):
    bridge = FakeBridge(make_state(capabilities=["batch"]), make_state(executed=8))
    result = GameService(settings, bridge=bridge).act("R8")
    assert result.executed == 8
    assert bridge.request.call_count == 2  # readiness + one batch, not eight snapshots
    bridge.request.assert_called_with("batch", actions=["right"] * 8)
