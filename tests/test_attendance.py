from pathlib import Path

from sigaa.parsers.attendance import parse_attendance

FIXTURES = Path(__file__).parent / "fixtures"
FREQUENCIA = (FIXTURES / "frequencia.html").read_text(encoding="utf-8")
ID_TURMA = "369279"


def test_parse_attendance_extracts_records_and_totals():
    att = parse_attendance(FREQUENCIA, ID_TURMA)
    assert att is not None
    assert att.id_turma == ID_TURMA
    assert len(att.records) == 3
    assert att.records[0].date == "07/05/2026"
    assert att.records[0].status == "2 Falta(s)"
    assert att.records[0].justified is False
    assert att.total_absences == 6
    assert att.justified_absences == 0
    assert att.max_absences == 15


def test_parse_attendance_no_map_returns_none():
    assert parse_attendance("<html><body>nothing</body></html>", ID_TURMA) is None
