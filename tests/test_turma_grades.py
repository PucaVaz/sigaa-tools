from pathlib import Path

from sigaa.parsers.grades import parse_turma_grades

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
