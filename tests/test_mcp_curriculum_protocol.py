from __future__ import annotations

import asyncio
import os
import sys

import pytest

pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_mcp_stdio_exposes_curriculum_schemas_and_tool_errors():
    async def exercise_server():
        environment = dict(os.environ)
        environment.pop("SIGAA_USER", None)
        environment.pop("SIGAA_PASS", None)
        environment["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "sigaa.mcp_server"],
            env=environment,
        )

        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = await session.list_tools()
                tools = {tool.name: tool for tool in listed.tools}

                assert {"sigaa_get_curriculum", "sigaa_get_cra"} <= set(tools)
                curriculum = tools["sigaa_get_curriculum"]
                properties = curriculum.inputSchema["properties"]
                assert set(properties) == {
                    "status",
                    "required_only",
                    "period",
                    "include_requirements",
                    "include_cra",
                }
                assert properties["status"]["default"] == "current"
                assert properties["status"]["enum"] == [
                    "current",
                    "enrolled",
                    "pending",
                    "completed",
                    "all",
                ]

                rejected = await session.call_tool("sigaa_get_curriculum", {})
                assert rejected.isError is True
                assert "no credentials available" in " ".join(
                    getattr(item, "text", "") for item in rejected.content
                )

                invalid = await session.call_tool(
                    "sigaa_get_curriculum",
                    {"status": "not-a-status"},
                )
                assert invalid.isError is True

    asyncio.run(exercise_server())
