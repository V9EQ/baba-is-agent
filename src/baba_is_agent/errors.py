"""Actionable errors surfaced by the CLI and MCP tools."""


class BabaError(RuntimeError):
    """Base class for expected operational errors."""


class BridgeUnavailableError(BabaError):
    """The mod is missing, stopped, or inaccessible."""


class BridgeTimeoutError(BabaError):
    """An acknowledgement did not arrive; an action's outcome may be unknown."""


class BridgeProtocolError(BabaError):
    """The game returned an unsupported or malformed response."""


class GameActionError(BabaError):
    """The engine rejected an action, or the current menu does not allow it."""


class InputUnavailableError(BabaError):
    """Native menu input is not available on the current desktop."""
