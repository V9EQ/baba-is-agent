import re

import pytest

from baba_is_agent.config import Settings
from baba_is_agent.errors import BridgeUnavailableError
from baba_is_agent.installer import bridge_source, install, uninstall


def test_install_is_idempotent_and_preserves_game_files(settings):
    original = settings.game_dir / "Data/modsupport.lua"
    original.write_text("-- game code, not ours")
    for _ in range(2):
        result = install(settings)
        assert result["restart_game_required"]
        assert settings.mod_path.read_text() == bridge_source()
    assert original.read_text() == "-- game code, not ours"
    assert not list(settings.mod_path.parent.glob("*.tmp"))


@pytest.mark.parametrize("operation", [install, uninstall])
def test_unknown_mod_is_never_modified(settings, operation):
    settings.mod_path.write_text("-- someone else's mod")
    with pytest.raises(BridgeUnavailableError, match="unknown mod"):
        operation(settings)
    assert settings.mod_path.read_text() == "-- someone else's mod"


def test_uninstall_removes_only_recognized_files(settings):
    install(settings)
    sentinel = settings.transport_dir / "unrelated.txt"
    sentinel.write_text("keep me")
    (settings.transport_dir / "request.lua").touch()
    result = uninstall(settings)
    assert not settings.mod_path.exists()
    assert not (settings.transport_dir / "request.lua").exists()
    assert sentinel.read_text() == "keep me"
    assert result["saves_modified"] is False
    uninstall(settings)


def test_invalid_installation(settings):
    (settings.game_dir / "Data/modsupport.lua").unlink()
    with pytest.raises(BridgeUnavailableError, match="BABA_GAME_DIR"):
        install(settings)


def test_settings_are_explicit_and_expand_environment(tmp_path):
    settings = Settings.from_env(
        {"BABA_GAME_DIR": str(tmp_path), "BABA_BRIDGE_DIR": str(tmp_path / "state")}
    )
    assert settings.game_dir == tmp_path.resolve()
    assert settings.lock_path == tmp_path / "state/lock"
    with pytest.raises(ValueError):
        Settings(tmp_path, tmp_path, request_timeout=0)


def test_packaged_asset_is_sandbox_compatible():
    source = bridge_source()
    assert source.startswith("-- Baba MCP telemetry v2:")
    assert "io.open" not in source
    assert re.search(r"\bos\.\w", source) is None
    assert "MF_store" in source
    assert "MF_win(" not in source
