"""Parse a turma's Frequência page (Mapa de Frequências)."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ._variants import page_parser
from ._common import fold

from ..models import Attendance, AttendanceRecord

_TOTAL_RE = re.compile(r"Total de Faltas:\s*(\d+)")
_JUSTIFIED_RE = re.compile(r"Total de Faltas Justificadas:\s*(\d+)")
_MAX_RE = re.compile(r"M[áa]ximo de Faltas Permitido:\s*(\d+)")


def parse_attendance(html: str, id_turma: str) -> Attendance | None:
    """Extract the attendance map. Returns None if the page has no map."""
    soup = BeautifulSoup(html, "lxml")
    legend = next(
        (lg for lg in soup.find_all("legend")
         if "mapa de frequ" in lg.get_text(strip=True).casefold()),
        None,
    )
    if legend is None:
        return None
    fieldset = legend.find_parent("fieldset")
    if fieldset is None:
        return None

    records = []
    table = fieldset.find("table")
    if table is not None:
        for row in table.select("tbody tr"):
            cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
            if len(cells) < 2:
                continue
            records.append(
                AttendanceRecord(
                    date=cells[0],
                    status=cells[1],
                    justified=len(cells) > 2 and cells[2].casefold().startswith("sim"),
                )
            )

    text = fieldset.get_text(" ", strip=True)
    return Attendance(
        id_turma=id_turma,
        records=records,
        total_absences=_int(_TOTAL_RE, text),
        justified_absences=_int(_JUSTIFIED_RE, text),
        max_absences=_int(_MAX_RE, text),
    )


def _int(pattern: re.Pattern, text: str) -> int | None:
    match = pattern.search(text)
    return int(match.group(1)) if match else None


def _recognized_map(soup):
    return any("mapa de frequ" in fold(lg.get_text()) for lg in soup.select("fieldset legend"))


def _valid_map(result, soup):
    if result is None:
        return False
    headers = {fold(th.get_text()) for th in soup.select("table th")}
    return {"data", "situacao"}.issubset(headers) and (
        len(result.records) == len(soup.select("table tbody tr")) and bool(soup.select("table tbody"))
    )


parse_attendance = page_parser("attendance", _recognized_map, validate=_valid_map,
                               name="frequency-map")(parse_attendance)
