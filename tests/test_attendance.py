from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from sigaa.errors import ParseError
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
    with pytest.raises(ParseError):
        parse_attendance("<html><body>nothing</body></html>", ID_TURMA)


def _map(edit):
    soup = BeautifulSoup(FREQUENCIA, "lxml")
    edit(soup)
    return str(soup)


def test_map_without_a_table_is_an_empty_attendance():
    html = _map(lambda soup: soup.select_one("fieldset table").decompose())

    att = parse_attendance(html, ID_TURMA)

    assert att.records == []
    assert att.total_absences == 6


@pytest.mark.parametrize("remove", ["fieldset tbody tr", "fieldset tbody"])
def test_map_without_rows_is_an_empty_attendance(remove):
    def edit(soup):
        for node in soup.select(remove):
            node.decompose()

    assert parse_attendance(_map(edit), ID_TURMA).records == []


def test_tables_outside_the_map_are_ignored():
    def edit(soup):
        layout = BeautifulSoup(
            "<table><tbody><tr><td>menu</td></tr><tr><td>menu</td></tr></tbody></table>", "lxml"
        ).table
        soup.body.insert(0, layout)

    assert len(parse_attendance(_map(edit), ID_TURMA).records) == 3


def test_single_cell_rows_are_skipped_as_before():
    def edit(soup):
        row = BeautifulSoup('<tr><td colspan="3">Aula não registrada</td></tr>', "lxml").tr
        soup.select_one("fieldset tbody").append(row)

    assert len(parse_attendance(_map(edit), ID_TURMA).records) == 3


def test_reordered_columns_are_not_read_positionally():
    def edit(soup):
        for row in soup.select("fieldset table tr"):
            row.append(row.find(["td", "th"]).extract())

    with pytest.raises(ParseError):
        parse_attendance(_map(edit), ID_TURMA)
