from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from sigaa.errors import ParseError
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
    with pytest.raises(ParseError):
        parse_course_plan("<html><body>nothing</body></html>", ID_TURMA)


def _plan(edit):
    soup = BeautifulSoup(PLANO, "lxml")
    edit(soup)
    return str(soup)


def _schedule_table(soup):
    return next(c for c in soup.select("caption") if "Cronograma" in c.get_text()).parent


def test_rows_the_reader_skips_do_not_fail_the_plan():
    def edit(soup):
        tbody = _schedule_table(soup).tbody
        tbody.append(BeautifulSoup('<tr><td colspan="3">Sem aula (feriado)</td></tr>', "lxml").tr)
        tbody.append(BeautifulSoup("<tr><td></td><td>x</td><td>y</td></tr>", "lxml").tr)

    plan = parse_course_plan(_plan(edit), ID_TURMA)

    assert len(plan.schedule) == len(parse_course_plan(PLANO, ID_TURMA).schedule)


def test_other_tables_on_the_plan_page_are_not_checked():
    def edit(soup):
        extra = BeautifulSoup(
            "<table><caption>Avaliações anteriores</caption><tbody>"
            "<tr><td>a</td><td>b</td><td>c</td><td>d</td></tr></tbody></table>", "lxml"
        ).table
        soup.body.append(extra)

    assert len(parse_course_plan(_plan(edit), ID_TURMA).evaluations) == 5


def test_schedule_columns_in_another_order_are_not_read_positionally():
    def edit(soup):
        for row in _schedule_table(soup).select("tr"):
            row.append(row.find(["td", "th"]).extract())

    with pytest.raises(ParseError):
        parse_course_plan(_plan(edit), ID_TURMA)
