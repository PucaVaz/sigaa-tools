from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from sigaa.errors import ParseError
from sigaa.models import Turma, TurmaGrade
from sigaa.parsers.grades import parse_turma_grades
from sigaa.store.db import connect
from sigaa.store.repository import Repository

FIXTURES = Path(__file__).parent / "fixtures"
VERNOTAS = (FIXTURES / "vernotas.html").read_text(encoding="utf-8")
ID_TURMA = "369279"


def test_parse_turma_grades_extracts_student_row():
    g = parse_turma_grades(VERNOTAS, ID_TURMA)
    assert g is not None
    assert g.id_turma == ID_TURMA
    assert g.units == ["8.0", "7.5"]  # empty Unid. 3 dropped
    assert g.exam is None
    assert g.result == "7.8"
    assert g.absences == "4"
    assert g.status == "APROVADO"


def test_parse_turma_grades_no_table_returns_none():
    with pytest.raises(ParseError):
        parse_turma_grades("<html><body>no grades</body></html>", ID_TURMA)


def _report(edit):
    soup = BeautifulSoup(VERNOTAS, "lxml")
    edit(soup)
    return str(soup)


def test_another_report_table_before_the_grades_is_ignored():
    def edit(soup):
        legend = BeautifulSoup(
            '<table class="tabelaRelatorio"><tr><th>Legenda</th></tr>'
            "<tr><td>REP: reprovado</td></tr></table>", "lxml"
        ).table
        soup.body.insert(0, legend)

    assert parse_turma_grades(_report(edit), ID_TURMA) == parse_turma_grades(VERNOTAS, ID_TURMA)


@pytest.mark.parametrize("remove", ["tbody tr", "tbody"])
def test_report_without_a_data_row_has_no_grade(remove):
    def edit(soup):
        for node in soup.select(f"table.tabelaRelatorio {remove}"):
            node.decompose()

    assert parse_turma_grades(_report(edit), ID_TURMA) is None


def test_a_row_that_does_not_fit_the_header_still_fails():
    def edit(soup):
        soup.select_one("table.tabelaRelatorio tbody td").decompose()

    with pytest.raises(ParseError):
        parse_turma_grades(_report(edit), ID_TURMA)


def test_turma_grade_store_roundtrip(tmp_path):
    repo = Repository(connect(tmp_path / "t.db"))
    repo.upsert_turma(Turma(id_turma=ID_TURMA, name="SISTEMAS DISTRIBUÍDOS", code="DSCO00022"))
    repo.upsert_turma_grade(
        TurmaGrade(id_turma=ID_TURMA, units=["8.0", "7.5"], result="7.8",
                   absences="4", status="APROVADO")
    )
    stored = repo.get_turma_grades(id_turma=ID_TURMA)
    assert len(stored) == 1
    assert stored[0].units == ["8.0", "7.5"]
    assert stored[0].status == "APROVADO"


def test_turma_grade_upsert_overwrites(tmp_path):
    repo = Repository(connect(tmp_path / "t.db"))
    repo.upsert_turma(Turma(id_turma=ID_TURMA, name="SD", code="DSCO00022"))
    repo.upsert_turma_grade(TurmaGrade(id_turma=ID_TURMA, units=["8.0"]))
    repo.upsert_turma_grade(TurmaGrade(id_turma=ID_TURMA, units=["8.0", "9.0"], result="8.5"))
    stored = repo.get_turma_grades(id_turma=ID_TURMA)
    assert len(stored) == 1
    assert stored[0].units == ["8.0", "9.0"]
    assert stored[0].result == "8.5"


def _repo(tmp_path):
    repo = Repository(connect(tmp_path / "t.db"))
    repo.upsert_turma(Turma(id_turma=ID_TURMA, name="SD", code="DSCO00022"))
    return repo


def test_empty_grade_is_not_notable(tmp_path):
    repo = _repo(tmp_path)
    notable = repo.upsert_turma_grade(
        TurmaGrade(id_turma=ID_TURMA, units=[], absences="0", status="MATRICULADO")
    )
    assert notable is False
    assert repo.get_turma_grades(unread_only=True) == []


def test_posted_grade_is_notable_and_unread(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_turma_grade(TurmaGrade(id_turma=ID_TURMA, units=[], status="MATRICULADO"))
    notable = repo.upsert_turma_grade(TurmaGrade(id_turma=ID_TURMA, units=["8.0"]))
    assert notable is True
    unread = repo.get_turma_grades(unread_only=True)
    assert len(unread) == 1 and unread[0].units == ["8.0"]


def test_unchanged_grade_is_not_notable(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_turma_grade(TurmaGrade(id_turma=ID_TURMA, units=["8.0"]))
    assert repo.upsert_turma_grade(TurmaGrade(id_turma=ID_TURMA, units=["8.0"])) is False


def test_terminal_status_change_is_notable(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_turma_grade(TurmaGrade(id_turma=ID_TURMA, units=["8.0"], status="MATRICULADO"))
    assert repo.upsert_turma_grade(
        TurmaGrade(id_turma=ID_TURMA, units=["8.0"], result="8.0", status="APROVADO")
    ) is True


def test_mark_turma_grades_seen_clears_unread(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_turma_grade(TurmaGrade(id_turma=ID_TURMA, units=["8.0"]))
    repo.mark_turma_grades_seen([ID_TURMA])
    assert repo.get_turma_grades(unread_only=True) == []
