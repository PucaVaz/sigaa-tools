from pathlib import Path

from sigaa.parsers.plano import parse_course_plan

FIXTURES = Path(__file__).parent / "fixtures"
PLANO = (FIXTURES / "plano.html").read_text(encoding="utf-8")
ID_TURMA = "369279"


def test_parse_course_plan_extracts_schedule():
    plan = parse_course_plan(PLANO, ID_TURMA)
    assert plan is not None
    assert plan.id_turma == ID_TURMA
    assert plan.schedule[0].start == "28/04/2026"
    assert plan.schedule[0].end == "05/05/2026"
    assert plan.schedule[0].description == "Visão geral e introdução"
    assert len(plan.schedule) >= 5


def test_parse_course_plan_extracts_evaluations():
    plan = parse_course_plan(PLANO, ID_TURMA)
    evals = {e.description: e.date for e in plan.evaluations}
    assert evals["1ª avaliação"] == "11/06/2026"
    assert evals["Exame Final"] == "13/08/2026"
    assert len(plan.evaluations) == 5


def test_parse_course_plan_no_tables_returns_none():
    assert parse_course_plan("<html><body>nothing</body></html>", ID_TURMA) is None
