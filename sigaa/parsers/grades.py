"""Parse grade reports.

The Relatório de Notas has one ``tabelaRelatorio`` per semester (16 columns:
Código, Disciplina, Unidade 1..10, Exame Final, Resultado, Faltas, Situação).
A turma's Ver Notas report is a single ``tabelaRelatorio`` whose header drives a
variable column set (Matrícula, Nome, Unid. 1..N, Exame Final, Resultado, Faltas,
Sit.) with one data row — the student's own grades.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from ..models import Grade, TurmaGrade
from ..errors import UnrecognizedPageError
from ._common import fold, page_fingerprint
from ._variants import Variant, parse_with_variants, page_parser

_UNIT_COUNT = 10  # Unidade 1..10


def _parse_grades_16col(soup: BeautifulSoup) -> list[Grade]:
    grades: list[Grade] = []
    for table in soup.find_all("table", class_="tabelaRelatorio"):
        caption = table.find("caption")
        semester = caption.get_text(strip=True) if caption else ""
        for row in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
            if len(cells) < 16:
                continue  # header (<th>) or malformed row
            grades.append(_row_to_grade(semester, cells))
    return grades


def _row_to_grade(semester: str, cells: list[str]) -> Grade:
    code, discipline = cells[0], cells[1]
    units = cells[2 : 2 + _UNIT_COUNT]
    exam, result, absences, status = cells[12], cells[13], cells[14], cells[15]
    return Grade(
        semester=semester,
        code=code,
        discipline=discipline,
        units=[u for u in units if u],  # drop empty unit columns
        exam=_clean(exam),
        result=_clean(result),
        absences=_clean(absences),
        status=_clean(status),
    )


def _grade_tables(soup):
    return soup.select("table.tabelaRelatorio")


def _grade_headers(table):
    row = table.find("tr")
    return [fold(c.get_text(" ", strip=True)) for c in row.find_all(["th", "td"])] if row else []


def _turma_grade_table(soup):
    """The report table whose header names the student columns; reads stay inside it."""
    return next(
        (t for t in _grade_tables(soup)
         if {"matricula", "nome", "faltas"}.issubset(_grade_headers(t))),
        None,
    )


def _turma_grades_empty(soup):
    """No data row at all: nothing posted yet (not yet seen live). A row that
    does not fit the header is not empty and still fails."""
    return not any(row.find("td") for row in _turma_grade_table(soup).find_all("tr")[1:])


@page_parser(
    "turma_grades",
    lambda soup: _turma_grade_table(soup) is not None,
    empty=_turma_grades_empty,
    name="class-grade-headers",
)
def parse_turma_grades(soup: BeautifulSoup, id_turma: str) -> TurmaGrade | None:
    """Extract the student's grade row from a turma's Ver Notas report."""
    table = _turma_grade_table(soup)
    if table is None:
        return None
    rows = table.find_all("tr")
    if not rows:
        return None

    headers = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
    data = _first_data_row(rows[1:], len(headers))
    if data is None:
        return None

    by_label = dict(zip(headers, data))
    units = [v for label, v in by_label.items() if label.lower().startswith("unid") and v]
    return TurmaGrade(
        id_turma=id_turma,
        units=units,
        exam=_clean(by_label.get("Exame Final", "")),
        result=_clean(by_label.get("Resultado", "")),
        absences=_clean(by_label.get("Faltas", "")),
        status=_clean(by_label.get("Sit.", "")) or _clean(by_label.get("Situação", "")),
    )


def _first_data_row(rows, width: int) -> list[str] | None:
    for row in rows:
        cells = row.find_all("td")
        if len(cells) == width:
            return [c.get_text(" ", strip=True) for c in cells]
    return None


def _clean(value: str) -> str | None:
    value = value.strip()
    return None if value in ("", "--") else value


def _is_grades_report(soup):
    """The Relatório de Notas page itself, recognized even with no semester table.

    Not yet seen live for a student with no grades: the heading is the marker
    the report carries above its tables (see ACCEPTANCE.md).
    """
    return any(
        "relatorio de notas" in fold(node.get_text(" ", strip=True))
        for node in soup.select("h1, h2, h3, h4, legend, caption")
    )


def _matches_grades(soup):
    tables = _grade_tables(soup)
    if not tables:
        return _is_grades_report(soup)
    return all({"codigo", "disciplina", "resultado", "faltas", "situacao"}
               .issubset(_grade_headers(t)) for t in tables)


def _grades_by_header(soup):
    out = []
    for table in _grade_tables(soup):
        headers = _grade_headers(table)
        caption = table.find("caption")
        semester = caption.get_text(strip=True) if caption else ""
        for row in table.select("tr")[1:]:
            cells = row.find_all("td", recursive=False)
            if not cells:
                continue
            if len(cells) != len(headers):
                raise UnrecognizedPageError("grades", page_fingerprint(soup))
            values = dict(zip(headers, (c.get_text(" ", strip=True) for c in cells)))
            if not values["codigo"] or not values["disciplina"]:
                raise UnrecognizedPageError("grades", page_fingerprint(soup))
            out.append(Grade(semester=semester, code=values["codigo"], discipline=values["disciplina"],
                             units=[v for k, v in values.items() if k.startswith("unid") and v],
                             exam=_clean(values.get("exame final", "")), result=_clean(values["resultado"]),
                             absences=_clean(values["faltas"]), status=_clean(values["situacao"])))
    return out


def _grades_16col(soup):
    _grades_by_header(soup)  # verify row integrity before the positional compatibility reader
    return _parse_grades_16col(soup)


_GRADE_VARIANTS = (
    Variant("ufpb-16col", lambda soup: _matches_grades(soup) and all(
        _grade_headers(t) == ["codigo", "disciplina", *[f"unidade. {i}" for i in range(1, 11)],
                              "exame final", "resultado", "faltas", "situacao"]
        for t in _grade_tables(soup)), _grades_16col),
    Variant("grade-headers", _matches_grades, _grades_by_header),
)


def parse_grades(html: str) -> list[Grade]:
    return parse_with_variants("grades", html, _GRADE_VARIANTS)


parse_grades.variants = _GRADE_VARIANTS
parse_grades.feature = "grades"
