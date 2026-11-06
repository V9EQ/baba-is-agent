import json
import re
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from baba_is_agent.errors import (
    BridgeProtocolError,
    BridgeTimeoutError,
    BridgeUnavailableError,
    GameActionError,
)
from baba_is_agent.installer import install
from baba_is_agent.storage import atomic_write, game_lock
from baba_is_agent.transport import BridgeClient, BridgeSession, encode_request


def test_transport_waits_for_matching_acknowledgement(settings):
    install(settings)
    response_path = settings.transport_dir / "state.ini"
    response_path.write_text('[baba_mcp]\nstate={"request_id":"stale"}\n')
    failures = []

    def engine():
        try:
            for _ in range(200):
                request = settings.transport_dir / "request.lua"
                if request.exists():
                    match = re.search(r'id="([a-f0-9]+)"', request.read_text())
                    assert match is not None
                    request_id = match[1]
                    data = {
                        "request_id": request_id,
                        "protocol": 2,
                        "frame": 17,
                        "units": [],
                        "rules": [],
                        "buttons": [],
                    }
                    atomic_write(response_path, "[baba_mcp]\nstate=" + json.dumps(data) + "\n")
                    return
                time.sleep(0.002)
            raise AssertionError("Request was not written")
        except Exception as error:
            failures.append(error)

    worker = threading.Thread(target=engine)
    worker.start()
    try:
        with BridgeClient(settings).session() as session:
            response = session.request()
        assert response.frame == 17
        assert response.request_id != "stale"
        assert not (settings.transport_dir / "request.lua").exists()
    finally:
        worker.join(timeout=2)
    assert not worker.is_alive()
    assert not failures


def test_timeout_does_not_retry_or_leave_an_action_queued(settings):
    install(settings)
    with patch("baba_is_agent.transport.atomic_write", wraps=atomic_write) as writer:
        with BridgeClient(settings).session() as session:
            with pytest.raises(BridgeTimeoutError, match="outcome is uncertain") as error:
                session.request("move", "left")
            assert "observe()" in str(error.value)
            assert "may already have executed" in str(error.value)
            assert "get_state" not in str(error.value)
            assert "installed" not in str(error.value)
        assert writer.call_count == 1
    assert not (settings.transport_dir / "request.lua").exists()


def test_missing_bridge_is_actionable(settings):
    with pytest.raises(BridgeUnavailableError, match="install"):
        BridgeSession(settings).request()


@pytest.mark.parametrize(
    "operation,direction",
    [("eval", None), ("state", "left"), ("move", None), ("move", 'left";os.exit()')],
)
def test_request_rejects_executable_input(operation, direction):
    with pytest.raises(ValueError):
        encode_request("safe123", operation, direction)


def test_request_table_is_fixed_data():
    assert (
        encode_request("abc123", "move", "left") == 'return {id="abc123",op="move",key="left"}\n'
    )
    with pytest.raises(ValueError):
        encode_request('";code()', "state", None)


@pytest.mark.parametrize("content", ["not ini", "[baba_mcp]\nstate={", "[baba_mcp]\nstate=[]"])
def test_partial_or_unrelated_response_is_ignored(settings, content):
    settings.transport_dir.mkdir(parents=True)
    (settings.transport_dir / "state.ini").write_text(content)
    assert BridgeSession(settings)._read_response("mine") is None


@pytest.mark.parametrize("error_key", ["error", "action_error"])
def test_engine_errors_are_not_retried(settings, error_key):
    settings.transport_dir.mkdir(parents=True)
    payload = {"request_id": "mine", error_key: "Not ready"}
    (settings.transport_dir / "state.ini").write_text("[baba_mcp]\nstate=" + json.dumps(payload))
    with pytest.raises(GameActionError, match="Not ready"):
        BridgeSession(settings)._read_response("mine")


def test_protocol_mismatch_is_explicit(settings):
    settings.transport_dir.mkdir(parents=True)
    (settings.transport_dir / "state.ini").write_text(
        '[baba_mcp]\nstate={"request_id":"mine","protocol":99}'
    )
    with pytest.raises(BridgeProtocolError):
        BridgeSession(settings)._read_response("mine")


def test_lock_has_a_deadline(tmp_path: Path):
    lock = tmp_path / "lock"
    with game_lock(lock, 1):
        with pytest.raises(BridgeTimeoutError, match="Another client"):
            with game_lock(lock, 0.02):
                pytest.fail("A competing lock was acquired")
