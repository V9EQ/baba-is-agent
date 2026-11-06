import asyncio
from unittest.mock import Mock, patch

import pytest
from conftest import make_state
from mcp.server.fastmcp.exceptions import ToolError
from test_feedback import PLAYER
from test_presentation import decode

from baba_is_agent.cli import main
from baba_is_agent.feedback import action_result
from baba_is_agent.server import create_server

TOOLS = {
    "observe",
    "act",
    "undo",
    "restart",
    "press",
    "choose_menu",
    "enter_level",
    "list_levels",
    "launch_game",
}


def test_one_tool_set_has_simple_schemas_without_profiles_or_views():
    tools = asyncio.run(create_server(Mock()).list_tools())
    schemas = {t.name: t.inputSchema for t in tools}
    assert set(schemas) == TOOLS
    assert not schemas["observe"].get("properties")
    actions = schemas["act"]["properties"]["actions"]
    assert actions["type"] == "array" and "anyOf" not in actions
    assert actions["minItems"] == 1 and actions["maxItems"] == 64
    assert all("view" not in s.get("properties", {}) for s in schemas.values())


def test_observe_does_not_mutate_and_route_uses_one_batch():
    async def exercise():
        state = make_state(units=[PLAYER])
        service = Mock()
        service.get_state.return_value = state
        service.act.return_value = action_result(state, state, 3, 3)
        server = create_server(service)
        await server.call_tool("observe", {})
        service.act.assert_not_called()
        route = ["right", "right", "up"]
        result = decode(await server.call_tool("act", {"actions": route}))
        assert result["requested"] == 3 and result["executed"] == 3
        assert "objects" not in result
        service.act.assert_called_once_with(route)
        await server.call_tool("undo", {"steps": 2})
        service.act.assert_called_with(["undo"] * 2)
        service.restart_level.assert_not_called()
        service.press.assert_not_called()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "actions", [[], ["right"] * 65, "right", '[["up"]]', ["select"], ['"right"']]
)
def test_bad_actions_rejected_before_mutation(actions):
    async def exercise():
        service = Mock()
        with pytest.raises(ToolError):
            await create_server(service).call_tool("act", {"actions": actions})
        service.act.assert_not_called()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("tool", "arguments", "method", "args"),
    [
        ("press", {"key": "confirm"}, "press", ("confirm",)),
        ("choose_menu", {"name": "resume"}, "choose_menu", ("resume",)),
        ("restart", {}, "restart_level", ()),
        ("enter_level", {"number": 6}, "enter_level", (6,)),
    ],
)
def test_menu_restart_and_entry_capabilities_preserved(tool, arguments, method, args):
    async def exercise():
        service = Mock()
        getattr(service, method).return_value = make_state()
        reply = decode(await create_server(service).call_tool(tool, arguments))
        assert "objects" in reply  # First reply always establishes a board baseline.
        getattr(service, method).assert_called_once_with(*args)

    asyncio.run(exercise())


def test_cli_has_one_api_even_with_obsolete_profile_environment(monkeypatch):
    monkeypatch.setenv("BABA_MCP_PROFILE", "lite")
    with (
        patch("baba_is_agent.cli.GameService") as service,
        patch("baba_is_agent.cli.create_server") as create,
    ):
        assert main(["serve"]) == 0
        create.assert_called_once_with(service.return_value)
        create.return_value.run.assert_called_once_with(transport="stdio")
        service.return_value.close.assert_called_once()
