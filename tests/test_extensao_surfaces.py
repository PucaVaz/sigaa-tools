"""The extension participation list through the client, the CLI and the MCP tool."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sigaa import cli as cli_module
from sigaa.client import SigaaClient
from sigaa.config import Settings
from sigaa.institutions import get
from sigaa.parsers.extensao import ExtensaoParseError, parse_extension_participations

FIXTURES = Path(__file__).parent / "fixtures"
PAGE = (FIXTURES / "extensao_documentos.html").read_text(encoding="utf-8")
EMPTY_PAGE = (FIXTURES / "extensao_documentos_vazio.html").read_text(encoding="utf-8")
EXPECTED_COUNTS = {
    "team_member": 3,
    "audience": 1,
    "extension_student": 1,
    "declarations_available": 2,
    "certificates_available": 1,
}


def _settings():
    return SimpleNamespace(institution="ufpb",
        username="configured-user",
        resolve_password=lambda: "test-password",
    )


def _fake_client(page: str | None = None, failure: Exception | None = None):
    class FakeClient:
        def __init__(self, username, password, **kwargs):
            assert (username, password) == ("configured-user", "test-password")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def list_extension_participations(self):
            if failure is not None:
                raise failure
            return parse_extension_participations(page)

    return FakeClient


def test_client_opens_the_documents_menu_item_and_parses_it():
    clicked = []
    client = object.__new__(SigaaClient)
    client.profile = get("ufpb").profile

    def menu_post(label):
        clicked.append(label)
        return PAGE

    client._portal_menu_post = menu_post

    participations = client.list_extension_participations()

    assert clicked == ["Certificados e Declarações"]
    assert len(participations) == 5


def test_cli_registers_extensao_command():
    args = cli_module._build_parser().parse_args(["extensao"])

    assert args.func is cli_module._cmd_extensao
    assert args.json is False


def test_cli_json_uses_the_shared_contract(monkeypatch, capsys):
    monkeypatch.setattr(cli_module, "SigaaClient", _fake_client(PAGE))
    args = cli_module._build_parser().parse_args(["extensao", "--json"])

    assert cli_module._cmd_extensao(args, _settings()) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["counts"] == EXPECTED_COUNTS
    certificate = next(p for p in data["participations"] if p["certificate_available"])
    assert certificate == {
        "kind": "team_member",
        "title": "OFICINA HIPOTÉTICA DE DADOS ABERTOS",
        "action_code": None,
        "year": 2097,
        "category": "DISCENTE",
        "role": "MONITOR(A)",
        "start_date": "05/05/2097",
        "end_date": "05/11/2097",
        "registered_on": None,
        "frequency": None,
        "status": None,
        "declaration_available": False,
        "certificate_available": True,
        "sigaa_id": "900003",
    }
    assert "FULANO" not in json.dumps(data).upper()


def test_cli_human_view_groups_by_kind_and_lists_documents(monkeypatch, capsys):
    monkeypatch.setattr(cli_module, "SigaaClient", _fake_client(PAGE))
    args = cli_module._build_parser().parse_args(["extensao"])

    assert cli_module._cmd_extensao(args, _settings()) == 0
    output = capsys.readouterr().out

    assert "Team member (3)" in output
    assert "Audience (1)" in output
    assert "Extension student (1)" in output
    assert "PJ000-2096 - Curso Fictício de Programação para a Comunidade" in output
    assert "frequency 75%" in output
    assert "documents: certificado" in output
    assert "documents: none available yet" in output
    assert "Summary: 2 declaration(s) and 1 certificate(s) available" in output


def test_cli_reports_an_empty_page_as_no_participations(monkeypatch, capsys):
    monkeypatch.setattr(cli_module, "SigaaClient", _fake_client(EMPTY_PAGE))
    args = cli_module._build_parser().parse_args(["extensao"])

    assert cli_module._cmd_extensao(args, _settings()) == 0
    assert "No extension participations" in capsys.readouterr().out


def test_cli_parse_failure_exits_nonzero(monkeypatch, capsys):
    failure = ExtensaoParseError("extension documents page not recognized")
    monkeypatch.setattr(cli_module, "SigaaClient", _fake_client(failure=failure))
    args = cli_module._build_parser().parse_args(["extensao", "--json"])

    assert cli_module._cmd_extensao(args, _settings()) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not recognized" in captured.err


def test_cli_requires_credentials(capsys, monkeypatch, tmp_path):
    monkeypatch.delenv("SIGAA_PASS", raising=False)
    settings = Settings(db_path=tmp_path / "t.db", username=None)
    args = cli_module._build_parser().parse_args(["extensao"])

    assert cli_module._cmd_extensao(args, settings) == 1
    assert "missing credentials" in capsys.readouterr().err


class TestMcpTool:
    @pytest.fixture(autouse=True)
    def _mcp(self):
        pytest.importorskip("mcp")
        from sigaa import mcp_server

        self.mcp_server = mcp_server

    def test_is_registered_and_kept_in_hosted_mode(self):
        from sigaa.config import HOSTED_MODE

        name = "sigaa_list_extension_participations"
        assert name in self.mcp_server.mcp._tool_manager._tools
        assert name not in self.mcp_server.hidden_tools_for_mode(HOSTED_MODE)

    def test_returns_the_shared_contract(self, monkeypatch):
        monkeypatch.setattr(self.mcp_server, "Settings", _settings)
        monkeypatch.setattr(self.mcp_server, "SigaaClient", _fake_client(PAGE))

        data = self.mcp_server.sigaa_list_extension_participations()

        assert data["counts"] == EXPECTED_COUNTS
        assert [p["sigaa_id"] for p in data["participations"]] == [
            "900001", "900002", "900003", "900004", "900005",
        ]

    def test_parse_failure_is_a_tool_error(self, monkeypatch):
        from mcp.server.fastmcp.exceptions import ToolError

        failure = ExtensaoParseError("extension documents page not recognized")
        monkeypatch.setattr(self.mcp_server, "Settings", _settings)
        monkeypatch.setattr(self.mcp_server, "SigaaClient", _fake_client(failure=failure))

        with pytest.raises(ToolError, match="not recognized"):
            self.mcp_server.sigaa_list_extension_participations()

    def test_requires_credentials(self, monkeypatch):
        from mcp.server.fastmcp.exceptions import ToolError

        settings = SimpleNamespace(institution="ufpb", username=None, resolve_password=lambda: None)
        monkeypatch.setattr(self.mcp_server, "Settings", lambda: settings)

        with pytest.raises(ToolError, match="no credentials"):
            self.mcp_server.sigaa_list_extension_participations()
