"""Opt-in, read-only smoke test against a running game through real MCP stdio."""

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from baba_is_agent.models import GameState


async def verify() -> None:
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "baba_is_agent"], env=dict(os.environ)
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as client:
            await client.initialize()
            states = []
            for _ in range(2):
                result = await client.call_tool("get_state", {"view": "full"})
                if result.isError:
                    raise RuntimeError(f"Native telemetry unavailable: {result.content}")
                content = result.content[0]
                if content.type != "text":
                    raise RuntimeError("Expected compact JSON text")
                states.append(GameState.model_validate(json.loads(content.text)))
            first, second = states
            if first.request_id == second.request_id or second.frame <= first.frame:
                raise RuntimeError("The engine did not acknowledge two fresh requests")
            print(f"MCP OK: fresh frames {first.frame} → {second.frame}; level={second.level!r}")


if __name__ == "__main__":
    asyncio.run(verify())
