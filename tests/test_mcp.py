"""Exercise the published stdio interface in a subprocess, with no game running."""

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_handshake_tools_and_read_only_metadata(settings):
    async def exercise():
        directory = settings.game_dir / "Data/Worlds/baba"
        directory.mkdir(parents=True)
        (directory / "0level.ld").write_text("[general]\nname=Fixture\n")
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "baba_is_agent"],
            env={
                **os.environ,
                "BABA_GAME_DIR": str(settings.game_dir),
                "BABA_BRIDGE_DIR": str(settings.state_dir),
            },
        )
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                tools = (await client.list_tools()).tools
                assert {tool.name for tool in tools} == {
                    "observe",
                    "undo",
                    "act",
                    "press",
                    "choose_menu",
                    "restart",
                    "list_levels",
                    "launch_game",
                    "enter_level",
                }
                descriptions: dict[str, str] = {}
                for tool in tools:
                    assert isinstance(tool.description, str)
                    descriptions[tool.name] = tool.description
                assert "1..64" in descriptions["act"]
                assert "unmentioned state" in descriptions["act"]
                assert "zero-based" in descriptions["observe"]
                assert "confirm" in descriptions["press"]
                schemas = {tool.name: tool.inputSchema for tool in tools}
                actions = schemas["act"]["properties"]["actions"]
                assert actions["type"] == "array"
                assert actions["minItems"] == 1
                assert actions["maxItems"] == 64
                assert schemas["list_levels"]["properties"]["limit"]["maximum"] == 100
                assert schemas["list_levels"]["properties"]["offset"]["minimum"] == 0
                read_only = next(tool for tool in tools if tool.name == "observe")
                assert read_only.annotations is not None
                assert read_only.annotations.readOnlyHint
                result = await client.call_tool("list_levels", {"world": "baba"})
                assert not result.isError
                assert result.structuredContent is None
                content = result.content[0]
                assert content.type == "text"
                assert json.loads(content.text)["levels"][0]["name"] == "Fixture"
                error = await client.call_tool("observe", {})
                assert error.isError
                content = error.content[0]
                assert content.type == "text"
                assert "install" in content.text

    asyncio.run(exercise())
