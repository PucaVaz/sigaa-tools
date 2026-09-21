"""Parse the Turma Virtual 'Participantes' page.

Only the teaching staff is extracted. The page also lists every enrolled
student (names and personal e-mail addresses); that block is deliberately
never parsed or returned.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import Professor
from ._common import fold
from ._common import normalized as _normalized
from ._variants import page_parser

_PROFESSOR_LEGEND_RE = re.compile(r"professor(es)?\b")
_DEPARTMENT_LABEL = "departamento"
_EMAIL_LABEL = "e-mail"


def _professor_legend(soup: BeautifulSoup):
    for legend in soup.select("fieldset legend"):
        if _PROFESSOR_LEGEND_RE.match(_normalized(legend.get_text(" ", strip=True))):
            return legend
    return None


def _professor_count(soup):
    """The count in the same 'Professores (n)' legend the table is read from."""
    legend = _professor_legend(soup)
    match = re.fullmatch(r"professores?\s*\((\d+)\)", fold(legend.get_text())) if legend else None
    return int(match.group(1)) if match else None


@page_parser(
    "professors",
    lambda soup: _professor_count(soup) is not None,
    empty=lambda soup: _professor_count(soup) == 0,
    validate=lambda result, soup: len(result) == _professor_count(soup),
    name="participants-role-count",
)
def parse_professors(soup: BeautifulSoup, id_turma: str) -> list[Professor]:
    """Teaching staff listed under the 'Professores' fieldset of a turma."""
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
    legend = _professor_legend(soup)
    if legend is None:
        return None
    table = legend.find_parent("fieldset").find_next(["table", "fieldset"])
    if table is not None and table.name == "table" and "participantes" in table.get("class", []):
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

