from __future__ import annotations

import asyncio
import os
import sys

import pytest

pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_mcp_stdio_exposes_safe_document_schemas_and_errors(tmp_path):
    async def exercise_server():
        environment = dict(os.environ)
        environment.pop("SIGAA_USER", None)
        environment.pop("SIGAA_PASS", None)
        environment["SIGAA_DOWNLOAD_DIR"] = str(tmp_path)
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "sigaa.mcp_server"],
            env=environment,
        )

        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = await session.list_tools()
                document_tools = {
                    tool.name: tool
                    for tool in listed.tools
                    if tool.name
                    in {
                        "sigaa_download_historico",
                        "sigaa_download_declaracao_vinculo",
                        "sigaa_download_atestado_matricula",
                    }
                }
                assert len(document_tools) == 3
                for tool in document_tools.values():
                    assert set(tool.inputSchema.get("properties", {})) == {"filename"}

                rejected = await session.call_tool(
                    "sigaa_download_historico", {"filename": "../outside.pdf"}
                )
                assert rejected.isError is True
                assert "safe file name" in " ".join(
                    getattr(item, "text", "") for item in rejected.content
                )

    asyncio.run(exercise_server())
    assert not (tmp_path.parent / "outside.pdf").exists()
