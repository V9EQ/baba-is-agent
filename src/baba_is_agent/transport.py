"""Acknowledged requests over the game's sandbox-compatible native INI API."""

import configparser
import json
import time
import uuid
from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager
from typing import Protocol

from pydantic import ValidationError

from baba_is_agent.config import Settings
from baba_is_agent.errors import (
    BridgeProtocolError,
    BridgeTimeoutError,
    BridgeUnavailableError,
    GameActionError,
)
from baba_is_agent.models import Direction, GameState, Operation
from baba_is_agent.storage import atomic_write, game_lock

_OPERATIONS = frozenset({"state", "move", "undo", "restart", "batch"})
_DIRECTIONS = frozenset({"up", "down", "left", "right", "idle"})


def encode_request(
    request_id: str,
    operation: Operation,
    direction: Direction | None,
    actions: list[str] | None = None,
) -> str:
    """Emit a fixed Lua table, never caller-supplied executable code."""
    if not request_id.isascii() or not request_id.isalnum():
        raise ValueError("Invalid request identifier")
    if operation not in _OPERATIONS:
        raise ValueError("Invalid bridge operation")
    if (operation == "move" and direction not in _DIRECTIONS) or (
        operation != "move" and direction is not None
    ):
        raise ValueError("A valid direction is required only for move operations")
    fields = [f"id={json.dumps(request_id)}", f"op={json.dumps(operation)}"]
    if direction is not None:
        fields.append(f"key={json.dumps(direction)}")
    if operation == "batch":
        if (
            actions is None
            or not 1 <= len(actions) <= 64
            or any(a not in _DIRECTIONS | {"undo"} for a in actions)
        ):
            raise ValueError("Expected 1..64 allowlisted batch actions")
        fields.append("actions={" + ",".join(json.dumps(a) for a in actions) + "}")
    elif actions is not None:
        raise ValueError("Actions are only supported by batch operations")
    return "return {" + ",".join(fields) + "}\n"


class BridgeSession:
    """A transport session owned by a caller holding the game's lock."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def request(
        self,
        operation: Operation = "state",
        direction: Direction | None = None,
        *,
        actions: list[str] | None = None,
    ) -> GameState:
        """Wait for this request's acknowledgement. Never retry a mutating operation."""
        settings = self.settings
        if not settings.mod_path.is_file() or not settings.transport_dir.is_dir():
            raise BridgeUnavailableError(
                "Bridge missing. Run `baba-mcp install`, then restart the game."
            )
        request_id = uuid.uuid4().hex
        payload = encode_request(request_id, operation, direction, actions)
        request_path = settings.transport_dir / "request.lua"
        atomic_write(request_path, payload)
        try:
            deadline = time.monotonic() + settings.request_timeout
            while time.monotonic() < deadline:
                response = self._read_response(request_id)
                if response is not None:
                    return response
                time.sleep(settings.poll_interval)
            detail = (
                " The action's outcome is uncertain: it may already have executed. "
                "Call observe() before any further action; do not repeat the command automatically."
                if operation != "state"
                else " The game did not acknowledge a read. Check that it is running and responsive, "
                "then try observe() again."
            )
            raise BridgeTimeoutError(
                f"No acknowledgement within {settings.request_timeout:g}s." + detail
            )
        finally:
            # Do not leave a timed-out action queued for a future game launch.
            # The session lock prevents another cooperating client replacing it here.
            request_path.unlink(missing_ok=True)

    def _read_response(self, request_id: str) -> GameState | None:
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read(self.settings.transport_dir / "state.ini", encoding="utf-8")
            response = json.loads(parser.get("baba_mcp", "state", fallback="{}"))
        except (OSError, UnicodeError, configparser.Error, json.JSONDecodeError):
            # The native writer may be between truncating and flushing its INI.
            return None
        if not isinstance(response, dict) or response.get("request_id") != request_id:
            return None
        if response.get("error") or response.get("action_error"):
            raise GameActionError(str(response.get("error") or response["action_error"]))
        try:
            return GameState.model_validate(response)
        except ValidationError as error:
            raise BridgeProtocolError(
                "Unsupported telemetry schema. Reinstall the matching bridge and restart the game."
            ) from error


class BridgeConnection(Protocol):
    """Request interface used by services and offline engine substitutes."""

    def request(
        self,
        operation: Operation = "state",
        direction: Direction | None = None,
        *,
        actions: list[str] | None = None,
    ) -> GameState: ...


class BridgeGateway(Protocol):
    def session(self) -> AbstractContextManager[BridgeConnection]: ...


class BridgeClient:
    """Own the cross-process lock for a complete tool call, including batches."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @contextmanager
    def session(self) -> Generator[BridgeSession]:
        with game_lock(self.settings.lock_path, self.settings.lock_timeout):
            yield BridgeSession(self.settings)
