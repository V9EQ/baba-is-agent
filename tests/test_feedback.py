import pytest
from conftest import make_state
from test_presentation import decode
from test_service import FakeBridge

from baba_is_agent.feedback import action_result, control_context
from baba_is_agent.presentation import Presenter
from baba_is_agent.service import GameService

PLAYER = {
    "id": 1,
    "name": "baba",
    "x": 2,
    "y": 3,
    "dir": 0,
    "type": "object",
    "properties": ["you"],
}
CURSOR = dict(PLAYER, name="cursor", properties=["select"])


@pytest.mark.parametrize(
    ("changes", "phase", "controller"),
    [
        ({"units": [PLAYER]}, "puzzle", "you"),
        ({"units": [dict(PLAYER, properties=["you2"])]}, "puzzle", "you2"),
        ({"units": [CURSOR], "no_player": 1}, "map", "cursor"),
        ({"menu": "levelintro"}, "intro", "none"),
        ({"menu": "pause"}, "menu", "none"),
        ({"paused": 1}, "menu", "none"),
        ({"auto": 1}, "auto", "none"),
        ({"rules": [{"words": ["empty", "is", "you"], "conditions": []}]}, "puzzle", "special"),
        ({"rules": [{"words": ["level", "is", "you2"], "conditions": []}]}, "puzzle", "special"),
    ],
)
def test_control_context(changes, phase, controller):
    status = control_context(make_state(**changes))
    assert status["phase"] == phase
    assert status["controller"] == controller


def test_unchanged_deltas_keep_control_positions_and_recovery():
    presenter = Presenter()
    alive = make_state(units=[PLAYER])
    presenter.render(alive, full=True)
    assert decode(presenter.render(alive))["controlled"][0]["x"] == 2
    dead = make_state(no_player=1, undo_depth=1)
    presenter.render(dead)
    repeated = decode(presenter.render(dead))
    assert repeated["no_player"] == 1
    assert repeated["controlled"] == []
    assert repeated["can_undo"]
    assert "undo()" in repeated["recovery_hint"]


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({}, "completed"),
        ({"won": True}, "win"),
        ({"wins": 1, "level": "map"}, "win"),
        ({"level": "map"}, "transition"),
        ({"paused": 1}, "not_ready"),
        ({"units": [], "no_player": 1}, "control_lost"),
        ({"units": [CURSOR], "no_player": 1}, "control_changed"),
    ],
)
def test_action_stop_reasons(changes, reason):
    initial = make_state(units=[PLAYER])
    current = make_state(**(initial.as_dict() | changes))
    result = action_result(initial, current, 1, 1)
    assert result.stop_reason == reason


def test_board_change_ignores_transport_counters_and_unit_order():
    initial = make_state(units=[PLAYER, dict(PLAYER, id=2)])
    current = make_state(units=list(reversed(initial.units)), frame=100, turns=50, undo_depth=3)
    assert not action_result(initial, current, 8, 8).board_changed
    moved = make_state(units=[dict(PLAYER, x=3)])
    assert action_result(initial, moved, 8, 8).board_changed


@pytest.mark.parametrize("native", [False, True])
def test_action_metadata_reaches_board_and_delta(settings, native):
    initial = make_state(units=[PLAYER], capabilities=["batch"] if native else [])
    dead = make_state(no_player=1, executed=1, undo_depth=1)
    result = GameService(settings, bridge=FakeBridge(initial, dead)).act("R6")
    presenter = Presenter()
    for full in [True, False]:
        reply = decode(presenter.render(result.state, full=full, action=result))
        assert reply["requested"] == 6
        assert reply["executed"] == 1
        assert reply["stop_reason"] == "control_lost"
        assert reply["board_changed"]
        assert reply["controlled"] == []
        assert "state" not in reply
