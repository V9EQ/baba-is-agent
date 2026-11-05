"""Install only our own mod. Never overwrite game scripts or edit saves."""

from importlib.resources import files

from baba_is_agent.config import BRIDGE_MARKER, Settings
from baba_is_agent.errors import BridgeUnavailableError
from baba_is_agent.models import JsonObject
from baba_is_agent.storage import atomic_write, game_lock


def bridge_source() -> str:
    """Read the Lua asset from an editable install or built wheel."""
    return files("baba_is_agent").joinpath("assets/bridge.lua").read_text(encoding="utf-8")


def _check_ownership(settings: Settings) -> None:
    if settings.mod_path.exists() and not settings.mod_path.read_text(encoding="utf-8").startswith(
        BRIDGE_MARKER
    ):
        raise BridgeUnavailableError(f"Refusing to modify an unknown mod: {settings.mod_path}")


def install(settings: Settings) -> JsonObject:
    """Install or upgrade the bridge; the running game must then be restarted."""
    if not (settings.game_dir / "Data/modsupport.lua").is_file():
        raise BridgeUnavailableError(
            f"Unsupported game directory: {settings.game_dir}. Set BABA_GAME_DIR to the Linux installation."
        )
    with game_lock(settings.lock_path, settings.lock_timeout):
        _check_ownership(settings)
        settings.transport_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        settings.mod_path.parent.mkdir(exist_ok=True)
        atomic_write(settings.mod_path, bridge_source())
        (settings.transport_dir / "request.lua").unlink(missing_ok=True)
    return {
        "mod": str(settings.mod_path),
        "transport": str(settings.transport_dir),
        "restart_game_required": True,
    }


def uninstall(settings: Settings) -> JsonObject:
    """Remove recognized bridge files; leave all game assets and saves alone."""
    with game_lock(settings.lock_path, settings.lock_timeout):
        _check_ownership(settings)
        settings.mod_path.unlink(missing_ok=True)
        for name in ("request.lua", "request.tmp", "state.ini", "state.ini.tmp"):
            (settings.transport_dir / name).unlink(missing_ok=True)
    return {"removed": True, "restart_game_required": True, "saves_modified": False}
