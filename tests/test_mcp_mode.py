from __future__ import annotations

import asyncio
import sys

import pytest

pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from sigaa import mcp_server
from sigaa.config import HOSTED_MODE, LOCAL_MODE

KEPT_IN_HOSTED = {"sigaa_sync", "sigaa_list_classes", "sigaa_matricula_open_turmas"}


def _spawn(environment):
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "sigaa.mcp_server"],
        env=environment,
    )


def test_local_mode_hides_nothing():
    assert mcp_server.hidden_tools_for_mode(LOCAL_MODE) == frozenset()


def test_hosted_mode_hides_the_disk_writers():
    assert mcp_server.hidden_tools_for_mode(HOSTED_MODE) == mcp_server.HOSTED_HIDDEN_TOOLS


def test_deny_list_only_names_tools_that_exist():
    """A renamed tool must not leave a stale entry behind — remove_tool would raise."""
    assert mcp_server.HOSTED_HIDDEN_TOOLS <= set(mcp_server.mcp._tool_manager._tools)


def test_hosted_server_withholds_downloads_and_keeps_the_rest(tmp_path, mcp_subprocess_env):
    async def exercise_server():
        environment = mcp_subprocess_env(tmp_path, SIGAA_MODE="hosted")

        async with stdio_client(_spawn(environment)) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = {tool.name for tool in (await session.list_tools()).tools}

                assert listed.isdisjoint(mcp_server.HOSTED_HIDDEN_TOOLS)
                assert KEPT_IN_HOSTED <= listed

                # Proves the tool is gone, not merely hidden: call_tool dispatches
                # straight into the tool manager, bypassing any list_tools filter.
                refused = await session.call_tool(
                    "sigaa_download_material", {"material_id": "any"}
                )
                assert refused.isError is True
                assert "Unknown tool" in " ".join(
                    getattr(item, "text", "") for item in refused.content
                )

    asyncio.run(exercise_server())


def test_default_server_still_exposes_every_tool(tmp_path, mcp_subprocess_env):
    """No behavior change for existing users: unset SIGAA_MODE keeps the full surface."""

    async def exercise_server():
        environment = mcp_subprocess_env(tmp_path)

        async with stdio_client(_spawn(environment)) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = {tool.name for tool in (await session.list_tools()).tools}

                assert mcp_server.HOSTED_HIDDEN_TOOLS <= listed

    asyncio.run(exercise_server())
