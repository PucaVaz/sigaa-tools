from datetime import date
from pathlib import Path

from sigaa.exporters.ics import build_calendar
from sigaa.models import Deadline, Turma
from sigaa.parsers import portal as portal_parser
from sigaa.parsers.grades import parse_grades

FIXTURES = Path(__file__).parent / "fixtures"
GRADES = (FIXTURES / "grades.html").read_text(encoding="utf-8")
PORTAL = (FIXTURES / "portal.html").read_text(encoding="utf-8")


def test_parse_grades():
    grades = parse_grades(GRADES)
    assert len(grades) == 2
    current = next(g for g in grades if g.semester == "2026.1")
    assert current.code == "DSCO00022"
    assert current.units == []
    assert current.result is None
    assert current.status == "MATRICULADO"

    past = next(g for g in grades if g.semester == "2025.1")
    assert past.units == ["7,0", "6,9", "9,0"]
    assert past.result == "7,6"
    assert past.absences == "0"
    assert past.status == "APROVADO"


def test_parse_deadlines():
    deadlines = portal_parser.parse_deadlines(PORTAL)
    assert len(deadlines) == 1
    d = deadlines[0]
    assert d.id == "45959072"
    assert d.id_turma == "369279"
    assert d.kind == "atividade"
    assert d.title == "Atividade 04 - Análise Léxica"
    assert d.date == "19/05 à 02/06"
    assert d.detail == "5 dias atrás"


def test_ics_class_event():
    turma = Turma(id_turma="1", name="SD", room="SALA 1", schedule_raw="35M45")
    ics = build_calendar([turma], [], term_start=date(2026, 6, 1))
    assert "BEGIN:VCALENDAR" in ics
    assert "SUMMARY:SD" in ics
    assert "RRULE:FREQ=WEEKLY;BYDAY=TU" in ics  # day 3 = Tuesday
    assert "RRULE:FREQ=WEEKLY;BYDAY=TH" in ics  # day 5 = Thursday


def test_ics_deadline_uses_last_date():
    dl = Deadline(id="9", id_turma="1", kind="atividade", title="ATV", date="19/05 à 02/06")
    ics = build_calendar([], [dl], year=2026)
    assert "DTSTART;VALUE=DATE:20260602" in ics  # latest DD/MM
    assert "SUMMARY:[atividade] ATV" in ics
