"""Parse the Turma Virtual 'Participantes' page.

Only the teaching staff is extracted. The page also lists every enrolled
student (names and personal e-mail addresses); that block is deliberately
never parsed or returned.
"""

from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup

from ..models import Professor

_PROFESSOR_LEGEND_RE = re.compile(r"professor(es)?\b")
_DEPARTMENT_LABEL = "departamento"
_EMAIL_LABEL = "e-mail"


def parse_professors(html: str, id_turma: str) -> list[Professor]:
    """Teaching staff listed under the 'Professores' fieldset of a turma."""
    soup = BeautifulSoup(html, "lxml")
    table = _professor_table(soup)
    if table is None:
        return []

    professors: list[Professor] = []
    for row in table.select("tr"):
        name_el = row.select_one("strong")
        name = name_el.get_text(" ", strip=True) if name_el else ""
        if not name:
            continue
        fields = _labelled_fields(row)
        professors.append(
            Professor(
                id_turma=id_turma,
                name=name,
                department=fields.get(_DEPARTMENT_LABEL),
                email=fields.get(_EMAIL_LABEL),
            )
        )
    return professors


def _professor_table(soup: BeautifulSoup):
    """The participantes table that follows the 'Professores (n)' legend.

    SIGAA renders one table per role, each preceded by its own fieldset legend,
    so the role is identified by the legend rather than by table position.
    """
    for legend in soup.select("fieldset legend"):
        if not _PROFESSOR_LEGEND_RE.match(_normalized(legend.get_text(" ", strip=True))):
            continue
        table = legend.find_parent("fieldset").find_next("table", class_="participantes")
        if table is not None:
            return table
    return None


def _labelled_fields(row) -> dict[str, str]:
    """Map each ``Label: <em>value</em>`` pair in the participant cell.

    The label is a bare text node in front of the value's ``em``, so the pair is
    recovered by walking back from each ``em`` rather than by line splitting.
    """
    fields: dict[str, str] = {}
    for value_el in row.select("em"):
        label = _preceding_label(value_el)
        value = value_el.get_text(" ", strip=True)
        if label and value:
            fields.setdefault(label, value)
    return fields


def _preceding_label(value_el) -> str | None:
    for node in value_el.previous_siblings:
        text = _normalized(node.get_text(" ", strip=True) if hasattr(node, "get_text") else str(node))
        if not text:
            continue
        return text.rstrip(":") if text.endswith(":") else None
    return None


def _normalized(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\xa0", " ")
    return " ".join(normalized.split()).casefold()
