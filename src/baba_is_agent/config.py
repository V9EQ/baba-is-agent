"""Explicit, side-effect-free configuration for one local game installation."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

STEAM_APP_ID = "736260"
BRIDGE_MARKER = "-- Baba MCP telemetry v2:"
PROTOCOL_VERSION = 2


@dataclass(frozen=True, slots=True)
class Settings:
    """Paths and timing shared by the installer, transport, and service."""

    game_dir: Path
    state_dir: Path
    request_timeout: float = 5.0
    lock_timeout: float = 30.0
    poll_interval: float = 0.025

    def __post_init__(self) -> None:
        object.__setattr__(self, "game_dir", self.game_dir.expanduser().resolve())
        object.__setattr__(self, "state_dir", self.state_dir.expanduser().resolve())
        if min(self.request_timeout, self.lock_timeout, self.poll_interval) <= 0:
            raise ValueError("Timeouts and poll interval must be positive")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Read overrides without connecting to the game or desktop."""
        env = os.environ if env is None else env
        home = Path.home()
        candidates = (
            home / ".local/share/Steam/steamapps/common/Baba Is You",
            home / ".steam/steam/steamapps/common/Baba Is You",
        )
        default_game = next((path for path in candidates if path.is_dir()), candidates[0])
        state_home = Path(env.get("XDG_STATE_HOME", str(home / ".local/state")))
        return cls(
            game_dir=Path(env.get("BABA_GAME_DIR", str(default_game))),
            state_dir=Path(env.get("BABA_BRIDGE_DIR", str(state_home / "baba-mcp"))),
        )

    @property
    def mod_path(self) -> Path:
        return self.game_dir / "Data/Lua/zz_baba_mcp.lua"

    @property
    def transport_dir(self) -> Path:
        return self.game_dir / "Data/Languages/baba_mcp"

    @property
    def lock_path(self) -> Path:
        return self.state_dir / "lock"
