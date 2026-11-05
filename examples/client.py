"""Call the real stdio MCP from the terminal, preserving the desktop environment.

Examples:
    uv run python examples/client.py get_board
    uv run python examples/client.py act '{"actions": ["right", "undo"]}'
"""

import argparse
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult


def result_data(result: CallToolResult) -> object:
    """Use MCP structured output, including FastMCP's wrapper for list results."""
    if result.isError:
        message = "\n".join(item.text for item in result.content if item.type == "text")
        raise RuntimeError(message)
    if result.structuredContent is not None:
        data = result.structuredContent
        return data["result"] if set(data) == {"result"} else data
    texts = [item.text for item in result.content if item.type == "text"]
    return json.loads(texts[0]) if len(texts) == 1 else texts


async def run(tool: str, arguments: dict[str, object]) -> None:
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "baba_is_agent"], env=dict(os.environ)
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as client:
            await client.initialize()
            data = result_data(await client.call_tool(tool, arguments))
            print(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", nargs="?", default="get_board")
    parser.add_argument("arguments", nargs="?", default="{}", help="JSON object of tool arguments")
    args = parser.parse_args()
    try:
        arguments = json.loads(args.arguments)
        if not isinstance(arguments, dict):
            parser.error("arguments must be a JSON object")
        asyncio.run(run(args.tool, arguments))
    except json.JSONDecodeError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
