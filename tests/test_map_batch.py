from conftest import make_state
from test_service import FakeBridge

from baba_is_agent.service import GameService


def test_cursor_map_does_not_stop_batch_for_missing_baba(settings):
    cursor = {
        "id": 1,
        "name": "cursor",
        "x": 2,
        "y": 3,
        "dir": 0,
        "type": "object",
        "properties": ["select"],
    }
    initial = make_state(units=[cursor])
    # Native NOPLAYER means no YOU, not that map control has been lost.
    after = make_state(units=[cursor], no_player=1)
    bridge = FakeBridge(initial, *[after] * 8)
    assert GameService(settings, bridge=bridge).act("R8").executed == 8
