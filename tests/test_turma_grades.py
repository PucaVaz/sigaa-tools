from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from sigaa.errors import ParseError, UnrecognizedPageError
from sigaa.models import Assessment, Turma, TurmaGrade
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


NOT_POSTED = (FIXTURES / "turma_grades_not_posted.html").read_text(encoding="utf-8")


def test_notice_that_no_grade_was_posted_is_no_grade():
    assert parse_turma_grades(NOT_POSTED, ID_TURMA) is None


@pytest.mark.parametrize("message", [
    "Comportamento inesperado do sistema.",
    "Sua sessão expirou.",
])
def test_another_message_in_the_error_panel_still_fails(message):
    html = NOT_POSTED.replace("Ainda n&#227;o foram lan&#231;adas notas.", message)
    with pytest.raises(UnrecognizedPageError):
        parse_turma_grades(html, ID_TURMA)


def test_notice_text_outside_the_error_panel_is_not_trusted():
    def edit(soup):
        soup.select_one("#painel-erros").attrs["id"] = "outro-painel"

    soup = BeautifulSoup(NOT_POSTED, "lxml")
    edit(soup)
    with pytest.raises(UnrecognizedPageError):
        parse_turma_grades(str(soup), ID_TURMA)


SUB_ASSESSMENTS = (FIXTURES / "vernotas_sub_assessments.html").read_text(encoding="utf-8")


def test_unit_split_into_sub_assessments_keeps_the_posted_one():
    g = parse_turma_grades(SUB_ASSESSMENTS, ID_TURMA)
    assert g == TurmaGrade(
        id_turma=ID_TURMA,
        units=[],  # the Unid. 1 Nota column is still blank
        absences="0",
        status="MATRICULADO",
        assessments=[Assessment(unit="Unid. 1", label="T1", grade="7,5")],
    )


def _sub_report(edit):
    soup = BeautifulSoup(SUB_ASSESSMENTS, "lxml")
    edit(soup, soup.select("table.tabelaRelatorio tbody td"))
    return str(soup)


def test_sub_assessment_report_reads_unit_grades_and_the_columns_after_them():
    def edit(soup, cells):
        # Mat, Nome, T1..T4, Nota 1, Nota 2, Nota 3, Exame, Resultado, Faltas, Sit.
        for i, value in {3: "8,0", 6: "7,8", 7: "6,0", 10: "6,9"}.items():
            cells[i].string = value
        cells[12].string = "APROVADO"

    g = parse_turma_grades(_sub_report(edit), ID_TURMA)
    assert g.units == ["7,8", "6,0"]
    assert [(a.label, a.grade) for a in g.assessments] == [("T1", "7,5"), ("T2", "8,0")]
    assert (g.exam, g.result, g.absences, g.status) == (None, "6,9", "0", "APROVADO")


def test_sub_header_that_does_not_cover_the_spans_still_fails():
    def edit(soup, cells):
        soup.select_one("#trAval th#aval_48410395").decompose()

    with pytest.raises(UnrecognizedPageError):
        parse_turma_grades(_sub_report(edit), ID_TURMA)


def test_posted_sub_assessment_is_notable_and_stored(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_turma_grade(TurmaGrade(id_turma=ID_TURMA, status="MATRICULADO"))
    posted = TurmaGrade(id_turma=ID_TURMA, status="MATRICULADO",
                        assessments=[Assessment(unit="Unid. 1", label="T1", grade="7,5")])
    assert repo.upsert_turma_grade(posted) is True
    assert repo.get_turma_grades(unread_only=True) == [posted]
    assert repo.upsert_turma_grade(posted) is False


def test_store_created_before_assessments_gains_the_column(tmp_path):
    import sqlite3

    db = tmp_path / "t.db"
    repo = _repo(tmp_path)
    repo.upsert_turma_grade(TurmaGrade(id_turma=ID_TURMA, units=["8.0"]))
    legacy = sqlite3.connect(db)
    legacy.execute("ALTER TABLE turma_grade DROP COLUMN assessments")
    legacy.commit()
    legacy.close()

    [stored] = Repository(connect(db)).get_turma_grades(id_turma=ID_TURMA)
    assert stored.units == ["8.0"] and stored.assessments == []


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
