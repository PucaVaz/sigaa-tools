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


def _map_fieldset(soup: BeautifulSoup):
    """The fieldset under the 'Mapa de Frequências' legend; every read is scoped to it."""
    legend = next(
        (lg for lg in soup.find_all("legend") if "mapa de frequ" in fold(lg.get_text())),
        None,
    )
    return legend.find_parent("fieldset") if legend is not None else None


def _valid_map(result, soup):
    """A map without a table or without rows is the state the parser has always
    accepted (nothing posted yet; not yet seen live). A table that labels its
    columns must start with the two the positional reader relies on."""
    table = _map_fieldset(soup).find("table")
    if table is None:
        return True
    headers = [fold(th.get_text(" ", strip=True)) for th in table.select("th")]
    return not headers or headers[:2] == ["data", "situacao"]


@page_parser(
    "attendance",
    lambda soup: _map_fieldset(soup) is not None,
    validate=_valid_map,
    name="frequency-map",
)
def parse_attendance(soup: BeautifulSoup, id_turma: str) -> Attendance | None:
    """Extract the attendance map. Returns None if the page has no map."""
    fieldset = _map_fieldset(soup)
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
