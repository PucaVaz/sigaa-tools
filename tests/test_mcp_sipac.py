import asyncio
import os
from pathlib import Path
import sys

import pytest

pytest.importorskip("mcp")

from mcp.server.fastmcp.exceptions import ToolError
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from sigaa import mcp_server
from sigaa.models import SipacProcessSearchPage, SipacProcessSearchResult
from sigaa.parsers.sipac import parse_public_process


FIXTURE = Path(__file__).parent / "fixtures" / "sipac_process.html"


def _process():
    return parse_public_process(
        FIXTURE.read_text(encoding="utf-8"),
        public_url="https://sipac.ufpb.br/public/jsp/processos/processo_detalhado.jsf?id=123",
    )


def test_mcp_registers_public_sipac_process_tool():
    assert "sipac_get_public_process" in mcp_server.mcp._tool_manager._tools
    assert "sipac_search_public_processes" in mcp_server.mcp._tool_manager._tools


def test_mcp_public_process_uses_shared_contract_without_credentials(monkeypatch):
    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def get_public_process(self, number):
            assert number == "23074.000001/2099-10"
            return _process()

    monkeypatch.setattr(mcp_server, "SipacClient", FakeClient)

    data = mcp_server.sipac_get_public_process("23074.000001/2099-10")
    assert data["source"] == "sipac_ufpb_public_portal"
    assert data["movements"][0]["destination_unit"] == "DESTINO"


def test_mcp_public_process_errors_are_tool_errors():
    with pytest.raises(ToolError, match="invalid SIPAC process number"):
        mcp_server.sipac_get_public_process("invalid")


def test_mcp_public_search_uses_shared_contract(monkeypatch):
    expected_page = SipacProcessSearchPage(
        query_type="identifier",
        query="1234567",
        page=2,
        total_pages=3,
        total_results=31,
        results=[
            SipacProcessSearchResult(
                number="23074.000001/2099-10",
                subject="TEST",
                interested_parties=["JANE"],
                origin_unit="UNIT",
                public_url="https://sipac.ufpb.br/public/process/1",
            )
        ],
    )

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def search_public_processes(self, *, name, identifier, page):
            assert (name, identifier, page) == (None, "1234567", 2)
            return expected_page

    monkeypatch.setattr(mcp_server, "SipacClient", FakeClient)
    data = mcp_server.sipac_search_public_processes(identifier="1234567", page=2)
    assert data["pagination"]["page"] == 2
    assert data["results"][0]["number"] == "23074.000001/2099-10"


def test_mcp_public_search_rejects_ambiguous_criteria():
    with pytest.raises(ToolError, match="exactly one"):
        mcp_server.sipac_search_public_processes()


def test_mcp_stdio_exposes_public_sipac_process_schema_and_validation():
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
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                tool = tools["sipac_get_public_process"]
                assert set(tool.inputSchema["properties"]) == {"number"}
                assert tool.inputSchema["required"] == ["number"]
                search = tools["sipac_search_public_processes"]
                assert set(search.inputSchema["properties"]) == {
                    "name",
                    "identifier",
                    "page",
                }

                invalid = await session.call_tool(
                    "sipac_get_public_process", {"number": "invalid"}
                )
                assert invalid.isError is True
                assert "invalid SIPAC process number" in " ".join(
                    getattr(item, "text", "") for item in invalid.content
                )

    asyncio.run(exercise_server())
