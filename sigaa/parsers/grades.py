"""Parse the Relatório de Notas: one ``tabelaRelatorio`` per semester.

Each table has a ``<caption>`` with the semester and 16 columns:
Código, Disciplina, Unidade 1..10, Exame Final, Resultado, Faltas, Situação.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from ..models import Grade

_UNIT_COUNT = 10  # Unidade 1..10


def parse_grades(html: str) -> list[Grade]:
    soup = BeautifulSoup(html, "lxml")
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


def _clean(value: str) -> str | None:
    value = value.strip()
    return None if value in ("", "--") else value
