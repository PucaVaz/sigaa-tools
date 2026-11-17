"""A Turma Virtual page is only trusted when it names the turma that was asked for.

SIGAA keeps the current turma in server-side navigation state. When that state
and the request disagree (a stale portal ViewState, a crossed postback) it still
answers HTTP 200 with another turma's page. The parsers stamp whatever
``id_turma`` they are handed, so without this check the content of one class is
stored under another.
"""

import pytest

from sigaa.client import SigaaClient
from sigaa.errors import STAGE_PARSE, NavigationError, WrongTurmaError, error_stage
from sigaa.institutions import get, ufpb
from sigaa.models import Turma
from sigaa.parsers.turma_header import displayed_turma_code

REQUESTED = Turma(
    id_turma="379201",
    name="INTRODUÇÃO AO PROCESSAMENTO DIGITAL DE IMAGENS",
    code="GDSCO0055",
    form_id="form_acessarTurmaVirtual",
    field="form_acessarTurmaVirtual:turmaVirtual",
)
OTHER_CODE = "DINF00054"

PORTAL = (
    '<html><body><form id="j_id_jsp_1_1">'
    '<input id="javax.faces.ViewState" name="javax.faces.ViewState" value="j_id1"/>'
    "</form></body></html>"
)


def _turma_page(code: str) -> str:
    """A Turma Virtual page (Principal or a menu page) with SIGAA's turma header."""
    menu = "".join(
        f"""<a href="#" onclick="jsfcljs(document.getElementById('formMenu'),"""
        f"""{{'menu:{slug}':'menu:{slug}'}},'');">{label}</a>"""
        for label, slug in (("Ver Notas", "notas"), ("Plano de Curso", "plano"))
    )
    return (
        "<html><body>"
        '<p id="linkCodigoTurma" style="display:inline-block;font-weight:bold;" '
        f'title="NOME">{code} - </p>'
        f'<form id="formMenu">{menu}'
        '<input id="javax.faces.ViewState" name="javax.faces.ViewState" value="j_id2"/>'
        "</form></body></html>"
    )


def _grade_report(code: str) -> str:
    """Ver Notas with posted grades: a bare report, no Turma Virtual header."""
    return (
        "<html><body>"
        f"<h3>{code} - INTRODU&#199;&#195;O AO PROCESSAMENTO DIGITAL DE IMAGENS"
        " - Turma: 01 (2026.2)</h3></body></html>"
    )


class _ScriptedSession:
    """Answers each kind of request from a queue, repeating the last answer."""

    def __init__(self, entries: list[str], menus: list[str] | None = None):
        self._entries = list(entries)
        self._menus = list(menus or [])
        self.entry_posts = 0
        self.portal_gets = 0

    def post(self, url: str, fields: dict) -> str:
        if url == ufpb.PORTAL_ACTION_URL:
            self.entry_posts += 1
            return self._next(self._entries)
        return self._next(self._menus)

    post_navigation = post

    def get(self, url: str) -> str:
        self.portal_gets += 1
        return PORTAL

    @staticmethod
    def _next(queue: list[str]) -> str:
        return queue.pop(0) if len(queue) > 1 else queue[0]


def _client(session: _ScriptedSession) -> SigaaClient:
    client = SigaaClient.__new__(SigaaClient)
    client.profile = ufpb.PROFILE
    client.navigator = get("ufpb").navigator
    client._session = session
    client._portal_html = PORTAL
    client._spent_principals = set()
    return client


def test_header_code_is_read_from_a_turma_virtual_page():
    assert displayed_turma_code(_turma_page("GDSCO0055")) == "GDSCO0055"


def test_header_code_is_read_from_a_posted_grade_report():
    assert displayed_turma_code(_grade_report("GDSCO0055")) == "GDSCO0055"


def test_a_page_without_a_turma_header_names_no_turma():
    assert displayed_turma_code("<html><body><h3>Avaliação - Unidade 1</h3></body></html>") is None


def test_entering_a_turma_returns_the_page_that_names_it():
    session = _ScriptedSession(entries=[_turma_page(REQUESTED.code)])

    assert _client(session).enter_turma(REQUESTED) == _turma_page(REQUESTED.code)
    assert session.portal_gets == 0


def test_entering_a_turma_refreshes_the_portal_once_when_another_turma_answers():
    session = _ScriptedSession(entries=[_turma_page(OTHER_CODE), _turma_page(REQUESTED.code)])

    page = _client(session).enter_turma(REQUESTED)

    assert displayed_turma_code(page) == REQUESTED.code
    assert session.portal_gets == 1
    assert session.entry_posts == 2


def test_entering_a_turma_fails_when_another_turma_keeps_answering():
    session = _ScriptedSession(entries=[_turma_page(OTHER_CODE)])

    with pytest.raises(WrongTurmaError) as failure:
        _client(session).enter_turma(REQUESTED)

    assert session.entry_posts == 2
    assert REQUESTED.code in str(failure.value)
    assert OTHER_CODE in str(failure.value)
    assert isinstance(failure.value, NavigationError)
    assert error_stage(failure.value) == STAGE_PARSE


def test_a_menu_page_of_another_turma_is_refused():
    session = _ScriptedSession(
        entries=[_turma_page(REQUESTED.code)], menus=[_turma_page(OTHER_CODE)]
    )

    with pytest.raises(WrongTurmaError):
        _client(session).get_course_plan(REQUESTED, _turma_page(REQUESTED.code))


def test_a_grade_report_of_another_turma_is_refused():
    session = _ScriptedSession(
        entries=[_turma_page(REQUESTED.code)], menus=[_grade_report(OTHER_CODE)]
    )

    with pytest.raises(WrongTurmaError):
        _client(session).get_turma_grades(REQUESTED, _turma_page(REQUESTED.code))


def test_a_page_that_names_no_turma_is_left_to_its_parser():
    headerless = "<html><body><form id='formMenu'></form></body></html>"
    session = _ScriptedSession(entries=[headerless])

    assert _client(session).enter_turma(REQUESTED) == headerless
    assert session.portal_gets == 0


def test_a_turma_without_a_code_cannot_be_checked():
    uncoded = Turma(id_turma="379201", name="SD", form_id="form", field="form:turma")
    session = _ScriptedSession(entries=[_turma_page(OTHER_CODE)])

    assert _client(session).enter_turma(uncoded) == _turma_page(OTHER_CODE)
