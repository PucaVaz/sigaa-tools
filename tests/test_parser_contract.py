"""Structural contracts use synthetic pages; live empty-state acceptance is separate."""
from pathlib import Path
import json

from bs4 import BeautifulSoup
import pytest

from sigaa.errors import ParseError, error_stage, UnrecognizedPageError
from sigaa.onboard.features import FEATURES
from sigaa.parsers._common import page_fingerprint
from sigaa.parsers._variants import resolve_variant
from sigaa.parsers.grades import parse_grades

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("feature", FEATURES, ids=lambda f: f.key)
def test_every_page_parser_rejects_auth_redirect(feature):
    with pytest.raises(ParseError) as caught:
        feature.parse((FIXTURES / "auth_redirect.html").read_text(), "123")
    assert error_stage(caught.value) == "parse"


@pytest.mark.parametrize("feature", FEATURES, ids=lambda f: f.key)
def test_every_page_parser_rejects_unrecognized_markup(feature):
    with pytest.raises(ParseError):
        feature.parse('<html><table class="new-layout"><tr><td>Unexpected</td></tr></table></html>', "123")


def test_fingerprint_excludes_private_cells_inputs_queries_and_heading_values():
    private = "SENSITIVE-EXAMPLE"
    html = f'<form action="/page?token={private}"><input value="{private}"></form>'
    html += f'<table><caption>{private}</caption><tr><td>{private}</td></tr></table>'
    assert private not in json.dumps(page_fingerprint(html))
    changed = html.replace(f'<td>{private}</td>', '<td>OTHER</td>').replace(f'value="{private}"', 'value="OTHER"')
    assert page_fingerprint(html) == page_fingerprint(changed)


def test_grades_use_headers_after_column_reordering():
    soup = BeautifulSoup((FIXTURES / "grades.html").read_text(), "lxml")
    for row in soup.select("table tr"):
        first = row.find(["td", "th"])
        if first:
            row.append(first.extract())
    html = str(soup)
    assert resolve_variant("grades", html, parse_grades.variants).name == "grade-headers"
    assert parse_grades(html) == parse_grades((FIXTURES / "grades.html").read_text())


def test_grades_do_not_discard_a_malformed_row():
    soup = BeautifulSoup((FIXTURES / "grades.html").read_text(), "lxml")
    soup.select_one("tbody td").extract()
    with pytest.raises(UnrecognizedPageError):
        parse_grades(str(soup))


@pytest.mark.parametrize("feature", [f for f in FEATURES if (FIXTURES / f"{f.key}_empty.html").exists()], ids=lambda f: f.key)
def test_synthetic_empty_contract(feature):
    html = (FIXTURES / f"{feature.key}_empty.html").read_text()
    if feature.key in {"student", "task"}:
        # Missing identity/task details can never be reported as confirmed empty.
        with pytest.raises(ParseError):
            feature.parse(html, "123")
    else:
        result = feature.parse(html, "123")
        if feature.key == "attendance":
            assert result.records == []
        elif feature.key == "plan":
            assert result.schedule == result.evaluations == []
        else:
            assert not result
    with pytest.raises(ParseError):
        feature.parse((FIXTURES / f"{feature.key}_changed_markup.html").read_text(), "123")


def test_attendance_uses_headers_after_column_reordering():
    from sigaa.parsers.attendance import parse_attendance
    original = (FIXTURES / "frequencia.html").read_text()
    soup = BeautifulSoup(original, "lxml")
    for row in soup.select("table tr"):
        row.append(row.find(["td", "th"]).extract())
    assert parse_attendance(str(soup), "123") == parse_attendance(original, "123")


def test_class_grades_reject_an_ambiguous_second_student_row():
    from sigaa.parsers.grades import parse_turma_grades
    soup = BeautifulSoup((FIXTURES / "vernotas.html").read_text(), "lxml")
    row = soup.select_one("tbody tr")
    row.parent.append(BeautifulSoup(str(row), "lxml").find("tr"))
    with pytest.raises(UnrecognizedPageError):
        parse_turma_grades(str(soup), "123")


def test_deadlines_reject_partial_results_when_one_link_changes():
    from sigaa.parsers.portal import parse_deadlines
    soup = BeautifulSoup((FIXTURES / "portal.html").read_text(), "lxml")
    anchor = soup.select_one('ul[class*="dropdown-menu-atividade"] a[onclick]')
    anchor["onclick"] = "changedPostback()"
    with pytest.raises(UnrecognizedPageError):
        parse_deadlines(str(soup))
