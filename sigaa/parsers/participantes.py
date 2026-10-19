"""Parse the Turma Virtual 'Participantes' page.

The teaching staff is extracted in full. The page also lists every enrolled
student with a personal e-mail address; from that block only the names are
read, for live classmate lookups, and the e-mails are never parsed or returned.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import Classmate, Professor
from ._common import fold
from ._common import normalized as _normalized
from ._variants import page_parser

_PROFESSOR_LEGEND_RE = re.compile(r"professor(es)?\b")
_PROFESSOR_COUNT_RE = re.compile(r"professores?\s*\((\d+)\)")
_STUDENT_LEGEND_RE = re.compile(r"alunos?\b")
_STUDENT_COUNT_RE = re.compile(r"alunos?\s*\((\d+)\)")
_DEPARTMENT_LABEL = "departamento"
_EMAIL_LABEL = "e-mail"


def _role_legend(soup: BeautifulSoup, legend_re: re.Pattern):
    for legend in soup.select("fieldset legend"):
        if legend_re.match(_normalized(legend.get_text(" ", strip=True))):
            return legend
    return None


def _role_count(soup, legend_re: re.Pattern, count_re: re.Pattern):
    """The count in the same 'Role (n)' legend the role's table is read from."""
    legend = _role_legend(soup, legend_re)
    match = count_re.fullmatch(fold(legend.get_text())) if legend else None
    return int(match.group(1)) if match else None


def _professor_count(soup):
    return _role_count(soup, _PROFESSOR_LEGEND_RE, _PROFESSOR_COUNT_RE)


def _student_count(soup):
    return _role_count(soup, _STUDENT_LEGEND_RE, _STUDENT_COUNT_RE)


@page_parser(
    "professors",
    lambda soup: _professor_count(soup) is not None,
    empty=lambda soup: _professor_count(soup) == 0,
    validate=lambda result, soup: len(result) == _professor_count(soup),
    name="participants-role-count",
)
def parse_professors(soup: BeautifulSoup, id_turma: str) -> list[Professor]:
    """Teaching staff listed under the 'Professores' fieldset of a turma."""
    table = _role_table(soup, _PROFESSOR_LEGEND_RE)
    if table is None:
        return []

    professors: list[Professor] = []
    for row in table.select("tr"):
        name = _participant_name(row)
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


@page_parser(
    "classmates",
    lambda soup: _student_count(soup) is not None,
    empty=lambda soup: _student_count(soup) == 0,
    validate=lambda result, soup: len(result) == _student_count(soup),
    name="participants-role-count",
)
def parse_classmates(soup: BeautifulSoup, id_turma: str) -> list[Classmate]:
    """Names of the students listed under the 'Alunos' fieldset of a turma.

    Unlike the teachers' table, the roster holds two students per row, so each
    name is read from its own cell.
    """
    table = _role_table(soup, _STUDENT_LEGEND_RE)
    if table is None:
        return []
    names = (_participant_name(cell) for cell in table.select("td"))
    return [Classmate(id_turma=id_turma, name=name) for name in names if name]


def _participant_name(element) -> str:
    name_el = element.select_one("strong")
    return name_el.get_text(" ", strip=True) if name_el else ""


def _role_table(soup: BeautifulSoup, legend_re: re.Pattern):
    """The participantes table that follows a role's 'Role (n)' legend.

    SIGAA renders one table per role, each preceded by its own fieldset legend,
    so the role is identified by the legend rather than by table position.
    """
    legend = _role_legend(soup, legend_re)
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
