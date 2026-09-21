"""Every live CLI command and MCP tool turns a parse or navigation failure into
its surface's normal error shape instead of a traceback."""

import secrets
from types import SimpleNamespace

import pytest

from sigaa import cli
from sigaa.errors import NavigationError, UnrecognizedPageError
from sigaa.models import Turma
from sigaa.parsers import tarefa as tarefa_parser

pytest.importorskip("mcp")

from mcp.server.fastmcp.exceptions import ToolError  # noqa: E402

from sigaa import mcp_server  # noqa: E402

TURMA = Turma(id_turma="369279", name="SISTEMAS DISTRIBUÍDOS", code="DSCO00022")
# An avaliação event page: no detail form, so the task parser does not recognize it.
AVALIACAO_PAGE = "<html><body><h3>Avaliação</h3><p>1ª avaliação em sala.</p></body></html>"


def _unrecognized(*args, **kwargs):
    raise UnrecognizedPageError("attendance", {})


def _fake_client(**methods):
    class FakeClient:
        def __init__(self, username, password, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def close(self):
            pass

        def list_turmas(self):
            return [TURMA]

    for name, method in methods.items():
        setattr(FakeClient, name, staticmethod(method))
    return FakeClient


def _settings(tmp_path):
    return SimpleNamespace(
        institution="ufpb",
        username="configured-user",
        db_path=tmp_path / "sigaa.db",
        resolve_password=lambda: secrets.token_urlsafe(),
        credentials_problem=lambda: None,
    )


@pytest.fixture
def mcp_live(monkeypatch, tmp_path):
    def configure(deadline_kind="avaliacao", **methods):
        deadline = SimpleNamespace(id="45959072", kind=deadline_kind, title="1ª avaliação",
                                   body=None)
        news = SimpleNamespace(id="1", id_turma=TURMA.id_turma, body=None)
        repo = SimpleNamespace(
            get_deadlines=lambda: [deadline],
            get_news=lambda: [news],
            get_turma=lambda code: None,
        )
        monkeypatch.setattr(mcp_server, "_repo", lambda: repo)
        monkeypatch.setattr(mcp_server, "Settings", lambda: _settings(tmp_path))
        monkeypatch.setattr(mcp_server, "SigaaClient", _fake_client(**methods))
    return configure


@pytest.mark.parametrize("kind", ["avaliacao", "enquete"])
def test_tarefa_tool_keeps_its_friendly_answer_for_an_event_that_is_not_a_task(mcp_live, kind):
    mcp_live(deadline_kind=kind, get_tarefa_body=lambda event_id: (
        tarefa_parser.parse_tarefa_body(AVALIACAO_PAGE)))

    result = mcp_server.sigaa_get_tarefa_body("45959072")

    assert result == {"error": "no detail form on this event (it may not be a tarefa)"}


def test_tarefa_tool_reports_an_unrecognized_task_page(mcp_live):
    mcp_live(deadline_kind="tarefa", get_tarefa_body=lambda event_id: (
        tarefa_parser.parse_tarefa_body(AVALIACAO_PAGE)))

    result = mcp_server.sigaa_get_tarefa_body("45959072")

    assert result == {"error": "task page not recognized: unrecognized task page"}


def test_tarefa_tool_reports_an_event_missing_from_the_portal(mcp_live):
    def missing(event_id):
        raise NavigationError(f"portal event not found: {event_id!r}")

    mcp_live(deadline_kind="tarefa", get_tarefa_body=missing)

    result = mcp_server.sigaa_get_tarefa_body("45959072")

    assert result == {"error": "task lookup failed: portal event not found: '45959072'"}


def test_attachment_tool_reports_parse_failures_as_a_message(mcp_live):
    mcp_live(download_tarefa_attachment=_unrecognized)

    assert mcp_server.sigaa_download_tarefa_anexo("45959072").startswith("download failed:")


def test_news_body_tool_reports_parse_failures_as_a_message(mcp_live):
    mcp_live(get_news_body=_unrecognized)

    assert mcp_server.sigaa_get_news_body("1").startswith("could not fetch this news body:")


@pytest.mark.parametrize("tool, method", [
    (mcp_server.sigaa_get_attendance, "get_attendance"),
    (mcp_server.sigaa_get_course_plan, "get_course_plan"),
])
def test_live_class_tools_report_parse_failures_as_an_error(mcp_live, tool, method):
    mcp_live(**{method: _unrecognized})

    assert tool(TURMA.code)["error"].endswith("unrecognized attendance page")


def test_live_class_tools_report_an_unrecognized_portal(mcp_live):
    mcp_live(list_turmas=_unrecognized)

    assert mcp_server.sigaa_get_attendance(TURMA.code) == {
        "error": "class lookup failed: unrecognized attendance page"
    }


def test_matricula_tool_reports_parse_failures_in_its_list_shape(mcp_live):
    mcp_live(list_open_turmas=_unrecognized)

    assert mcp_server.sigaa_matricula_open_turmas() == [
        {"error": "matrícula lookup failed: unrecognized attendance page"}
    ]


def test_document_tool_raises_a_tool_error(mcp_live, monkeypatch, tmp_path):
    def missing(kind):
        raise NavigationError("portal document menu item not found: 'Histórico acadêmico'")

    monkeypatch.setattr(mcp_server, "default_download_dir", lambda: tmp_path)
    mcp_live(download_academic_document=missing)

    with pytest.raises(ToolError, match="download failed: portal document menu item"):
        mcp_server.sigaa_download_historico()


@pytest.fixture
def cli_live(monkeypatch, tmp_path):
    def configure(**methods):
        monkeypatch.setattr(cli, "SigaaClient", _fake_client(**methods))
        monkeypatch.setattr(cli, "_settings", lambda args, institution: _settings(tmp_path))
    return configure


@pytest.mark.parametrize("argv, method, prefix", [
    (["attendance", "--class", "DSCO00022"], "get_attendance", "attendance lookup failed"),
    (["plan", "--class", "DSCO00022"], "get_course_plan", "course plan lookup failed"),
    (["attendance", "--class", "DSCO00022"], "list_turmas", "class lookup failed"),
    (["matricula"], "open_matricula_curriculo", "matrícula failed"),
    (["curriculum"], "get_curriculum_status", "curriculum lookup failed"),
    (["cra"], "get_cra", "CRA lookup failed"),
    (["historico"], "download_academic_document", "download failed"),
    (["materials", "--download-all"], "list_turmas", "download failed"),
])
def test_cli_reports_parse_failures_without_a_traceback(cli_live, capsys, argv, method, prefix):
    cli_live(**{method: _unrecognized})

    assert cli.main(argv) == 1

    assert f"{prefix}: unrecognized attendance page" in capsys.readouterr().err
