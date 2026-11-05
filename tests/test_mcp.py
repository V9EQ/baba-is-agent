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
                    "get_state",
                    "get_board",
                    "act",
                    "press",
                    "choose_menu",
                    "restart_level",
                    "list_levels",
                    "launch_game",
                }
                read_only = next(tool for tool in tools if tool.name == "get_state")
                assert read_only.annotations is not None
                assert read_only.annotations.readOnlyHint
                result = await client.call_tool("list_levels", {"world": "baba"})
                assert not result.isError
                assert result.structuredContent is None
                content = result.content[0]
                assert content.type == "text"
                assert json.loads(content.text)["levels"][0]["name"] == "Fixture"
                error = await client.call_tool("get_state", {})
                assert error.isError
                content = error.content[0]
                assert content.type == "text"
                assert "install" in content.text

    asyncio.run(exercise())
