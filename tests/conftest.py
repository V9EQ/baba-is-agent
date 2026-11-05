"""Offline fixtures; no Steam installation or desktop access is required."""

from pathlib import Path

import pytest

from baba_is_agent.config import Settings
from baba_is_agent.models import GameState


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    game = tmp_path / "game"
    (game / "Data/Lua").mkdir(parents=True)
    (game / "Data/modsupport.lua").touch()
    return Settings(
        game_dir=game, state_dir=tmp_path / "state", request_timeout=0.3, poll_interval=0.005
    )


def make_state(**changes: object) -> GameState:
    data = {
        "protocol": 2,
        "request_id": "test",
        "frame": 1,
        "units": [],
        "rules": [],
        "buttons": [],
        "menu": "ingame",
        "world": "baba",
        "level": "0level",
    }
    data.update(changes)
    return GameState.model_validate(data)
