import asyncio
from unittest.mock import Mock, patch

import pytest
from conftest import make_state
from mcp.server.fastmcp.exceptions import ToolError

from baba_is_agent.cli import main
from baba_is_agent.feedback import action_result
from baba_is_agent.server import create_server


def test_lite_tools_have_small_unambiguous_schemas():
    tools = asyncio.run(create_server(Mock(), profile="lite").list_tools())
    schemas = {t.name: t.inputSchema for t in tools}
    assert set(schemas) == {"observe", "move", "undo", "restart", "press", "enter_level"}
    assert not schemas["observe"].get("properties")
    assert schemas["move"]["properties"]["direction"]["enum"] == [
        "up",
        "down",
        "left",
        "right",
        "wait",
    ]
    assert schemas["move"]["properties"]["steps"]["minimum"] == 1
    assert schemas["move"]["properties"]["steps"]["maximum"] == 64
    assert all("view" not in s.get("properties", {}) for s in schemas.values())


def test_lite_observe_does_not_mutate_and_move_uses_one_batch():
    async def exercise():
        state = make_state()
        service = Mock()
        service.get_state.return_value = state
        service.act.return_value = action_result(state, state, 4, 4)
        server = create_server(service, profile="lite")
        await server.call_tool("observe", {})
        service.act.assert_not_called()
        await server.call_tool("move", {"direction": "right", "steps": 4})
        service.act.assert_called_once_with(["right"] * 4)
        await server.call_tool("undo", {"steps": 2})
        service.act.assert_called_with(["undo"] * 2)
        service.restart_level.assert_not_called()
        service.press.assert_not_called()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "arguments",
    [{"direction": "right", "steps": 65}, {"direction": '"right"'}, {"direction": "R"}],
)
def test_lite_rejects_bad_input_before_mutation(arguments):
    async def exercise():
        service = Mock()
        server = create_server(service, profile="lite")
        with pytest.raises(ToolError):
            await server.call_tool("move", arguments)
        service.act.assert_not_called()

    asyncio.run(exercise())


@pytest.mark.parametrize("argv", [["--profile", "lite", "serve"], []])
def test_cli_selects_lite_profile(argv, monkeypatch):
    monkeypatch.setenv("BABA_MCP_PROFILE", "lite")
    with (
        patch("baba_is_agent.cli.GameService") as service,
        patch("baba_is_agent.cli.create_server") as create,
    ):
        assert main(argv) == 0
        create.assert_called_once_with(service.return_value, profile="lite")
        create.return_value.run.assert_called_once_with(transport="stdio")
        service.return_value.close.assert_called_once()


def test_profile_must_be_known():
    with pytest.raises(ValueError, match="profile"):
        create_server(Mock(), profile="unknown")  # ty: ignore[invalid-argument-type]
