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


def parse_turma_grades(html: str, id_turma: str) -> TurmaGrade | None:
    """Extract the student's grade row from a turma's Ver Notas report."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_="tabelaRelatorio")
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
