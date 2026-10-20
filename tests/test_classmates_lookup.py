"""The classmate lookup through the client, the search service, the CLI and the MCP tool."""

import json
import secrets
from pathlib import Path
from types import SimpleNamespace

import pytest

from sigaa import cli as cli_module
from sigaa.client import SigaaClient
from sigaa.errors import UnrecognizedPageError, UnsupportedFeatureError
from sigaa.http import AuthError
from sigaa.institutions import get
from sigaa.models import Classmate, Turma
from sigaa.parsers.participantes import parse_classmates
from sigaa.services.classmates import find_classmates, search_to_dict

FIXTURES = Path(__file__).parent / "fixtures"
PARTICIPANTES = (FIXTURES / "participantes.html").read_text(encoding="utf-8")
CALCULO = Turma(id_turma="900001", name="CÁLCULO DE EXEMPLO", code="TEST0001")
FISICA = Turma(id_turma="900002", name="FÍSICA DE EXEMPLO", code="TEST0002")
USERNAME = "aluno.teste"
# Random per run: the tests only need a value the fake client can check.
PASSWORD = secrets.token_urlsafe(16)


class FakeClient:
    """Serves one roster per class; a roster given as an exception is raised."""

    def __init__(self, rosters, institution="ufpb", login_failure=None):
        self.profile = get(institution).profile
        self.rosters = rosters
        self.login_failure = login_failure
        self.read: list[str] = []

    def list_turmas(self):
        if self.login_failure is not None:
            raise self.login_failure
        return [CALCULO, FISICA]

    def list_classmates(self, turma):
        self.read.append(turma.id_turma)
        roster = self.rosters[turma.id_turma]
        if isinstance(roster, Exception):
            raise roster
        return roster

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


def _rosters(**overrides):
    rosters = {
        CALCULO.id_turma: parse_classmates(PARTICIPANTES, CALCULO.id_turma),
        FISICA.id_turma: [
            Classmate(FISICA.id_turma, "ALUNA TRÊS DE EXEMPLO"),
            Classmate(FISICA.id_turma, "OUTRO COLEGA DE EXEMPLO"),
        ],
    }
    rosters.update(overrides)
    return rosters


def _client_factory(fake):
    def build(username, password, **kwargs):
        assert (username, password) == (USERNAME, PASSWORD)
        return fake

    return build


def _settings():
    return SimpleNamespace(
        institution="ufpb",
        username=USERNAME,
        resolve_password=lambda: PASSWORD,
        credentials_problem=lambda: "no credentials",
    )


def _names(search):
    return [match.name for match in search.matches]


def test_client_opens_participantes_and_reads_only_the_roster():
    clicked = []
    client = object.__new__(SigaaClient)
    client.profile = get("ufpb").profile

    def menu_post(turma, label, turma_html=None):
        clicked.append(label)
        return PARTICIPANTES

    client._turma_menu_post = menu_post

    classmates = client.list_classmates(CALCULO)

    assert clicked == ["Participantes"]
    assert [c.name for c in classmates] == [
        "ALUNO UM DE EXEMPLO",
        "ALUNO DOIS DE EXEMPLO",
        "ALUNA TRÊS DE EXEMPLO",
    ]


def test_a_first_name_finds_the_classmate_in_every_shared_class():
    search = find_classmates(FakeClient(_rosters()), "Tres")

    assert search.complete
    assert search.searched == [CALCULO, FISICA]
    assert _names(search) == ["ALUNA TRÊS DE EXEMPLO"]
    assert search.matches[0].turmas == [CALCULO, FISICA]


def test_every_query_word_must_start_a_word_of_the_name():
    rosters = _rosters()

    assert _names(find_classmates(FakeClient(rosters), "aluno ex")) == [
        "ALUNO DOIS DE EXEMPLO",
        "ALUNO UM DE EXEMPLO",
    ]
    assert _names(find_classmates(FakeClient(rosters), "luno")) == []
    assert _names(find_classmates(FakeClient(rosters), "aluno colega")) == []


def test_an_unreadable_roster_makes_the_search_incomplete():
    failure = UnrecognizedPageError("classmates", "fingerprint")
    search = find_classmates(FakeClient(_rosters(**{FISICA.id_turma: failure})), "tres")

    assert not search.complete
    assert search.searched == [CALCULO]
    assert search.matches[0].turmas == [CALCULO]
    assert search_to_dict(search)["errors"] == [
        {
            "class_id": "900002",
            "code": "TEST0002",
            "name": "FÍSICA DE EXEMPLO",
            "error": "unrecognized classmates page",
        }
    ]


def test_a_blank_query_is_refused_before_any_roster_is_read():
    fake = FakeClient(_rosters())

    with pytest.raises(ValueError, match="empty"):
        find_classmates(fake, "   ")
    assert fake.read == []


def test_an_institution_without_the_capability_is_refused():
    fake = FakeClient(_rosters(), institution="ufcg")

    with pytest.raises(UnsupportedFeatureError):
        find_classmates(fake, "tres")
    assert fake.read == []


def test_cli_json_uses_the_shared_contract(monkeypatch, capsys):
    monkeypatch.setattr(cli_module, "SigaaClient", _client_factory(FakeClient(_rosters())))
    args = cli_module._build_parser().parse_args(["classmates", "tres", "--json"])

    assert cli_module._cmd_classmates(args, _settings()) == 0
    assert json.loads(capsys.readouterr().out) == {
        "query": "tres",
        "complete": True,
        "classes_searched": 2,
        "matches": [
            {
                "name": "ALUNA TRÊS DE EXEMPLO",
                "classes": [
                    {"class_id": "900001", "code": "TEST0001", "name": "CÁLCULO DE EXEMPLO"},
                    {"class_id": "900002", "code": "TEST0002", "name": "FÍSICA DE EXEMPLO"},
                ],
            }
        ],
        "errors": [],
    }


def test_cli_lists_each_match_under_its_classes(monkeypatch, capsys):
    monkeypatch.setattr(cli_module, "SigaaClient", _client_factory(FakeClient(_rosters())))
    args = cli_module._build_parser().parse_args(["classmates", "aluna"])

    assert cli_module._cmd_classmates(args, _settings()) == 0
    assert capsys.readouterr().out.splitlines() == [
        "ALUNA TRÊS DE EXEMPLO",
        "  TEST0001     CÁLCULO DE EXEMPLO",
        "  TEST0002     FÍSICA DE EXEMPLO",
    ]


def test_cli_reports_no_match_with_the_classes_searched(monkeypatch, capsys):
    monkeypatch.setattr(cli_module, "SigaaClient", _client_factory(FakeClient(_rosters())))
    args = cli_module._build_parser().parse_args(["classmates", "ninguem"])

    assert cli_module._cmd_classmates(args, _settings()) == 0
    assert capsys.readouterr().out == "no classmate matching 'ninguem' in 2 classes\n"


def test_cli_exits_nonzero_when_a_roster_was_not_read(monkeypatch, capsys):
    failure = UnrecognizedPageError("classmates", "fingerprint")
    fake = FakeClient(_rosters(**{FISICA.id_turma: failure}))
    monkeypatch.setattr(cli_module, "SigaaClient", _client_factory(fake))
    args = cli_module._build_parser().parse_args(["classmates", "ninguem"])

    assert cli_module._cmd_classmates(args, _settings()) == 1
    captured = capsys.readouterr()
    assert captured.out == "no classmate matching 'ninguem' in 1 classes\n"
    assert "roster of TEST0002 not read: unrecognized classmates page" in captured.err


def test_cli_login_failure_exits_nonzero(monkeypatch, capsys):
    fake = FakeClient(_rosters(), login_failure=AuthError("login rejected"))
    monkeypatch.setattr(cli_module, "SigaaClient", _client_factory(fake))
    args = cli_module._build_parser().parse_args(["classmates", "tres", "--json"])

    assert cli_module._cmd_classmates(args, _settings()) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "classmate lookup failed: login rejected" in captured.err


@pytest.fixture
def mcp_server():
    pytest.importorskip("mcp")
    from sigaa import mcp_server

    return mcp_server


def test_mcp_tool_returns_the_shared_contract(monkeypatch, mcp_server):
    monkeypatch.setattr(mcp_server, "Settings", _settings)
    monkeypatch.setattr(mcp_server, "SigaaClient", _client_factory(FakeClient(_rosters())))

    result = mcp_server.sigaa_find_classmate("tres")

    assert "sigaa_find_classmate" in mcp_server.mcp._tool_manager._tools
    assert result == search_to_dict(find_classmates(FakeClient(_rosters()), "tres"))


def test_mcp_tool_raises_when_the_lookup_fails(monkeypatch, mcp_server):
    from mcp.server.fastmcp.exceptions import ToolError

    fake = FakeClient(_rosters(), login_failure=AuthError("login rejected"))
    monkeypatch.setattr(mcp_server, "Settings", _settings)
    monkeypatch.setattr(mcp_server, "SigaaClient", _client_factory(fake))

    with pytest.raises(ToolError, match="classmate lookup failed: login rejected"):
        mcp_server.sigaa_find_classmate("tres")


def test_mcp_tool_requires_credentials(monkeypatch, mcp_server):
    from mcp.server.fastmcp.exceptions import ToolError

    settings = SimpleNamespace(institution="ufpb", username=None, resolve_password=lambda: None)
    monkeypatch.setattr(mcp_server, "Settings", lambda: settings)

    with pytest.raises(ToolError, match="no credentials"):
        mcp_server.sigaa_find_classmate("tres")
