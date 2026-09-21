"""Structural contracts use synthetic pages; live empty-state acceptance is separate."""
from pathlib import Path
import json

from bs4 import BeautifulSoup
import pytest

from sigaa.errors import ParseError, error_stage, UnrecognizedPageError
from sigaa.onboard.features import FEATURES
from sigaa.parsers._common import page_fingerprint
from sigaa.parsers._variants import resolve_variant
from sigaa.parsers.attendance import parse_attendance
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
        feature.parse(
            '<html><table class="new-layout"><tr><td>Unexpected</td></tr></table></html>', "123"
        )


def test_fingerprint_excludes_private_cells_inputs_queries_and_heading_values():
    private = "SENSITIVE-EXAMPLE"
    html = f'<form action="/page?token={private}"><input value="{private}"></form>'
    html += f'<table><caption>{private}</caption><tr><td>{private}</td></tr></table>'
    assert private not in json.dumps(page_fingerprint(html))
    changed = html.replace(f"<td>{private}</td>", "<td>OTHER</td>")
    changed = changed.replace(f'value="{private}"', 'value="OTHER"')
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


def test_grades_16col_keeps_skipping_short_rows():
    soup = BeautifulSoup((FIXTURES / "grades.html").read_text(), "lxml")
    note = BeautifulSoup('<tr><td colspan="16">Trancamento em 2026.1</td></tr>', "lxml").tr
    soup.select_one("tbody").append(note)
    assert parse_grades(str(soup)) == parse_grades((FIXTURES / "grades.html").read_text())


def test_grades_16col_row_without_a_code_is_not_a_grade():
    soup = BeautifulSoup((FIXTURES / "grades.html").read_text(), "lxml")
    soup.select_one("tbody td").string = ""
    with pytest.raises(UnrecognizedPageError):
        parse_grades(str(soup))


def test_grades_by_header_do_not_discard_a_malformed_row():
    soup = BeautifulSoup((FIXTURES / "grades.html").read_text(), "lxml")
    for row in soup.select("table tr"):
        row.append(row.find(["td", "th"]).extract())
    soup.select_one("tbody td").extract()
    with pytest.raises(UnrecognizedPageError):
        parse_grades(str(soup))


WITH_EMPTY_FIXTURE = [f for f in FEATURES if (FIXTURES / f"{f.key}_empty.html").exists()]


@pytest.mark.parametrize("feature", WITH_EMPTY_FIXTURE, ids=lambda f: f.key)
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


@pytest.mark.parametrize("feature, fixture", [
    ("student", "portal.html"), ("turmas", "portal.html"), ("deadlines", "portal.html"),
    ("grades", "grades.html"), ("turma_grades", "vernotas.html"),
    ("attendance", "frequencia.html"), ("plan", "plano.html"),
    ("professors", "participantes.html"), ("materials", "materials.html"),
    ("task", "tarefa.html"),
])
def test_page_parsers_build_the_soup_once(feature, fixture, monkeypatch):
    built = []
    original = BeautifulSoup.__init__

    def counting(self, *args, **kwargs):
        built.append(1)
        original(self, *args, **kwargs)

    parser = next(f for f in FEATURES if f.key == feature)
    html = (FIXTURES / fixture).read_text()
    monkeypatch.setattr(BeautifulSoup, "__init__", counting)
    parser.parse(html, "123")
    assert len(built) == 1


def test_grades_report_without_semester_tables_is_empty():
    soup = BeautifulSoup((FIXTURES / "grades.html").read_text(), "lxml")
    for table in soup.select("table.tabelaRelatorio"):
        table.decompose()

    assert parse_grades(str(soup)) == []


def test_page_without_report_heading_or_tables_is_unrecognized():
    soup = BeautifulSoup((FIXTURES / "grades.html").read_text(), "lxml")
    for node in soup.select("table.tabelaRelatorio, h3"):
        node.decompose()

    with pytest.raises(UnrecognizedPageError):
        parse_grades(str(soup))


def test_a_password_confirmation_field_does_not_make_a_login_page():
    soup = BeautifulSoup((FIXTURES / "frequencia.html").read_text(), "lxml")
    confirm = BeautifulSoup(
        '<form id="confirmar"><input type="password" name="confirmar:senha"/></form>', "lxml"
    ).form
    soup.body.append(confirm)

    assert parse_attendance(str(soup), "123").records


@pytest.mark.parametrize("login_field", ["form:login", "user.login", "usuario"])
def test_a_login_form_is_never_parsed_as_content(login_field):
    soup = BeautifulSoup((FIXTURES / "frequencia.html").read_text(), "lxml")
    login = BeautifulSoup(
        f'<form><input type="text" name="{login_field}"/><input type="password" name="senha"/>'
        "</form>", "lxml"
    ).form
    soup.body.append(login)

    with pytest.raises(UnrecognizedPageError):
        parse_attendance(str(soup), "123")
