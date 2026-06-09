from pathlib import Path

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
    assert parse_turma_grades("<html><body>no grades</body></html>", ID_TURMA) is None


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
