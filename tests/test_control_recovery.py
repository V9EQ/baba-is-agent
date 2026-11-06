import pytest
from conftest import make_state
from test_feedback import CURSOR, PLAYER
from test_presentation import decode
from test_service import FakeBridge

from baba_is_agent.presentation import Presenter
from baba_is_agent.service import GameService


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("moves", ["R8", "W4", "R Z"])
def test_no_direction_commands_sent_without_ordinary_control(settings, native, moves):
    dead = make_state(no_player=1, undo_depth=1, capabilities=["batch"] if native else [])
    bridge = FakeBridge(dead)
    result = GameService(settings, bridge=bridge).act(moves)
    assert bridge.request.call_count == 1  # Telemetry only, no mutation.
    assert result.executed == 0
    assert result.stop_reason == "control_lost"
    assert not result.board_changed
    reply = decode(Presenter().render(result.state, action=result))
    assert "undo()" in reply["recovery_hint"]


@pytest.mark.parametrize("native", [False, True])
def test_repeated_calls_after_death_are_blocked(settings, native):
    alive = make_state(units=[PLAYER], capabilities=["batch"] if native else [])
    dead = make_state(no_player=1, undo_depth=1, executed=1, capabilities=alive.capabilities)
    bridge = FakeBridge(alive, dead, dead, dead)
    service = GameService(settings, bridge=bridge)
    first = service.act("R6")
    assert first.executed == 1
    assert first.stop_reason == "control_lost"
    for _ in range(2):
        result = service.act("D8")
        assert result.executed == 0
        assert result.stop_reason == "control_lost"
    assert bridge.request.call_count == 4  # Three initial reads and one mutation.


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize(
    "changes",
    [
        {"units": [CURSOR]},
        {"units": [PLAYER]},  # NOPLAYER may lag; an actual controller wins.
        {"rules": [{"words": ["level", "is", "you"], "conditions": []}]},
        {"rules": [{"words": ["empty", "is", "you2"], "conditions": []}]},
        {"auto": 1},  # Let the bridge report the realtime-input requirement.
    ],
)
def test_guard_exempts_other_control_modes(settings, native, changes):
    state = make_state(no_player=1, capabilities=["batch"] if native else [], **changes)
    after = state.model_copy(update={"executed": 1})
    bridge = FakeBridge(state, after)
    assert GameService(settings, bridge=bridge).act("R").executed == 1
    assert bridge.request.call_count == 2


@pytest.mark.parametrize("native", [False, True])
def test_undo_is_allowed_and_verified_before_directions(settings, native):
    dead = make_state(no_player=1, undo_depth=1, capabilities=["batch"] if native else [])
    restored = make_state(units=[PLAYER], executed=1)
    moved = make_state(units=[dict(PLAYER, x=3)], executed=1)
    bridge = FakeBridge(dead, restored, moved)
    result = GameService(settings, bridge=bridge).act("Z R")
    assert result.executed == 2
    assert result.requested == 2
    assert result.stop_reason == "completed"
    calls = bridge.request.call_args_list
    if native:
        assert calls[1].kwargs == {"actions": ["undo"]}
        assert calls[2].kwargs == {"actions": ["right"]}
    else:
        assert calls[1].args == ("undo",)
        assert calls[2].args == ("move", "right")


@pytest.mark.parametrize("native", [False, True])
def test_failed_recovery_does_not_send_following_directions(settings, native):
    dead = make_state(no_player=1, capabilities=["batch"] if native else [])
    after_undo = dead.model_copy(update={"executed": 1})
    bridge = FakeBridge(dead, after_undo)
    result = GameService(settings, bridge=bridge).act("Z R8")
    assert result.executed == 1
    assert result.stop_reason == "control_lost"
    assert bridge.request.call_count == 2


def test_compatibility_batch_detects_death_after_undo_restores_control(settings):
    dead = make_state(no_player=1, undo_depth=1)
    restored = make_state(units=[PLAYER])
    bridge = FakeBridge(dead, restored, dead)
    result = GameService(settings, bridge=bridge).act("Z R8")
    assert result.executed == 2
    assert result.stop_reason == "control_lost"
    assert bridge.request.call_count == 3


def test_native_undo_only_batch_stays_one_batch(settings):
    initial = make_state(no_player=1, capabilities=["batch"])
    bridge = FakeBridge(initial, make_state(executed=3))
    result = GameService(settings, bridge=bridge).act("Z3")
    assert result.executed == 3
    assert bridge.request.call_count == 2
    assert bridge.request.call_args.kwargs == {"actions": ["undo"] * 3}
